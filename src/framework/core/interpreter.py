"""Interprete DSL: facade sottile sopra programma, scope e runner.

Tre responsabilità, niente di più:

* ``load`` — testo DSL → programma compilato (dato puro);
* ``open_session`` — apre o riprende una sessione utente;
* ``evaluate`` — valuta un'espressione o riprende un ``Deferred``.
"""

from __future__ import annotations

import copy
import inspect
import uuid
from typing import Any

import framework.core.flow as flow

from .data import Registry
from .evaluation import Evaluator
from .library import BUILTINS, flatten_records
from .model import Call, Deferred, ExecutionSpec, Literal, Ref
from .program import DSLSourceError, Program, ProgramLoader
from .runner import DagRunner
from .scope import Scope
from .session import SessionData, pure_mapping, pure_value

__all__ = [
    "DSLSourceError",
    "Interpreter",
    "Program",
    "SessionHandle",
    "flatten_records",
]

_EXPRESSION_TYPES = (Call, Deferred, ExecutionSpec, Literal, Ref)
_PAYLOAD_NOT_GIVEN = object()


class SessionHandle:
    """Handle runtime di una sessione utente: esegue DAG ed emette eventi."""

    def __init__(
        self,
        runner: DagRunner,
        sid: str | None = None,
        env: dict | None = None,
        context_preparer=None,
        session_data: SessionData | None = None,
        session_data_store: dict[str, SessionData] | None = None,
        executions: dict[str, Any] | None = None,
        context: Scope | None = None,
        registry: Registry | None = None,
    ):
        self.runner = runner
        self.env = dict(env or {})
        self.registry = registry or runner.registry
        self._context_preparer = context_preparer
        self._closed = False
        self.sid = sid or (session_data["id"] if session_data else uuid.uuid4().hex)
        if session_data_store is None:
            self._session_data_store = {
                self.sid: session_data or SessionData({
                    "id": self.sid,
                    "context": pure_mapping(self.env),
                    "authentication": {},
                    "results": {},
                })
            }
        else:
            self._session_data_store = session_data_store
            if self.sid not in self._session_data_store:
                self._session_data_store[self.sid] = session_data
        self._executions = executions if executions is not None else {}
        self._context = context or Scope(pure_value(self.session_data["context"]))

    @property
    def session_data(self) -> SessionData:
        return self._session_data_store[self.sid]

    def replace_session_data(self, session_data: SessionData | dict[str, Any]):
        """Pubblica uno snapshot nuovo e aggiorna i binding runtime esistenti."""
        snapshot = (
            session_data
            if isinstance(session_data, SessionData)
            else SessionData.from_dict(session_data)
        )
        if snapshot["id"] != self.sid:
            raise ValueError("L'id dello snapshot non corrisponde alla sessione aperta")
        self._session_data_store[self.sid] = snapshot
        self._context.data.clear()
        self._context.data.update(pure_value(snapshot["context"]))
        for execution in self._executions.values():
            execution.context.set("session", snapshot)
        return snapshot

    def publish_result(self, dag_name: str, node_name: str, value: Any):
        return self.replace_session_data(
            self.session_data.publish_result(dag_name, node_name, value)
        )

    def clear_result(self, dag_name: str, node_name: str):
        return self.replace_session_data(
            self.session_data.clear_result(dag_name, node_name)
        )

    def execution(self, dag_name: str):
        return self._executions.get(dag_name)

    @property
    def context(self) -> Scope:
        return self._context

    @property
    def results(self) -> dict[str, dict[str, Any]]:
        """Vista immutabile dei risultati pubblicati dai DAG."""
        return self.session_data["results"]

    async def run(self, dag_name: str, env: dict | None = None):
        """Esegue un DAG e restituisce il Context DSL come risultato puro."""
        if self._closed:
            raise RuntimeError("La sessione è stata chiusa")
        if dag_name not in self.runner.dags:
            raise KeyError(f"DAG non registrato: {dag_name}")

        self.env.update(env or {})
        bindings = pure_mapping(self.env)
        bindings["session"] = self.session_data
        self.registry.register_dict(self.env)

        session = self.execution(dag_name)
        created = session is None
        if created:
            session = await self.runner.create_session(
                dag_name,
                initial_context=bindings,
                context=Scope(parent=self.context),
                runtime_session=self,
                resolve_context=False,
            )
            self._executions[dag_name] = session

        setattr(session, "registry", self.registry)
        if created:
            if self._context_preparer:
                await self._context_preparer(dag_name, session, bindings)
        else:
            for key, value in bindings.items():
                session.context.set(key, value)

        await self.runner.run(dag_name, session=session)

        if session.errors:
            return flow.error({name: str(error) for name, error in session.errors.items()})
        return flow.success(self._visible_context(session))

    def _visible_context(self, session) -> dict[str, Any]:
        visible = {}
        for key, value in session.context.data.items():
            if key.startswith("_"):
                continue
            if flow.is_result(value) and flow.check(value):
                value = flow.output(value)
            visible[key] = value
        return pure_mapping(visible)

    async def emit(
        self,
        target: str,
        node_or_payload: Any = None,
        payload: Any = _PAYLOAD_NOT_GIVEN,
    ):
        """Emette un evento su un nodo, opzionalmente qualificato dal controller."""
        if self._closed:
            raise RuntimeError("La sessione è stata chiusa")

        if payload is not _PAYLOAD_NOT_GIVEN:
            node, event_payload = node_or_payload, payload
            session = self.execution(target)
        else:
            node, event_payload = target, node_or_payload
            session = next(
                (
                    execution
                    for execution in self._executions.values()
                    if node in execution.states
                ),
                None,
            )

        if session is None:
            raise RuntimeError("L'esecuzione DAG non è disponibile")
        return await self.runner.emit(session, node, event_payload)

    async def dispatch_controller_event(
        self,
        controller: str,
        node: str,
        payload: Any = None,
    ):
        """Avvia il controller se necessario e consegna l'evento al suo DAG."""
        if self.execution(controller) is None:
            started = await self.run(controller)
            if flow.is_result(started) and not flow.check(started):
                return started
        return await self.emit(controller, node, payload=payload)

    def report(self, dag_name: str):
        """Esito puro dell'esecuzione di un DAG della sessione."""
        session = self.execution(dag_name)
        return session.report() if session is not None else None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        if self._closed:
            return
        for session in tuple(self._executions.values()):
            await self.runner.close_session(session)
        self._executions.clear()
        self._closed = True


