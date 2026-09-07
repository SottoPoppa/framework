import asyncio
import inspect
import uuid
from typing import Any

from .context import ExecutionContext
from .execution import Executor
from .graph import Dag, NodeNotFound
from .model import DagDefinition
from .session import NodeState, Session


class DependencyFailed(Exception):
    """Sollevata quando un nodo non può essere eseguito a causa del fallimento di una dipendenza."""
    pass


class DagRunner:

    def __init__(self, registry=None, *, concurrency: int = 32):
        self.registry = registry
        self.executor = Executor(self.registry)
        self.dags: dict[str, Dag] = {}
        self.sessions: dict[str, Session] = {}
        self._sem = asyncio.Semaphore(concurrency)

    def register(self, dag: Dag | DagDefinition) -> Dag:
        """Registra un DAG accettando sia un'istanza di Dag che un DagDefinition."""
        dag_obj = Dag(dag) if isinstance(dag, DagDefinition) else dag
        self.dags[dag_obj.name] = dag_obj
        return dag_obj

    async def create_session(
        self, dag_name: str, *, initial_context: dict[str, Any] | None = None
    ) -> Session:
        dag = self.dags[dag_name]
        sid = uuid.uuid4().hex

        raw_ctx = dict(getattr(dag.definition, "context", {}))
        raw_ctx.update(initial_context or {})

        context = ExecutionContext()
        session = Session(dag.name, sid, context)
        self.sessions[sid] = session

        # Risoluzione asincrona del contesto iniziale
        for key, expr in raw_ctx.items():
            resolved_val = await self.executor.execute(expr, context)
            context.set(key, resolved_val)

        for node_name in dag.nodes:
            session.mark(node_name, NodeState.PENDING)

        return session

    async def run(
        self, dag_name: str, *, session: Session | None = None
    ) -> Session:
        dag = self.dags[dag_name]
        session = session or await self.create_session(dag_name)

        await asyncio.gather(
            *(self._run_node(dag, session, n) for n in dag.entries())
        )
        return session

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

    async def wait(self, session_id: str, node: str) -> Any:
        """Attendi il completamento di un determinato nodo in una sessione."""
        return await self.sessions[session_id].wait(node)

    async def emit(
        self, session_id: str, node: str, payload: Any = None
    ) -> None:
        """Invia un evento/payload e attiva direttamente un nodo."""
        s = self.sessions[session_id]
        dag = self.dags[s.dag_name]

        if node not in dag.nodes:
            raise NodeNotFound(node)

        s.context.set(f"events.{node}", payload)
        return await self._run_node(dag, s, node)

    def close_session(self, session_id: str) -> None:
        """Rimuove e chiude una sessione attiva."""
        self.sessions.pop(session_id, None)