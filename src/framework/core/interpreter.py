import inspect
from typing import Any, Dict
import uuid
from collections.abc import Mapping
from lark.exceptions import UnexpectedInput

import framework.core.flow as flow

from .context import ExecutionContext
from .execution import Executor
from .model import Call, Literal, Ref
from .runner import DagRunner
from .compiler import Compiler
from .parser import Parser
from .data import Registry
from .session import UserSession
from framework.service.introspection import Reflection


class DSLSourceError(ValueError):
    """Errore DSL con posizione e fase utili ai client di tooling."""

    def __init__(self, source: str, phase: str, message: str, error=None):
        self.source = source
        self.phase = phase
        self.line = getattr(error, "line", None)
        self.column = getattr(error, "column", None)
        location = ""
        if self.line is not None:
            location = f":{self.line}"
            if self.column is not None:
                location += f":{self.column}"
        super().__init__(f"Errore {phase} in '{source}'{location}: {message}")

def map_records(records: Any, builder: Any, *args, **kwargs) -> list:
    if not isinstance(records, (list, tuple)) or not callable(builder):
        return []
    return [builder(record, *args, **kwargs)
            for record in records if isinstance(record, Mapping)]


def variants(tags: Any) -> list:
    if not isinstance(tags, Mapping):
        return []
    records = []
    for key, values in tags.items():
        values = list(values.keys()) if isinstance(values, Mapping) else values
        if not isinstance(values, (list, tuple, set)):
            continue
        records.extend({"key": key, "value": value} for value in values)
    return records


def tag_variants(tags: Any) -> list:
    return [
        {
            "inputs": (
                None,
                record["key"],
                {} if record["value"] == record["key"] else {"type": record["value"]},
                ["fixture"],
            ),
            "note": f"Composizione {record['key']}:{record['value']}",
        }
        for record in variants(tags)
    ]


def prefix_match(field: str, prefix: str):
    return lambda record: (
        (
            str(record).startswith(str(prefix))
            if isinstance(record, str) and field == "relative_path"
            else isinstance(record, Mapping)
            and str(record.get(field, "")).startswith(str(prefix))
        )
    )


def tuple_filter_tuple(records: Any, predicate: Any) -> tuple:
    if not isinstance(records, (list, tuple)) or not callable(predicate):
        return ()
    return tuple(record for record in records if predicate(record))


DSL_FUNCTIONS: Dict[str, Any] = {
    "map_records": map_records,
    "tag_variants": tag_variants,
    "keys": lambda value: list(value.keys()) if isinstance(value, Mapping) else [],
    "values": lambda value: list(value.values()) if isinstance(value, Mapping) else [],
    "union": lambda left, right: {**left, **right},
    "print": lambda *values: (print(*values), values)[1],
    "pass": lambda *values: values,
    "int": int,
    "str": str,
    "bool": bool,
    "result": lambda value=None: value,
    "file_dependencies": Reflection.file_dependencies,
    "prefix_match": prefix_match,
    "tuple_filter_tuple": tuple_filter_tuple,
}


def flatten_records(records):
    if isinstance(records, dict):
        return [records]
    if isinstance(records, (list, tuple)):
        res = []
        for r in records:
            res.extend(flatten_records(r))
        return res
    return [records] if records else []


