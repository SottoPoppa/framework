import asyncio
import inspect
import uuid
from typing import Any

import framework.core.flow as flow

from .context import ExecutionContext
from .execution import Executor
from .graph import Dag, NodeNotFound
from .model import DagDefinition
from .session import NodeState, Session


class DependencyFailed(Exception):
    """Sollevata quando un nodo non può essere eseguito a causa del fallimento di una dipendenza."""
    pass


class DagRunner:

    def __init__(self, registry=None, executor=None, *, concurrency: int = 32):
        self.registry = registry
        self.executor = executor or Executor(self.registry)
        self.dags: dict[str, Dag] = {}
        self.sessions: dict[str, Session] = {}
        self._source_tasks: dict[str, dict[str, asyncio.Task]] = {}
        self._sem = asyncio.Semaphore(concurrency)

    def register(self, dag: Dag | DagDefinition) -> Dag:
        """Registra un DAG accettando sia un'istanza di Dag che un DagDefinition."""
        dag_obj = Dag(dag) if isinstance(dag, DagDefinition) else dag
        self.dags[dag_obj.name] = dag_obj
        return dag_obj

    async def create_session(
        self,
        dag_name: str,
        *,
        initial_context: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
        resolve_context: bool = True,
    ) -> Session:
        dag = self.dags[dag_name]
        sid = uuid.uuid4().hex

        raw_ctx = dict(getattr(dag.definition, "context", {}))
        raw_ctx.update(initial_context or {})

        execution_context = context or ExecutionContext()
        session = Session(dag.name, sid, execution_context)
        self.sessions[sid] = session

        if resolve_context:
            # Struttura il contesto in namespace separati per evitare ambiguità
            # - shared: variabili da altri controller DSL (esplicite tramite shared.*)
            # - session: l'oggetto sessione per accesso metadati
            # - local: spazio locale (vuoto all'inizio, riempito dal DSL)
            shared_context = {}
            for key, expr in raw_ctx.items():
                resolved_val = await self.executor.execute(expr, execution_context)
                shared_context[key] = resolved_val
            
            execution_context.set('shared', shared_context)

        for node_name in dag.nodes:
            session.mark(node_name, NodeState.PENDING)

        return session

    async def run(
        self, dag_name: str, *, session: Session | None = None
    ) -> Session:
        dag = self.dags[dag_name]
        session = session or await self.create_session(dag_name)

        regular_entries = []
        for node_name in dag.entries():
            if getattr(dag.get(node_name), "metadata", {}).get("source") is True:
                self._start_source(dag, session, node_name)
            else:
                regular_entries.append(self._run_node(dag, session, node_name))

        if regular_entries:
            await asyncio.gather(*regular_entries)
        return session

    def _start_source(self, dag: Dag, session: Session, node_name: str) -> None:
        tasks = self._source_tasks.setdefault(session.id, {})
        current = tasks.get(node_name)
        if current and not current.done():
            return
        task = asyncio.create_task(self._run_source(dag, session, node_name))
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
                value = await self.executor.execute(node.action, session.context)
                if flow.is_result(value):
                    if not flow.check(value):
                        session.errors[node_name] = value
                        session.mark(node_name, NodeState.FAILED)
                        flow._dev_log("dag.source.failed node=%s", node_name)
                        return
                    value = flow.output(value)
                session.results[node_name] = value
                session.context.set(node_name, value)
                flow._dev_log(
                    "dag.source.received node=%s payload_type=%s",
                    node_name,
                    type(value).__name__,
                )
                await self._run_source_event(dag, session, event_node, value)
        except asyncio.CancelledError:
            session.mark(node_name, NodeState.PENDING)
            flow._dev_log("dag.source.cancelled node=%s", node_name)
            raise
        except Exception as exc:
            session.errors[node_name] = exc
            session.mark(node_name, NodeState.FAILED)
            flow._dev_log(
                "dag.source.error node=%s error=%r",
                node_name,
                exc,
            )

    async def _run_source_event(
        self, dag: Dag, session: Session, node_name: str, payload: Any
    ) -> None:
        node = dag.get(node_name)
        session.context.set(f"events.{node_name}", payload)
        for output in node.outputs:
            session.context.set(output, payload)
        self._reset_subgraph(dag, session, node_name)
        flow._dev_log(
            "dag.source.event source=%s target=%s",
            node_name,
            node_name,
        )
        await self._run_node(dag, session, node_name)

    async def _run_node(self, dag: Dag, s: Session, n: str) -> None:
        node = dag.get(n)

        # Se il nodo è già in uno stato finale, non rieseguire
        if s.states.get(n) in (
            NodeState.SUCCESS,
            NodeState.FAILED,
            NodeState.SKIPPED,
        ):
            return

        # 1. Verifica e attesa delle dipendenze
        for dep in node.deps:
            # Se la dipendenza è un altro nodo task nel DAG, attendi il suo completamento
            if dep in dag.nodes:
                await s.wait(dep)
                if s.states.get(dep) != NodeState.SUCCESS:
                    s.errors[n] = DependencyFailed(
                        f"Node {n!r} blocked by failed/skipped dependency {dep!r}"
                    )
                    s.mark(n, NodeState.SKIPPED)
                    return

        # 2. Esecuzione con Gestione Concorrenza e Retry
        async with self._sem:
            s.mark(n, NodeState.RUNNING)
            attempt = 0
            max_retries = getattr(node, "retries", 0)
            retry_delay = getattr(node, "retry_delay", 0)
            timeout = getattr(node, "timeout", None)

            while True:
                try:
                    metadata = getattr(node, "metadata", {})
                    if s.context.get(n) is None and "default" in metadata:
                        default = await self.executor.execute(
                            metadata["default"], s.context
                        )
                        if default is not None:
                            s.context.set(n, default)

                    # ---> FIX 1: Usa node.action invece di node.spec <---
                    exec_coro = self.executor.execute(node.action, s.context)

                    if inspect.isawaitable(exec_coro):
                        if timeout:
                            value = await asyncio.wait_for(
                                exec_coro, timeout=timeout
                            )
                        else:
                            value = await exec_coro
                    else:
                        value = exec_coro

                    # Salvataggio del risultato nel contesto e nella mappa della sessione
                    s.results[n] = value
                    s.context.set(n, value)
                    s.mark(n, NodeState.SUCCESS)

                    # ---> FIX 2: Usa il metodo dag.successors(n) se 'successors' è un metodo <---
                    successors = (
                        dag.successors(n)
                        if callable(getattr(dag, "successors", None))
                        else dag.successors.get(n, [])
                    )

                    # Attiva in parallelo tutti i nodi successori
                    await asyncio.gather(
                        *(self._run_node(dag, s, child) for child in successors)
                    )
                    return

                except Exception as exc:
                    if attempt >= max_retries:
                        s.errors[n] = exc
                        s.mark(n, NodeState.FAILED)
                        return

                    attempt += 1
                    if retry_delay:
                        await asyncio.sleep(retry_delay)

    async def wait(self, session: Session, node: str) -> Any:
        """Attendi il completamento di un determinato nodo in una sessione."""
        return await session.wait(node)

    async def emit(
        self, session: Session, node: str, payload: Any = None
    ) -> None:
        """Invia un evento/payload e attiva direttamente un nodo."""
        dag = self.dags[session.dag_name]

        if node not in dag.nodes:
            raise NodeNotFound(node)

        session.context.set(f"events.{node}", payload)
        for output in dag.get(node).outputs:
            session.context.set(output, payload)
        self._reset_subgraph(dag, session, node)
        await self._run_node(dag, session, node)
        on_end = dag.get(node).on_end
        if on_end and on_end in dag.nodes:
            self._reset_subgraph(dag, session, on_end)
            await self._run_node(dag, session, on_end)
        return session.results.get(node)

    def _reset_subgraph(self, dag: Dag, session: Session, node: str) -> None:
        pending = [node]
        visited = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            session.results.pop(current, None)
            session.errors.pop(current, None)
            session.mark(current, NodeState.PENDING)
            pending.extend(dag.successors.get(current, ()))

    def close_session(self, session: Session) -> None:
        """Rimuove e chiude una sessione attiva."""
        for task in self._source_tasks.pop(session.id, {}).values():
            task.cancel()
        self.sessions.pop(session.id, None)