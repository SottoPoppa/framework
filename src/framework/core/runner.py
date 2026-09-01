"""
framework.service.runner
========================

DAG runner asincrono basato su ``framework.service.flow``.

Responsabilità:
- registrazione dei DAG
- gestione delle sessioni
- scheduling dei nodi
- risoluzione delle dipendenze
- esecuzione tramite ``flow.pipe()``
- retry dei nodi
- timeout
- condizioni ``when``
- hook
- cache
- trigger
- scheduling periodico
- propagazione degli output nel context
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import networkx as nx

import framework.core.flow as flow
import framework.core.scheme as scheme


# =============================================================================
# SCHEME
# =============================================================================

class Node(scheme.Scheme):
    """
    Definizione di un nodo del DAG.
    """

    SCHEME = {
        "name": {
            "required": True,
            "nullable": False,
        },
        "fn": {
            "required": True,
            "nullable": False,
        },
        "default": {
            "required": False,
            "nullable": True,
            "default": None,
        },
        "deps": {
            "required": False,
            "nullable": True,
            "default": [],
        },
        "policy": {
            "required": False,
            "nullable": True,
            "default": "all",
        },
        "meta": {
            "required": False,
            "nullable": True,
            "default": False,
        },
        "trigger": {
            "required": False,
            "nullable": True,
            "default": None,
        },
        "schedule": {
            "required": False,
            "nullable": True,
            "default": None,
        },
        "duration": {
            "required": False,
            "nullable": True,
            "default": None,
        },
        "timeout": {
            "required": False,
            "nullable": True,
            "default": 30,
        },
        "retries": {
            "required": False,
            "nullable": True,
            "default": 0,
        },
        "retry_delay": {
            "required": False,
            "nullable": True,
            "default": 0,
        },
        "when": {
            "required": False,
            "nullable": True,
            "default": None,
        },
        "path": {
            "required": False,
            "nullable": True,
        },
        "cache": {
            "required": False,
            "nullable": True,
            "default": False,
        },
        "on_start": {
            "required": False,
            "nullable": True,
        },
        "on_success": {
            "required": False,
            "nullable": True,
        },
        "on_error": {
            "required": False,
            "nullable": True,
        },
        "on_end": {
            "required": False,
            "nullable": True,
        },
        "entry": {
            "required": False,
            "nullable": True,
            "default": True,
        },
    }


class ExecutionContext(scheme.Scheme):
    """
    Contesto immutabile di una singola esecuzione di nodo.

    Lo stato mutabile della sessione è contenuto in SessionState.
    """

    SCHEME = {
        "sid": {
            "required": True,
            "nullable": False,
            "type": str,
        },
        "fname": {
            "required": True,
            "nullable": False,
            "type": str,
        },
        "node": {
            "required": True,
            "nullable": False,
        },
        "started_at": {
            "required": True,
            "nullable": False,
            "type": (int, float),
        },
    }


# =============================================================================
# SESSION
# =============================================================================

@dataclass
class SessionState:
    """
    Stato runtime persistente di una sessione.
    """

    ctx: Dict[str, Any]
    results: Dict[str, flow.Result]
    done: Dict[str, asyncio.Event]
    schedulers: Dict[str, asyncio.Task]
    running_files: set[str]
    last_seen: Dict[str, Any]

    @classmethod
    def create(cls) -> "SessionState":
        return cls(
            ctx={},
            results={},
            done={},
            schedulers={},
            running_files=set(),
            last_seen={},
        )


class NodeExecution:
    """
    Runtime state mutabile di una singola esecuzione.

    ExecutionContext contiene l'identità dell'esecuzione.
    SessionState contiene lo stato persistente.
    """

    __slots__ = (
        "context",
        "session",
        "result",
        "skipped",
        "skip_reason",
    )

    def __init__(
        self,
        context: ExecutionContext,
        session: SessionState,
    ):
        self.context = context
        self.session = session

        self.result: Optional[flow.Result] = None

        self.skipped = False
        self.skip_reason: Optional[str] = None

    # -------------------------------------------------------------------------
    # Shortcut
    # -------------------------------------------------------------------------

    @property
    def sid(self) -> str:
        return self.context.sid

    @property
    def fname(self) -> str:
        return self.context.fname

    @property
    def node(self):
        return self.context.node

    @property
    def ctx(self) -> Dict[str, Any]:
        return self.session.ctx

    @property
    def results(self) -> Dict[str, flow.Result]:
        return self.session.results

    @property
    def started_at(self) -> float:
        return self.context.started_at


# =============================================================================
# EXCEPTIONS
# =============================================================================

class DagError(Exception):
    """Errore generico del DAG."""


class DependencyError(DagError):
    """Errore permanente nelle dipendenze."""


class DependencyPending(DagError):
    """
    Il nodo non è ancora eseguibile.

    Non rappresenta un errore del nodo:
    il runner lo rimetterà in coda.
    """


# =============================================================================
# HELPERS
# =============================================================================

def _set(context: Dict[str, Any], path: Optional[str], value: Any) -> None:
    if not path:
        return

    parts = path.split(".")

    for part in parts[:-1]:
        current = context.get(part)

        if not isinstance(current, dict):
            current = {}
            context[part] = current

        context = current

    context[parts[-1]] = value


def _set_default(
    context: Dict[str, Any],
    path: Optional[str],
    value: Any,
) -> None:
    if not path:
        return

    parts = path.split(".")

    for part in parts[:-1]:
        current = context.get(part)

        if not isinstance(current, dict):
            current = {}
            context[part] = current

        context = current

    context.setdefault(parts[-1], value)


def _get(
    context: Dict[str, Any],
    path: Optional[str],
    default: Any = None,
) -> Any:
    if not path:
        return default

    current: Any = context

    for part in path.split("."):
        if not isinstance(current, dict):
            return default

        if part not in current:
            return default

        current = current[part]

    return current


def _deep_merge_defaults(
    target: Dict[str, Any],
    source: Dict[str, Any],
) -> None:
    """
    Merge ricorsivo dove i valori già presenti in target hanno priorità.

    Serve per ctx_update:
        target = stato persistente
        source = dati della request
    """

    for key, value in source.items():

        if (
            key in target
            and isinstance(target[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge_defaults(target[key], value)
            continue

        if key not in target:
            target[key] = value


def _key(file: str, name: str) -> str:
    return f"{file}::{name}"


def _output_of(result: flow.Result) -> Any:
    """
    Estrae il valore dal Result del modulo flow.

    Result
        -> output
            -> Success
                -> value
    """

    if not isinstance(result, flow.Result):
        return result

    output = result.output

    if isinstance(output, flow.Success):
        return output.value

    if isinstance(output, flow.Failure):
        return output.error

    return output


def _result_success(result: Optional[flow.Result]) -> bool:
    if result is None:
        return False

    return result.is_success


async def _invoke_callable(
    fn,
    *args,
    **kwargs,
):
    """
    Invocazione esplicita di callback/hook/when.

    Per l'esecuzione dei nodi viene usato flow.pipe().
    """

    value = fn(*args, **kwargs)

    if inspect.isawaitable(value):
        value = await value

    return value


# =============================================================================
# DAG RUNNER
# =============================================================================

class DagRunner:

    def __init__(self, workers: int = 3):
        if workers < 1:
            raise ValueError("workers deve essere >= 1")

        self.workers = workers

        # fname -> DiGraph
        self.graphs: Dict[str, nx.DiGraph] = {}

        # fname -> node_name -> Node
        self.nodes: Dict[str, Dict[str, Node]] = {}

        # fname -> trigger_name -> [node_name]
        self.triggers: Dict[str, Dict[str, List[str]]] = {}

        # fname -> defaults
        self._file_defaults: Dict[str, Dict[str, Any]] = {}

        # sid -> SessionState
        self.sessions: Dict[str, SessionState] = {}

        self.queue: asyncio.Queue = asyncio.Queue()

        self.tasks: List[asyncio.Task] = []

        self.running = False

        self.cancelled_sessions: set[str] = set()

        self._start_lock = asyncio.Lock()

    # =========================================================================
    # FILE
    # =========================================================================

    async def add_file(
        self,
        name: str,
        nodes: List[Dict[str, Any] | Node],
    ) -> None:

        normalized: List[Node] = []

        for raw in nodes:

            if isinstance(raw, Node):
                node = raw
            else:
                node = Node(raw)

            normalized.append(node)

        graph = nx.DiGraph()

        node_map = {
            node.name: node
            for node in normalized
        }

        triggers: Dict[str, List[str]] = {}

        # ---------------------------------------------------------------------
        # Nodes
        # ---------------------------------------------------------------------

        for node in normalized:
            graph.add_node(node.name)

        # ---------------------------------------------------------------------
        # Dependencies
        # ---------------------------------------------------------------------

        for node in normalized:

            for dependency in node.deps or ():

                if dependency not in node_map:
                    raise ValueError(
                        f"Il nodo '{node.name}' dipende da "
                        f"'{dependency}', ma il nodo non esiste "
                        f"nel file '{name}'."
                    )

                graph.add_edge(
                    dependency,
                    node.name,
                )

        # ---------------------------------------------------------------------
        # Triggers
        # ---------------------------------------------------------------------

        for node in normalized:

            trigger = node.trigger

            if trigger:
                triggers.setdefault(
                    trigger,
                    [],
                ).append(node.name)

        # ---------------------------------------------------------------------
        # DAG validation
        # ---------------------------------------------------------------------

        if not nx.is_directed_acyclic_graph(graph):
            cycle = nx.find_cycle(graph)

            raise ValueError(
                f"Il file '{name}' contiene un ciclo: {cycle}"
            )

        # ---------------------------------------------------------------------
        # Store
        # ---------------------------------------------------------------------

        self.graphs[name] = graph
        self.nodes[name] = node_map
        self.triggers[name] = triggers

        self._file_defaults[name] = {
            node.name: node.default
            for node in normalized
            if node.default is not None
        }

        # ---------------------------------------------------------------------
        # Inject defaults into existing sessions
        # ---------------------------------------------------------------------

        for session in self.sessions.values():

            for path, value in self._file_defaults[name].items():
                _set_default(
                    session.ctx,
                    path,
                    value,
                )

    async def delete_file(self, name: str) -> None:

        # Cancella eventuali scheduler relativi al file.
        for session in self.sessions.values():

            to_remove = [
                key
                for key in session.schedulers
                if key.startswith(f"{name}::")
            ]

            for key in to_remove:

                task = session.schedulers.pop(key)

                task.cancel()

        self.graphs.pop(name, None)
        self.nodes.pop(name, None)
        self.triggers.pop(name, None)
        self._file_defaults.pop(name, None)

    def attach_node(
        self,
        fname: str,
        node_def: Dict[str, Any] | Node,
    ) -> None:

        if fname not in self.graphs:
            raise ValueError(
                f"File '{fname}' non registrato."
            )

        node = (
            node_def
            if isinstance(node_def, Node)
            else Node(node_def)
        )

        if node.name in self.nodes[fname]:
            return

        # Verifica dipendenze prima di modificare il grafo.
        for dependency in node.deps or ():

            if dependency not in self.nodes[fname]:
                raise ValueError(
                    f"Il nodo '{node.name}' dipende da "
                    f"'{dependency}', inesistente."
                )

        graph = self.graphs[fname]

        graph.add_node(node.name)

        for dependency in node.deps or ():
            graph.add_edge(
                dependency,
                node.name,
            )

        if not nx.is_directed_acyclic_graph(graph):

            graph.remove_node(node.name)

            raise ValueError(
                f"L'aggiunta del nodo '{node.name}' "
                f"crea un ciclo."
            )

        self.nodes[fname][node.name] = node

        if node.trigger:
            self.triggers[fname].setdefault(
                node.trigger,
                [],
            ).append(node.name)

        if node.default is not None:

            self._file_defaults[fname][node.name] = node.default

            for session in self.sessions.values():

                _set_default(
                    session.ctx,
                    node.name,
                    node.default,
                )

    # =========================================================================
    # SESSION
    # =========================================================================

    def create_session(
        self,
        sid: str,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> SessionState:

        session = self.sessions.get(sid)

        if session is None:

            session = SessionState.create()

            self.sessions[sid] = session

        # Defaults con priorità minima.
        for defaults in self._file_defaults.values():

            for path, value in defaults.items():

                _set_default(
                    session.ctx,
                    path,
                    value,
                )

        if ctx:
            session.ctx.update(ctx)

        # Una nuova sessione non è più cancellata.
        self.cancelled_sessions.discard(sid)

        return session

    def context(self, sid: str) -> Dict[str, Any]:

        session = self.sessions.get(sid)

        if session is None:
            return {}

        return session.ctx

    # =========================================================================
    # RUN FILE
    # =========================================================================

    async def run_file(
        self,
        sid: str,
        fname: str,
        ctx_update: Optional[Dict[str, Any]] = None,
    ):

        if sid not in self.sessions:
            raise ValueError(
                f"FLOW -> Sessione '{sid}' non trovata."
            )

        if fname not in self.graphs:
            raise ValueError(
                f"File '{fname}' non registrato."
            )

        session = self.sessions[sid]

        # ---------------------------------------------------------------------
        # Request context
        # ---------------------------------------------------------------------

        if ctx_update:
            _deep_merge_defaults(
                session.ctx,
                ctx_update,
            )

        session.running_files.add(fname)

        # ---------------------------------------------------------------------
        # Events
        # ---------------------------------------------------------------------

        for node_name in self.nodes[fname]:

            session.done[
                _key(fname, node_name)
            ] = asyncio.Event()

        # ---------------------------------------------------------------------
        # Start workers
        # ---------------------------------------------------------------------

        if not self.running:
            await self.start()

        # ---------------------------------------------------------------------
        # Bootstrap
        # ---------------------------------------------------------------------

        for node_name in self.graphs[fname].nodes:

            node = self.nodes[fname][node_name]

            if self.graphs[fname].in_degree(node_name) != 0:
                continue

            if not self._auto_starts(
                fname,
                node_name,
            ):
                continue

            if node.entry:
                self._enqueue(
                    sid,
                    fname,
                    node_name,
                )

        # ---------------------------------------------------------------------
        # Wait
        # ---------------------------------------------------------------------

        try:

            waits = []

            for node_name, node in self.nodes[fname].items():

                if node.schedule:
                    continue

                if not self._auto_starts(
                    fname,
                    node_name,
                ):
                    continue

                key = _key(
                    fname,
                    node_name,
                )

                waits.append(
                    session.done[key].wait()
                )

            if waits:
                await asyncio.gather(*waits)

            else:
                # DAG puramente reattivo.
                #
                # Non possiamo aspettare indefinitamente nodi che
                # nessuno ha intenzione di attivare.
                reactive = [
                    session.done[
                        _key(fname, node_name)
                    ].wait()
                    for node_name in self.nodes[fname]
                ]

                if reactive:
                    await asyncio.gather(*reactive)

        finally:

            session.running_files.discard(fname)

        # ---------------------------------------------------------------------
        # Return
        # ---------------------------------------------------------------------

        return {
            node_name: session.results[key]
            for node_name in self.nodes[fname]
            if (
                key := _key(fname, node_name)
            ) in session.results
        }

    # =========================================================================
    # SESSION CLOSE
    # =========================================================================

    async def close_session(self, sid: str) -> None:

        session = self.sessions.get(sid)

        if session is None:
            return

        self.cancelled_sessions.add(sid)

        # Cancella scheduler.
        for task in session.schedulers.values():
            task.cancel()

        session.schedulers.clear()

        # Sblocca eventuali waiters.
        for event in session.done.values():

            if not event.is_set():
                event.set()

        self.sessions.pop(sid, None)

        async def cleanup():

            await asyncio.sleep(60)

            self.cancelled_sessions.discard(sid)

        asyncio.create_task(cleanup())

    async def clear_all_sessions(self) -> None:

        for sid in list(self.sessions):
            await self.close_session(sid)

    # =========================================================================
    # WORKERS
    # =========================================================================

    async def start(self) -> None:

        async with self._start_lock:

            if self.running:
                return

            self.running = True

            self.tasks = [
                asyncio.create_task(
                    self._worker(),
                    name=f"DagRunner-worker-{i}",
                )
                for i in range(self.workers)
            ]

    async def stop(self) -> None:

        self.running = False

        tasks = self.tasks
        self.tasks = []

        for task in tasks:
            task.cancel()

        if tasks:

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

    async def _worker(self) -> None:

        while self.running:

            try:

                item = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=0.2,
                )

            except asyncio.TimeoutError:
                continue

            sid, fname, name = item

            try:

                if sid in self.cancelled_sessions:
                    continue

                if sid not in self.sessions:
                    continue

                if fname not in self.nodes:
                    continue

                if name not in self.nodes[fname]:
                    continue

                await self._run_node(
                    sid,
                    fname,
                    name,
                )

            except asyncio.CancelledError:
                raise

            except Exception as exc:

                print(
                    f"[DAG] errore nodo "
                    f"{fname}::{name}: {exc!r}"
                )

                self._set_done(
                    sid,
                    fname,
                    name,
                )

            finally:
                self.queue.task_done()

    # =========================================================================
    # NODE
    # =========================================================================

    async def _run_node(
        self,
        sid: str,
        fname: str,
        name: str,
    ) -> None:

        session = self.sessions.get(sid)

        if session is None:
            return

        node = self.nodes[fname][name]

        key = _key(
            fname,
            name,
        )

        # ---------------------------------------------------------------------
        # Dependency gate
        #
        # Questo non viene messo dentro flow.pipe().
        #
        # DependencyPending non è un errore del flow:
        # significa semplicemente "non ancora".
        # ---------------------------------------------------------------------

        try:

            await self._check_dependencies(
                sid,
                fname,
                node,
            )

        except DependencyPending:

            self._retry_node(
                sid,
                fname,
                name,
            )

            return

        except DependencyError as exc:

            print(
                f"[DAG] dependency error "
                f"{key}: {exc}"
            )

            self._set_done(
                sid,
                fname,
                name,
            )

            return

        # ---------------------------------------------------------------------
        # Cache
        # ---------------------------------------------------------------------

        if self._can_use_cache(
            session,
            fname,
            node,
        ):

            self._set_done(
                sid,
                fname,
                name,
            )

            self._dispatch_cached(
                sid,
                fname,
                name,
            )

            return

        # ---------------------------------------------------------------------
        # ExecutionContext
        # ---------------------------------------------------------------------

        execution_context = ExecutionContext(
            sid=sid,
            fname=fname,
            node=node,
            started_at=time.perf_counter(),
        )

        execution = NodeExecution(
            execution_context,
            session,
        )

        # ---------------------------------------------------------------------
        # Pipeline
        #
        # Tutta l'orchestrazione del nodo passa da flow.pipe().
        # ---------------------------------------------------------------------

        steps = [
            self._handle_duration,
            self._check_when,
            self._run_on_start,
            self._execute_step,
            self._run_on_result_hooks,
            self._save_step,
            self._dispatch,
        ]

        timeout = node.timeout

        try:

            if timeout:

                await asyncio.wait_for(
                    flow.pipe(
                        execution,
                        *steps,
                        action="dag.node",
                        component=fname,
                    ),
                    timeout=float(timeout),
                )

            else:

                await flow.pipe(
                    execution,
                    *steps,
                    action="dag.node",
                    component=fname,
                )

        except asyncio.TimeoutError as exc:

            execution.result = flow.Result(
                input=execution.ctx,
                output=flow.Failure(exc),
                action=f"{fname}.{name}",
                component=fname,
            )

            await self._run_on_error(
                execution,
                exc,
            )

            await self._save_step(
                execution,
            )

        except Exception as exc:

            print(
                f"[DAG] errore pipeline "
                f"{key}: {exc!r}"
            )

            if execution.result is None:

                execution.result = flow.Result(
                    input=execution.ctx,
                    output=flow.Failure(exc),
                    action=f"{fname}.{name}",
                    component=fname,
                )

            await self._run_on_error(
                execution,
                exc,
            )

            try:
                await self._save_step(execution)
            except Exception:
                pass

        finally:

            self._set_done(
                sid,
                fname,
                name,
            )

    # =========================================================================
    # DEPENDENCIES
    # =========================================================================

    async def _check_dependencies(
        self,
        sid: str,
        fname: str,
        node: Node,
    ) -> None:

        session = self.sessions[sid]

        dependencies = list(node.deps or ())

        if not dependencies:
            return

        dependency_keys = [
            _key(fname, dep)
            for dep in dependencies
        ]

        # ---------------------------------------------------------------------
        # Pending
        # ---------------------------------------------------------------------

        if not node.cache:

            waiting = [
                key
                for key in dependency_keys
                if (
                    key in session.done
                    and not session.done[key].is_set()
                )
            ]

            if waiting:

                raise DependencyPending(
                    f"Waiting for dependencies: {waiting}"
                )

        # ---------------------------------------------------------------------
        # Results
        # ---------------------------------------------------------------------

        completed = [
            key
            for key in dependency_keys
            if key in session.results
        ]

        succeeded = [
            key
            for key in completed
            if _result_success(
                session.results[key]
            )
        ]

        failed = [
            key
            for key in completed
            if not _result_success(
                session.results[key]
            )
        ]

        policy = node.policy or "all"

        # ---------------------------------------------------------------------
        # ALL
        # ---------------------------------------------------------------------

        if policy == "all":

            if len(succeeded) == len(dependencies):
                return

            if failed:

                raise DependencyError(
                    f"policy=all failed: {failed}"
                )

            raise DependencyPending(
                "Non tutte le dipendenze hanno prodotto "
                "un risultato."
            )

        # ---------------------------------------------------------------------
        # ANY
        # ---------------------------------------------------------------------

        if policy == "any":

            if succeeded:
                return

            if len(completed) == len(dependencies):

                raise DependencyError(
                    f"policy=any failed: {failed}"
                )

            raise DependencyPending(
                "Nessuna dipendenza è ancora riuscita."
            )

        # ---------------------------------------------------------------------
        # QUORUM
        # ---------------------------------------------------------------------

        if isinstance(policy, int):

            if len(succeeded) >= policy:
                return

            if len(completed) == len(dependencies):

                raise DependencyError(
                    f"policy={policy} failed: "
                    f"{len(succeeded)} succeeded"
                )

            raise DependencyPending(
                f"policy={policy}: "
                f"{len(succeeded)} succeeded"
            )

        raise DependencyError(
            f"Unknown dependency policy: {policy!r}"
        )

    # =========================================================================
    # FLOW STEPS
    # =========================================================================

    async def _handle_duration(
        self,
        execution: NodeExecution,
    ):
        """
        Controlla il limite cumulativo ``duration``.

        Importante:
        ritorna sempre Success(execution) perché duration non deve
        rompere la pipeline tramite Failure.
        """

        node = execution.node

        maximum = node.duration

        if not maximum:
            return flow.Success(execution)

        previous = execution.results.get(
            _key(
                execution.fname,
                node.name,
            )
        )

        current = 0.0

        if previous is not None:
            current = previous.execution_time_ms / 1000.0

        if current >= float(maximum):

            execution.skipped = True
            execution.skip_reason = (
                f"Quota temporale esaurita "
                f"({current:.2f}s >= {maximum}s)"
            )

        return flow.Success(execution)

    async def _check_when(
        self,
        execution: NodeExecution,
    ):
        """
        Valuta ``when``.

        False = nodo skipped, non Failure.
        """

        if execution.skipped:
            return flow.Success(execution)

        fn = execution.node.when

        if not fn:
            return flow.Success(execution)

        try:

            payload = {
                "ctx": execution.ctx,
                "results": execution.results,
            }

            value = await _invoke_callable(
                fn,
                payload,
            )

            if not value:

                execution.skipped = True
                execution.skip_reason = (
                    "when condition not met"
                )

        except Exception as exc:

            execution.skipped = True
            execution.skip_reason = (
                f"when error: {exc}"
            )

        return flow.Success(execution)

    async def _run_on_start(
        self,
        execution: NodeExecution,
    ):
        if execution.skipped:
            return flow.Success(execution)

        await self._run_hook(
            execution,
            "on_start",
        )

        return flow.Success(execution)

    async def _execute_step(
        self,
        execution: NodeExecution,
    ):
        """
        Esegue il nodo usando flow.pipe().

        Il Result del nodo viene conservato in execution.result.
        Lo step restituisce sempre Success(execution), perché la
        Failure del nodo non deve impedire agli hook on_error/on_end
        e al salvataggio del risultato di essere eseguiti.
        """

        if execution.skipped:
            return flow.Success(execution)

        node = execution.node

        # ---------------------------------------------------------------------
        # Dependency outputs
        # ---------------------------------------------------------------------

        for dependency in node.deps or ():

            key = _key(
                execution.fname,
                dependency,
            )

            dependency_result = execution.results.get(key)

            if dependency_result is None:
                continue

            if node.meta:

                execution.ctx[
                    dependency
                ] = dependency_result

            else:

                execution.ctx[
                    dependency
                ] = _output_of(
                    dependency_result
                )

        # ---------------------------------------------------------------------
        # Execute with retries
        # ---------------------------------------------------------------------

        retries = max(
            0,
            int(node.retries or 0),
        )

        delay = max(
            0.0,
            float(node.retry_delay or 0),
        )

        last_result: Optional[flow.Result] = None

        for attempt in range(retries + 1):

            try:

                last_result = await flow.pipe(
                    execution.ctx,
                    node.fn,
                    action=f"{execution.fname}.{node.name}",
                    component=execution.fname,
                )

            except Exception as exc:

                last_result = flow.Result(
                    input=execution.ctx,
                    output=flow.Failure(exc),
                    action=f"{execution.fname}.{node.name}",
                    component=execution.fname,
                )

            if last_result.is_success:
                break

            if attempt < retries:
                await asyncio.sleep(delay)

        execution.result = last_result

        return flow.Success(execution)

    async def _run_on_result_hooks(
        self,
        execution: NodeExecution,
    ):
        if execution.skipped:
            return flow.Success(execution)

        result = execution.result

        if result is None:
            return flow.Success(execution)

        if result.is_success:

            await self._run_hook(
                execution,
                "on_success",
            )

        else:

            await self._run_on_error(
                execution,
                result.output.error
                if isinstance(
                    result.output,
                    flow.Failure,
                )
                else None,
            )

        await self._run_hook(
            execution,
            "on_end",
        )

        return flow.Success(execution)

    async def _run_on_error(
        self,
        execution: NodeExecution,
        error: Any,
    ):

        await self._run_hook(
            execution,
            "on_error",
            error=error,
        )

        await self._run_hook(
            execution,
            "on_end",
            error=error,
        )

    async def _run_hook(
        self,
        execution: NodeExecution,
        hook_name: str,
        error: Any = None,
    ) -> None:

        hook = execution.node.get(
            hook_name
        )

        if not hook:
            return

        try:

            # -----------------------------------------------------------------
            # String/list -> trigger nodi
            # -----------------------------------------------------------------

            if isinstance(hook, str):

                targets = [hook]

            elif isinstance(hook, (list, tuple)):

                targets = list(hook)

            else:

                targets = None

            if targets is not None:

                for target in targets:

                    if target not in self.nodes[
                        execution.fname
                    ]:
                        continue

                    self._prepare_event(
                        execution.sid,
                        execution.fname,
                        target,
                    )

                    self._enqueue(
                        execution.sid,
                        execution.fname,
                        target,
                    )

                return

            # -----------------------------------------------------------------
            # Callable
            # -----------------------------------------------------------------

            if callable(hook):

                payload = {
                    "execution": execution,
                    "ctx": execution.ctx,
                    "results": execution.results,
                    "result": execution.result,
                    "error": error,
                }

                await _invoke_callable(
                    hook,
                    payload,
                )

        except Exception as exc:

            print(
                f"[DAG] hook {hook_name} "
                f"su {execution.fname}::"
                f"{execution.node.name}: "
                f"{exc!r}"
            )

    async def _save_step(
        self,
        execution: NodeExecution,
    ):

        node = execution.node

        key = _key(
            execution.fname,
            node.name,
        )

        # ---------------------------------------------------------------------
        # Skipped
        # ---------------------------------------------------------------------

        if execution.skipped:

            result = flow.Result(
                input=execution.ctx,
                output=flow.Success(
                    None
                ),
                action=f"{execution.fname}.{node.name}",
                component=execution.fname,
                diagnostics={
                    "skipped": True,
                    "reason": execution.skip_reason,
                },
            )

            execution.result = result

        # ---------------------------------------------------------------------
        # Missing result
        # ---------------------------------------------------------------------

        elif execution.result is None:

            execution.result = flow.Result(
                input=execution.ctx,
                output=flow.Failure(
                    RuntimeError(
                        "Il nodo non ha prodotto un Result."
                    )
                ),
                action=f"{execution.fname}.{node.name}",
                component=execution.fname,
            )

        # ---------------------------------------------------------------------
        # Store
        # ---------------------------------------------------------------------

        execution.session.results[key] = (
            execution.result
        )

        # ---------------------------------------------------------------------
        # Context path
        # ---------------------------------------------------------------------

        if (
            node.path
            and execution.result.is_success
        ):

            _set(
                execution.ctx,
                node.path,
                _output_of(
                    execution.result
                ),
            )

        execution.session.last_seen[key] = (
            execution.result.execution_time_ms
        )

        return flow.Success(execution)

    async def _dispatch(
        self,
        execution: NodeExecution,
    ):

        if execution.skipped:
            return flow.Success(execution)

        session = execution.session

        fname = execution.fname
        name = execution.node.name

        key = _key(
            fname,
            name,
        )

        # ---------------------------------------------------------------------
        # Graph successors
        # ---------------------------------------------------------------------

        for next_node in self.graphs[
            fname
        ].successors(name):

            next_key = _key(
                fname,
                next_node,
            )

            node = self.nodes[
                fname
            ][next_node]

            if not node.cache:

                if next_key in session.done:
                    session.done[
                        next_key
                    ].clear()

            self._enqueue(
                execution.sid,
                fname,
                next_node,
            )

        # ---------------------------------------------------------------------
        # Triggers
        # ---------------------------------------------------------------------

        for target in self.triggers[
            fname
        ].get(name, []):

            self._prepare_event(
                execution.sid,
                fname,
                target,
            )

            self._enqueue(
                execution.sid,
                fname,
                target,
            )

        # ---------------------------------------------------------------------
        # Scheduler
        # ---------------------------------------------------------------------

        interval = execution.node.schedule

        if (
            interval
            and key not in session.schedulers
        ):

            session.schedulers[key] = (
                asyncio.create_task(
                    self._scheduler(
                        execution.sid,
                        fname,
                        name,
                        float(interval),
                    ),
                    name=f"dag-scheduler-{key}",
                )
            )

        return flow.Success(execution)

    # =========================================================================
    # CACHE
    # =========================================================================

    def _can_use_cache(
        self,
        session: SessionState,
        fname: str,
        node: Node,
    ) -> bool:

        if not node.cache:
            return False

        key = _key(
            fname,
            node.name,
        )

        if key not in session.results:
            return False

        return True

    def _dispatch_cached(
        self,
        sid: str,
        fname: str,
        name: str,
    ) -> None:

        session = self.sessions.get(sid)

        if session is None:
            return

        for next_node in self.graphs[
            fname
        ].successors(name):

            self._enqueue(
                sid,
                fname,
                next_node,
            )

    # =========================================================================
    # SCHEDULER
    # =========================================================================

    async def _scheduler(
        self,
        sid: str,
        fname: str,
        name: str,
        interval: float,
    ) -> None:

        key = _key(
            fname,
            name,
        )

        try:

            while (
                sid in self.sessions
                and sid not in self.cancelled_sessions
            ):

                await asyncio.sleep(interval)

                session = self.sessions.get(sid)

                if session is None:
                    break

                if key in session.done:
                    session.done[key].clear()

                self._enqueue(
                    sid,
                    fname,
                    name,
                )

                # Attende la specifica esecuzione.
                if key in session.done:

                    await session.done[key].wait()

        except asyncio.CancelledError:
            pass

    # =========================================================================
    # REACTIVE API
    # =========================================================================

    def get_file_context(
        self,
        sid: str,
        fname: str,
    ) -> Dict[str, Any]:

        session = self.sessions.get(sid)

        if (
            session is None
            or fname not in self.nodes
        ):
            return {}

        result = {}

        for node_name, node in self.nodes[
            fname
        ].items():

            if not node.path:
                continue

            value = _get(
                session.ctx,
                node.path,
            )

            if value is not None:
                result[node.path] = value

        return result

    def update_state(
        self,
        sid: str,
        fname: str,
        path: str,
        value: Any,
    ) -> None:

        session = self.sessions.get(sid)

        if session is None:
            return

        if fname not in self.nodes:
            return

        _set(
            session.ctx,
            path,
            value,
        )

    def emit(
        self,
        sid: str,
        fname: str,
        name: str,
        value: Any = None,
    ) -> None:

        session = self.sessions.get(sid)

        if session is None:
            return

        if fname not in self.nodes:
            return

        if name not in self.nodes[fname]:

            print(
                f"[emit] Nodo '{name}' "
                f"non trovato in '{fname}' — ignorato"
            )

            return

        if value is not None:

            _set(
                session.ctx,
                name,
                value,
            )

        self._prepare_event(
            sid,
            fname,
            name,
        )

        self._enqueue(
            sid,
            fname,
            name,
        )

    async def wait_node(
        self,
        sid: str,
        fname: str,
        name: str,
    ) -> None:

        session = self.sessions.get(sid)

        if session is None:
            raise ValueError(
                f"Sessione '{sid}' non trovata."
            )

        key = _key(
            fname,
            name,
        )

        if key not in session.done:
            session.done[key] = asyncio.Event()

        await session.done[key].wait()

    # =========================================================================
    # INTERNAL QUEUE
    # =========================================================================

    def _enqueue(
        self,
        sid: str,
        fname: str,
        name: str,
    ) -> None:

        if sid in self.cancelled_sessions:
            return

        if sid not in self.sessions:
            return

        self.queue.put_nowait(
            (
                sid,
                fname,
                name,
            )
        )

    def _prepare_event(
        self,
        sid: str,
        fname: str,
        name: str,
    ) -> None:

        session = self.sessions.get(sid)

        if session is None:
            return

        key = _key(
            fname,
            name,
        )

        event = session.done.get(key)

        if event is None:

            session.done[key] = asyncio.Event()

        elif event.is_set():

            event.clear()

    def _set_done(
        self,
        sid: str,
        fname: str,
        name: str,
    ) -> None:

        session = self.sessions.get(sid)

        if session is None:
            return

        key = _key(
            fname,
            name,
        )

        event = session.done.get(key)

        if event is None:

            event = asyncio.Event()
            session.done[key] = event

        event.set()

    def _retry_node(
        self,
        sid: str,
        fname: str,
        name: str,
        delay: float = 0.5,
    ) -> None:

        async def retry():

            await asyncio.sleep(delay)

            if sid not in self.sessions:
                return

            if sid in self.cancelled_sessions:
                return

            self._enqueue(
                sid,
                fname,
                name,
            )

        asyncio.create_task(
            retry(),
            name=(
                f"dag-dependency-retry-"
                f"{fname}::{name}"
            ),
        )

    # =========================================================================
    # AUTO START
    # =========================================================================

    def _auto_starts(
        self,
        fname: str,
        name: str,
    ) -> bool:

        node = self.nodes[
            fname
        ][name]

        # Nodo non-root:
        # verrà raggiunto dal dispatch del parent.
        if self.graphs[
            fname
        ].in_degree(name) > 0:

            return True

        return bool(
            node.entry
            or node.trigger
            or node.schedule
        )