class Interpreter:

    def __init__(self, schemes=None, registry=None):
        self.schemes = schemes
        self.registry = registry or Registry()
        self.registry.register_dict(BUILTINS)
        self.programs = ProgramLoader()
        self.evaluator = Evaluator(self.registry)
        self.runner = DagRunner(registry=self.registry, evaluator=self.evaluator)
        self.session_envs: dict[str, dict] = {}
        self.session_data: dict[str, SessionData] = {}
        self.session_executions: dict[str, dict[str, Any]] = {}
        self.session_contexts: dict[str, Scope] = {}
        self._started = False

    # ── programmi ────────────────────────────────────────────────────────────

    def parse_only(self, source: str, name: str = "<string>"):
        """Parsa il DSL senza compilare né registrare il programma."""
        return self.programs.parse(source, name)

    def load(self, name: str, source: str) -> Program:
        """Compila e registra un programma DSL; ricompila solo se il testo cambia."""
        program = self.programs.load(name, source)
        self.runner.register(program.definition)
        return program

    async def load_file(self, name: str, code: str):
        return flow.success(self.load(name, code).definition)

    # ── valutazione ──────────────────────────────────────────────────────────

    async def evaluate(
        self,
        expression: Any,
        bindings: dict | None = None,
        *,
        session=None,
    ) -> Any:
        """Valuta un'espressione o riprende un ``Deferred`` con i binding dati."""
        scope = Scope(dict(bindings or {}))
        if isinstance(expression, Deferred):
            return await self.evaluator.resume(expression, scope, session=session)
        return await self.evaluator.evaluate(expression, scope, session=session)

    async def evaluate_named(
        self,
        program_name: str,
        name: str,
        bindings: dict | None = None,
        *,
        session=None,
    ):
        """Rivaluta una dichiarazione DSL per nome usando binding JSON."""
        dag = self.runner.dags.get(program_name)
        if dag is None:
            return flow.error(f"Programma DSL non registrato: {program_name}")

        expression = dag.definition.context
        for part in name.split("."):
            if not isinstance(expression, dict) or part not in expression:
                return flow.error(
                    f"Dichiarazione DSL non trovata: {program_name}.{name}"
                )
            expression = expression[part]

        scope_data = copy.deepcopy(dag.definition.context)
        scope_data.update(pure_mapping(bindings))
        try:
            result = await self.evaluator.evaluate(
                expression,
                Scope(scope_data),
                session=session,
            )
        except Exception as exc:
            return flow.error(str(exc))
        return self._pure_result(result)

    @staticmethod
    def _pure_result(value: Any):
        if flow.is_result(value):
            if not flow.check(value):
                return flow.error(str(flow.output(value)))
            value = flow.output(value)
        try:
            return flow.success(pure_value(value))
        except TypeError as exc:
            return flow.error(str(exc))

    async def call(self, fn, args=(), kwargs=None, *, session=None):
        """Invoca una callable o valuta un'espressione, normalizzando in Result."""
        kwargs = dict(kwargs or {})

        if hasattr(fn, "tree"):
            fn = fn.tree

        if isinstance(fn, str):
            registry = getattr(session, "registry", None) or self.registry
            if callable(registry.lookup(fn)):
                result = await self.evaluate(
                    Call(fn, tuple(args), kwargs),
                    session=session,
                )
                return self._pure_result(result)
            else:
                return flow.success(fn)

        if isinstance(fn, _EXPRESSION_TYPES) or (
            hasattr(fn, "data") and hasattr(fn, "children")
        ):
            bindings = dict(kwargs)
            for alias in ("received", "expected"):
                if alias in kwargs:
                    bindings[f"@{alias}"] = kwargs[alias]
            result = await self.evaluate(fn, bindings, session=session)
            return result if flow.is_result(result) else flow.success(result)

        if callable(fn):
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result if flow.is_result(result) else flow.success(result)

        return flow.success(fn)

    # ── contesto DSL ─────────────────────────────────────────────────────────

    def _validate_context(self, dag_name: str, session) -> None:
        """Applica i custom type quando il contesto DSL è pronto."""
        from framework.service import scheme

        metadata = getattr(self.runner.dags[dag_name].definition, "metadata", {})
        custom_types = set(metadata.get("custom_types", ()))
        errors = {}

        for path, type_name in metadata.get("typed_declarations", []):
            if type_name not in custom_types:
                continue
            schema = session.context.get(type_name)
            if schema is None:
                continue
            try:
                result = scheme.normalize(session.context.get(path), schema)
            except (TypeError, ValueError) as exc:
                errors[path] = str(exc)
                continue
            if not result.is_success:
                errors[path] = flow.output(result)

        if errors:
            raise ValueError(f"Contesto non valido secondo gli schemi dichiarati: {errors}")

    async def _prepare_context(self, dag_name: str, session, initial_context: dict) -> None:
        """Valuta il contesto dichiarato dal DAG prima di avviarlo."""
        declared = dict(getattr(self.runner.dags[dag_name].definition, "context", {}))
        declared.update(initial_context or {})

        for key, expression in declared.items():
            value = await self.evaluator.evaluate(
                expression, session.context, session=session
            )
            session.context.set(key, value)

        self._validate_context(dag_name, session)

    # ── sessioni ─────────────────────────────────────────────────────────────

    def session_create(
        self,
        sid: str = None,
        env: dict = None,
        authentication: dict | None = None,
        state: dict | SessionData | None = None,
    ):
        """Crea una sessione registrandone l'ambiente runtime."""
        sid = sid or uuid.uuid4().hex
        if env is not None:
            self.session_envs[sid] = dict(env)
        return self.open_session(
            env=env,
            sid=sid,
            authentication=authentication,
            state=state,
        )

    def open_session(
        self,
        env: dict = None,
        sid: str = None,
        authentication: dict | None = None,
        state: dict | SessionData | None = None,
    ):
        """Apre una sessione, riprendendo lo stato puro prodotto da `to_dict()`."""
        restored = None
        if state is not None:
            restored = (
                state
                if isinstance(state, SessionData)
                else SessionData.from_dict(state)
            )
            sid = sid or restored["id"]
        sid = sid or uuid.uuid4().hex
        merged_env = dict(self.session_envs.get(sid, {}))
        if env is not None:
            merged_env.update(env)
            self.session_envs[sid] = merged_env

        current = self.session_data.get(sid)
        payload = current.to_dict() if current is not None else {
            "id": sid,
            "context": {},
            "authentication": {},
            "results": {},
        }
        if restored is not None:
            restored_data = restored.to_dict()
            payload["context"].update(restored_data["context"])
            payload["authentication"].update(restored_data["authentication"])
            for dag, nodes in restored_data["results"].items():
                payload["results"].setdefault(dag, {}).update(nodes)
        payload["context"].update(pure_mapping(merged_env))
        payload["authentication"].update(pure_mapping(authentication or {}))
        snapshot = SessionData(payload)
        self.session_data[sid] = snapshot
        context = self.session_contexts.get(sid)
        if context is None:
            context = Scope(pure_value(snapshot["context"]))
            self.session_contexts[sid] = context
        else:
            context.data.clear()
            context.data.update(pure_value(snapshot["context"]))

        # Registry figlio: l'ambiente di una sessione non contamina le altre.
        registry = self.registry.child()
        registry.register_dict(merged_env)

        return SessionHandle(
            self.runner,
            sid=sid,
            env=merged_env,
            context_preparer=self._prepare_context,
            session_data=snapshot,
            session_data_store=self.session_data,
            executions=self.session_executions.setdefault(sid, {}),
            context=context,
            registry=registry,
        )

    # ── ciclo di vita ────────────────────────────────────────────────────────

    async def start(self):
        self._started = True
        return self

    async def stop(self):
        for executions in tuple(self.session_executions.values()):
            for session in tuple(executions.values()):
                await self.runner.close_session(session)
            executions.clear()
        self.session_data.clear()
        self.session_executions.clear()
        self.session_contexts.clear()
        for session in tuple(self.runner.sessions.values()):
            await self.runner.close_session(session)
        self.session_envs.clear()
        self._started = False

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()