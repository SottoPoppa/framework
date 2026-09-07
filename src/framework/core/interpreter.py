import inspect
from typing import Any, Dict
import uuid

import framework.core.flow as flow

from .context import ExecutionContext
from .model import Call, Literal, Ref
from .runner import DagRunner
from .compiler import Compiler
from .parser import Parser

DSL_FUNCTIONS: Dict[str, Any] = {}


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
        self, runner: DagRunner, sid: str = None, env: dict = None
    ):
        self.runner = runner
        self.sid = sid or uuid.uuid4().hex
        self.env = env or {}

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
                dag_name, initial_context=merged_env
            )
            self.sid = session.id
        else:
            # Aggiorna il contesto esistente con i nuovi valori dell'env
            for k, v in merged_env.items():
                session.context.set(k, v)

        # Esegue l'orchestrazione dei Task del DAG
        await self.runner.run(dag_name, session=session)

        # Estrae lo snapshot risolto e pulito del contesto finale
        unwrapped = session.context.snapshot()
        return flow.success(unwrapped)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class Interpreter:

    def __init__(self, schemes=None, registry=None):
        self.parser = Parser()
        self.compiler = Compiler()
        self._runner = DagRunner(registry=registry)
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
            return flow.success(res)

        return flow.success(fn)

    async def load_file(self, name: str, code: str):
        ast_prog = self.parser.parse(code)
        dag_def = self.compiler.compile(ast_prog, name=name)
        self.runner.register(dag_def)
        return flow.success(dag_def)

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

        return SessionHandle(self.runner, sid=sid, env=merged_env)

    async def start(self):
        pass

    async def stop(self):
        pass