import inspect
from typing import Any, Dict
import uuid
from collections.abc import Mapping

import framework.core.flow as flow

from .context import ExecutionContext
from .execution import Executor
from .model import Call, Literal, Ref
from .runner import DagRunner
from .compiler import Compiler
from .parser import Parser
from .data import Registry

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
    ):
        self.runner = runner
        self.sid = sid or uuid.uuid4().hex
        self.env = env or {}
        self._context_preparer = context_preparer

    def _register_functions(self, env: dict):
        """Registra automaticamente tutte le callable nel FunctionRegistry."""
        if self.runner.registry:
            for k, v in env.items():
                if callable(v):
                    self.runner.registry.register(k, v)

    async def run(self, dag_name: str, env: dict = None):
        merged_env = {**self.env, **(env or {})}
        self._register_functions(merged_env)

        session = self.runner.sessions.get(self.sid)

        if not session:
            # Crea la sessione ed esegue la risoluzione asincrona del contesto
            session = await self.runner.create_session(
                dag_name,
                initial_context=merged_env,
                resolve_context=False,
            )
            self.sid = session.id
            if self._context_preparer:
                await self._context_preparer(dag_name, session, merged_env)
        else:
            # Aggiorna il contesto esistente con i nuovi valori dell'env
            for k, v in merged_env.items():
                session.context.set(k, v)

        # Esegue l'orchestrazione dei Task del DAG
        await self.runner.run(dag_name, session=session)

        # Restituisce il contesto risolto e pulito.
        unwrapped = session.context.data
        return flow.success(unwrapped)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class Interpreter:

    def __init__(self, schemes=None, registry=None):
        self.parser = Parser()
        self.compiler = Compiler()
        self.registry = registry or Registry()
        self._runner = DagRunner(
            registry=self.registry,
            executor=Executor(self.registry),
        )
        self.runner = self._runner
        self.session_envs = {}

    async def call(self, fn, args=(), kwargs=None):
        kwargs = kwargs or {}

        # Gestione asserzioni/AST custom
        if hasattr(fn, "tree"):
            fn = fn.tree

        if hasattr(fn, "data") and hasattr(fn, "children"):
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
            return flow.success(res)

        if callable(fn):
            res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            return res if flow.is_result(res) else flow.success(res)

        return flow.success(fn)

    async def load_file(self, name: str, code: str):
        ast_prog = self.parser.parse(code)
        dag_def = self.compiler.compile(ast_prog, name=name)
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

    def session_create(self, sid: str = None, env: dict = None):
        sid = sid or uuid.uuid4().hex
        if env:
            self.session_envs[sid] = env
            if self.runner.registry:
                for k, v in env.items():
                    if callable(v):
                        self.runner.registry.register(k, v)
        return self.open_session(env=env, sid=sid)

    def open_session(self, env: dict = None, sid: str = None):
        sid = sid or uuid.uuid4().hex
        merged_env = dict(self.session_envs.get(sid, {}))
        if env:
            merged_env.update(env)
            self.session_envs[sid] = merged_env

        if self.runner.registry:
            for k, v in merged_env.items():
                if callable(v):
                    self.runner.registry.register(k, v)

        return SessionHandle(
            self.runner,
            sid=sid,
            env=merged_env,
            context_preparer=self._prepare_context,
        )

    async def start(self):
        pass

    async def stop(self):
        pass