class SessionHandle:

    def __init__(
        self,
        runner: DagRunner,
        sid: str = None,
        env: dict = None,
        context_preparer=None,
        user_session: UserSession | None = None,
    ):
        self.runner = runner
        self.sid = sid or uuid.uuid4().hex
        self.env = dict(env or {})
        self._context_preparer = context_preparer
        self._closed = False
        self.user_session = user_session or UserSession(
            self.sid,
            ExecutionContext(self.env),
        )
        self.sid = self.user_session.id

    @property
    def context(self):
        return self.user_session.context

    def _register_functions(self, env: dict):
        """Registra automaticamente tutte le callable nel FunctionRegistry."""
        if self.runner.registry:
            for k, v in env.items():
                if callable(v):
                    self.runner.registry.register(k, v)

    async def run(self, dag_name: str, env: dict = None):
        if self._closed:
            raise RuntimeError("La sessione è stata chiusa")
        if dag_name not in self.runner.dags:
            raise KeyError(f"DAG non registrato: {dag_name}")
        merged_env = {**self.env, **(env or {})}
        self.env.update(env or {})
        self._register_functions(merged_env)

        session = self.user_session.executions.get(dag_name)

        if session is None:
            # Crea la sessione ed esegue la risoluzione asincrona del contesto
            session = await self.runner.create_session(
                dag_name,
                initial_context=merged_env,
                context=self.user_session.context,
                resolve_context=False,
            )
            self.user_session.executions[dag_name] = session
            if self._context_preparer:
                await self._context_preparer(dag_name, session, merged_env)
        else:
            # Aggiorna il contesto esistente con i nuovi valori dell'env
            for k, v in merged_env.items():
                session.context.set(k, v)

        # Esegue l'orchestrazione dei Task del DAG
        await self.runner.run(dag_name, session=session)

        if session.errors:
            return flow.error(dict(session.errors))
        return flow.success(dict(session.context.data))

    async def emit(
        self,
        node_or_controller: str,
        payload_or_node: Any = None,
        payload: Any = None,
    ):
        if self._closed:
            raise RuntimeError("La sessione è stata chiusa")
        if payload is not None:
            node = payload_or_node
            event_payload = payload
        else:
            node = node_or_controller
            event_payload = payload_or_node
        if payload is not None:
            session = self.user_session.executions.get(node_or_controller)
        else:
            session = next(
                (
                    execution
                    for execution in self.user_session.executions.values()
                    if node in execution.states
                ),
                None,
            )
        if session is None:
            raise RuntimeError("L'esecuzione DAG non è disponibile")
        return await self.runner.emit(session, node, event_payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        if self._closed:
            return
        for session in tuple(self.user_session.executions.values()):
            self.runner.close_session(session)
        self.user_session.executions.clear()
        self._closed = True


class Interpreter:

    def __init__(self, schemes=None, registry=None):
        self.parser = Parser()
        self.compiler = Compiler()
        self.registry = registry or Registry()
        self.registry.register_dict(DSL_FUNCTIONS)
        self._runner = DagRunner(
            registry=self.registry,
            executor=Executor(self.registry),
        )
        self.runner = self._runner
        self.session_envs = {}
        self.user_sessions: dict[str, UserSession] = {}
        self._started = False

    async def call(self, fn, args=(), kwargs=None):
        kwargs = kwargs or {}

        # Gestione asserzioni/AST custom
        if hasattr(fn, "tree"):
            fn = fn.tree

        if isinstance(fn, (Call, Literal, Ref)) or (
            hasattr(fn, "data") and hasattr(fn, "children")
        ):
            ctx_dict = dict(kwargs)
            if "received" in kwargs:
                ctx_dict["@received"] = kwargs["received"]
                ctx_dict["received"] = kwargs["received"]
            if "expected" in kwargs:
                ctx_dict["@expected"] = kwargs["expected"]
                ctx_dict["expected"] = kwargs["expected"]

            # Usa il metodo pubblico execute() anziché _eval()
            res = await self.runner.executor.execute(
                fn, ExecutionContext(ctx_dict)
            )
            return res if flow.is_result(res) else flow.success(res)

        if callable(fn):
            res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            return res if flow.is_result(res) else flow.success(res)

        return flow.success(fn)

    def parse_only(self, source: str, name: str = "<string>"):
        """Parsa il DSL senza registrare o eseguire il programma."""
        try:
            return self.parser.parse(source)
        except UnexpectedInput as error:
            raise DSLSourceError(
                name,
                "parsing DSL",
                str(error).splitlines()[0],
                error,
            ) from error

    async def load_file(self, name: str, code: str):
        ast_prog = self.parse_only(code, name)
        try:
            dag_def = self.compiler.compile(ast_prog, name=name)
        except Exception as error:
            if isinstance(error, DSLSourceError):
                raise
            raise DSLSourceError(name, "compilazione DSL", str(error)) from error
        self.runner.register(dag_def)
        return flow.success(dag_def)

    def _validate_context(self, dag_name: str, session) -> None:
        """Applica i custom type quando il contesto DSL e' pronto."""
        from framework.core import scheme

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
        """Valuta il contesto DSL in ordine, prima di avviare il DAG."""
        dag = self.runner.dags[dag_name]
        context = session.context
        values = dict(getattr(dag.definition, "context", {}))
        values.update(initial_context or {})

        for key, expression in values.items():
            value = await self.runner.executor.execute(expression, context)
            context.set(key, value)

        self._validate_context(dag_name, session)

    def session_create(
        self,
        sid: str = None,
        env: dict = None,
        authentication: dict | None = None,
    ):
        sid = sid or uuid.uuid4().hex
        if env is not None:
            self.session_envs[sid] = dict(env)
            if self.runner.registry:
                for k, v in self.session_envs[sid].items():
                    if callable(v):
                        self.runner.registry.register(k, v)
        return self.open_session(
            env=env,
            sid=sid,
            authentication=authentication,
        )

    def open_session(
        self,
        env: dict = None,
        sid: str = None,
        authentication: dict | None = None,
    ):
        sid = sid or uuid.uuid4().hex
        merged_env = dict(self.session_envs.get(sid, {}))
        if env is not None:
            merged_env.update(env)
            self.session_envs[sid] = merged_env

        if self.runner.registry:
            for k, v in merged_env.items():
                if callable(v):
                    self.runner.registry.register(k, v)

        user_session = self.user_sessions.get(sid)
        if user_session is None:
            user_session = UserSession(
                sid,
                ExecutionContext(merged_env),
                authentication=authentication,
            )
            self.user_sessions[sid] = user_session
        else:
            for key, value in merged_env.items():
                user_session.context.set(key, value)
            if authentication:
                user_session.authentication.update(authentication)

        return SessionHandle(
            self.runner,
            sid=sid,
            env=merged_env,
            context_preparer=self._prepare_context,
            user_session=user_session,
        )

    async def start(self):
        self._started = True
        return self

    async def stop(self):
        for user_session in tuple(self.user_sessions.values()):
            for session in tuple(user_session.executions.values()):
                self.runner.close_session(session)
            user_session.executions.clear()
        self.user_sessions.clear()
        for session in tuple(self.runner.sessions.values()):
            self.runner.close_session(session)
        self.session_envs.clear()
        self._started = False

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()