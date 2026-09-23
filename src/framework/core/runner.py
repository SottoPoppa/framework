"""Orchestrazione dell'esecuzione di un DAG.

Il runner possiede solo runtime: task, eventi, semafori. Lo stato osservabile
di un'esecuzione si ottiene con ``Session.report()``, che è puro.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import framework.core.flow as flow

from .evaluation import Evaluator
from .graph import Dag, NodeNotFound
from .model import DagDefinition
from .scope import Scope
from .session import NodeState, Session


class DependencyFailed(Exception):
    """Un nodo non è eseguibile perché una sua dipendenza è fallita o saltata."""


class _Failed:
    """Sentinella interna: il nodo è già stato marcato come fallito."""

    __slots__ = ()


_FAILED = _Failed()


class DagRunner:

    def __init__(self, registry=None, evaluator: Evaluator | None = None, *, concurrency: int = 32):
        self.registry = registry
        self.evaluator = evaluator or Evaluator(registry)
        self.dags: dict[str, Dag] = {}
        self.sessions: dict[str, Session] = {}
        self._source_tasks: dict[str, dict[str, asyncio.Task]] = {}
        self._sem = asyncio.Semaphore(concurrency)

    # ── registrazione ────────────────────────────────────────────────────────

    def register(self, dag: Dag | DagDefinition) -> Dag:
        """Registra un DAG accettando sia un'istanza di Dag che un DagDefinition."""
        dag_obj = Dag(dag) if isinstance(dag, DagDefinition) else dag
        self.dags[dag_obj.name] = dag_obj
        return dag_obj

    # ── sessioni di esecuzione ───────────────────────────────────────────────

    async def create_session(
        self,
        dag_name: str,
        *,
        initial_context: dict[str, Any] | None = None,
        context: Scope | None = None,
        user_session=None,
        runtime_session=None,
        resolve_context: bool = True,
    ) -> Session:
        dag = self.dags[dag_name]
        session = Session(
            dag.name,
            uuid.uuid4().hex,
            context if context is not None else Scope(),
            user_session=user_session,
            runtime_session=runtime_session,
        )
        self.sessions[session.id] = session

        if resolve_context:
            declared = dict(getattr(dag.definition, "context", {}))
            declared.update(initial_context or {})
            for key, expression in declared.items():
                value = await self.evaluator.evaluate(
                    expression, session.context, session=session
                )
                session.context.set(key, value)

        for node_name in dag.nodes:
            session.mark(node_name, NodeState.PENDING)

        return session

    async def close_session(self, session: Session) -> None:
        """Chiude una sessione attendendo la cancellazione dei task source."""
        tasks = self._source_tasks.pop(session.id, {})
        for task in tasks.values():
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        self.sessions.pop(session.id, None)

    # ── esecuzione ───────────────────────────────────────────────────────────

    async def run(self, dag_name: str, *, session: Session | None = None) -> Session:
        dag = self.dags[dag_name]
        session = session or await self.create_session(dag_name)

        entries = []
        for node_name in dag.entries():
            if getattr(dag.get(node_name), "metadata", {}).get("source") is True:
                self._start_source(dag, session, node_name)
            else:
                entries.append(node_name)

        if entries:
            async with asyncio.TaskGroup() as group:
                for node_name in entries:
                    group.create_task(self._run_node(dag, session, node_name))
        return session

    # ── nodi source ──────────────────────────────────────────────────────────

    def _start_source(self, dag: Dag, session: Session, node_name: str) -> None:
        tasks = self._source_tasks.setdefault(session.id, {})
        current = tasks.get(node_name)
        if current and not current.done():
            return
        task = asyncio.create_task(
            self._run_source(dag, session, node_name),
            name=f"source:{session.dag_name}.{node_name}",
        )
        tasks[node_name] = task

        def clear_completed(completed: asyncio.Task) -> None:
            if tasks.get(node_name) is completed:
                tasks.pop(node_name, None)

        task.add_done_callback(clear_completed)

    async def _run_source(self, dag: Dag, session: Session, node_name: str) -> None:
        node = dag.get(node_name)
        session.mark(node_name, NodeState.RUNNING)
        event_node = getattr(node, "metadata", {}).get("on_event")
        flow._dev_log(
            "dag.source.start node=%s event=%s session=%s",
            node_name,
            event_node,
            session.id,
        )

        try:
            if not event_node or event_node not in dag.nodes:
                raise NodeNotFound(
                    f"Source node {node_name!r} references missing event node {event_node!r}"
                )

            while True:
                value = await self.evaluator.evaluate(
                    node.action, session.context, session=session
                )
                if flow.is_result(value):
                    if not flow.check(value):
                        session.errors[node_name] = value
                        session.mark(node_name, NodeState.FAILED)
                        flow._dev_log("dag.source.failed node=%s", node_name)
                        return
                    value = flow.output(value)

                self._publish(session, node_name, value)
                flow._dev_log(
                    "dag.source.received node=%s payload_type=%s",
                    node_name,
                    type(value).__name__,
                )
                flow._dev_log(
                    "dag.source.event source=%s target=%s", node_name, event_node
                )
                self._bind_event(dag, session, event_node, value)
                await self._run_node(dag, session, event_node)
        except asyncio.CancelledError:
            session.mark(node_name, NodeState.PENDING)
            flow._dev_log("dag.source.cancelled node=%s", node_name)
            raise
        except Exception as exc:
            session.errors[node_name] = exc
            session.mark(node_name, NodeState.FAILED)
            flow._dev_log("dag.source.error node=%s error=%r", node_name, exc)

    # ── esecuzione di un nodo ────────────────────────────────────────────────

    async def _run_node(self, dag: Dag, session: Session, name: str) -> None:
        node = dag.get(name)

        if session.states.get(name) in (
            NodeState.SUCCESS,
            NodeState.FAILED,
            NodeState.SKIPPED,
        ):
            return

        if not await self._dependencies_ready(dag, session, node, name):
            return

        async with self._sem:
            session.mark(name, NodeState.RUNNING)
            value = await self._execute_with_retry(session, node, name)
            if value is _FAILED:
                return
            self._publish(session, name, value)
            session.mark(name, NodeState.SUCCESS)

        successors = dag.successors.get(name, ())
        if successors:
            async with asyncio.TaskGroup() as group:
                for child in successors:
                    group.create_task(self._run_node(dag, session, child))

    async def _dependencies_ready(self, dag: Dag, session: Session, node, name: str) -> bool:
        for dep in node.deps:
            if dep not in dag.nodes:
                continue
            await session.wait(dep)
            if session.states.get(dep) != NodeState.SUCCESS:
                session.errors[name] = DependencyFailed(
                    f"Node {name!r} blocked by failed/skipped dependency {dep!r}"
                )
                session.mark(name, NodeState.SKIPPED)
                return False
        return True

    async def _execute_with_retry(self, session: Session, node, name: str) -> Any:
        attempt = 0
        max_retries = getattr(node, "retries", 0)
        retry_delay = getattr(node, "retry_delay", 0)
        timeout = getattr(node, "timeout", None)

        while True:
            try:
                await self._apply_default(session, node, name)
                coroutine = self.evaluator.evaluate(
                    node.action, session.context, session=session
                )
                value = (
                    await asyncio.wait_for(coroutine, timeout=timeout)
                    if timeout
                    else await coroutine
                )

                if flow.is_result(value) and not flow.check(value):
                    session.results[name] = value
                    session.errors[name] = flow.output(value)
                    session.mark(name, NodeState.FAILED)
                    flow._dev_log(
                        "dag.node.failed",
                        controller=session.dag_name,
                        node=name,
                        error=flow._safe_log_value(flow.output(value)),
                        success=False,
                    )
                    return _FAILED
                return value

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt >= max_retries:
                    session.errors[name] = exc
                    session.mark(name, NodeState.FAILED)
                    flow._dev_log(
                        "dag.node.error",
                        controller=session.dag_name,
                        node=name,
                        error_message=str(exc),
                        exception=exc,
                        exc_info=True,
                    )
                    return _FAILED
                attempt += 1
                if retry_delay:
                    await asyncio.sleep(retry_delay)

    async def _apply_default(self, session: Session, node, name: str) -> None:
        metadata = getattr(node, "metadata", {})
        if "default" not in metadata or session.context.get(name) is not None:
            return
        default = await self.evaluator.evaluate(
            metadata["default"], session.context, session=session
        )
        if default is not None:
            session.context.set(name, default)

    async def wait(self, session: Session, node: str) -> Any:
        """Attende il completamento di un nodo della sessione."""
        return await session.wait(node)

    async def emit(self, session: Session, node: str, payload: Any = None) -> Any:
        """Consegna un payload a un nodo e propaga la catena `on_end`."""
        dag = self.dags[session.dag_name]

        if node not in dag.nodes:
            raise NodeNotFound(node)

        session.context.set("payload", payload)
        self._bind_event(dag, session, node, payload)
        await self._run_node(dag, session, node)
        if session.states.get(node) != NodeState.SUCCESS:
            return flow.error(
                session.errors.get(node, f"Nodo DAG fallito: {node}")
            )
        current = node
        visited = {node}
        while session.states.get(current) == NodeState.SUCCESS:
            on_end = dag.get(current).on_end
            if not on_end or on_end not in dag.nodes or on_end in visited:
                break
            visited.add(on_end)
            self._reset_subgraph(dag, session, on_end)
            await self._run_node(dag, session, on_end)
            if session.states.get(on_end) != NodeState.SUCCESS:
                return flow.error(
                    session.errors.get(on_end, f"Nodo DAG fallito: {on_end}")
                )
            current = on_end
        return session.results.get(node)

    # ── stato condiviso ──────────────────────────────────────────────────────

    def _publish(self, session: Session, name: str, value: Any) -> None:
        """Registra il risultato nel runtime e ne pubblica la forma pura."""
        session.results[name] = value
        session.context.set(name, value)
        if session.user_session is not None:
            payload = flow.output(value) if flow.is_result(value) else value
            session.user_session.publish_result(session.dag_name, name, payload)

    def _bind_event(self, dag: Dag, session: Session, node: str, payload: Any) -> None:
        session.context.set(f"events.{node}", payload)
        for output in dag.get(node).outputs:
            session.context.set(output, payload)
        self._reset_subgraph(dag, session, node)

    def _reset_subgraph(self, dag: Dag, session: Session, node: str) -> None:
        pending = [node]
        visited = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            session.results.pop(current, None)
            if session.user_session is not None:
                session.user_session.clear_result(session.dag_name, current)
            session.errors.pop(current, None)
            session.mark(current, NodeState.PENDING)
            pending.extend(dag.successors.get(current, ()))
