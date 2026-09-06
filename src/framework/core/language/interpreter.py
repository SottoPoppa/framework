import uuid
import inspect
from typing import Dict, Any
import framework.core.flow as flow
from ..dag.runner import DagRunner
from ..dag.model import Literal, Ref, Call
from ..dag.context import ExecutionContext
from .parser import Parser
from .compiler import Compiler

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
    def __init__(self, runner: DagRunner, sid: str = None, env: dict = None):
        self.runner = runner
        self.sid = sid or uuid.uuid4().hex
        self.env = env or {}

    async def run(self, dag_name: str, env: dict = None):
        merged_env = {**self.env, **(env or {})}
        session = self.runner.sessions.get(self.sid)
        if not session:
            session = self.runner.create_session(dag_name, initial_context=merged_env)
            self.sid = session.id
        else:
            for k, v in merged_env.items():
                session.context.set(k, v)
                if callable(v):
                    self.runner.registry.register(k, v)

        for k, v in merged_env.items():
            if callable(v):
                self.runner.registry.register(k, v)

        changed = True
        while changed:
            changed = False
            for k in list(session.context._data.keys()):
                v = session.context._data[k]
                try:
                    eval_v = await self.runner.executor._eval(v, session.context)
                    if eval_v != v:
                        session.context.set(k, eval_v)
                        changed = True
                except Exception:
                    pass

        await self.runner.run(dag_name, session=session)

        raw_snapshot = session.context.snapshot()
        unwrapped = await self.runner.executor._eval(raw_snapshot, session.context)
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
        if isinstance(fn, DslAssertion):
            fn = fn.tree
        if hasattr(fn, 'data') and hasattr(fn, 'children'):
            ctx_dict = dict(kwargs)
            if 'received' in kwargs:
                ctx_dict['@received'] = kwargs['received']
                ctx_dict['received'] = kwargs['received']
            if 'expected' in kwargs:
                ctx_dict['@expected'] = kwargs['expected']
                ctx_dict['expected'] = kwargs['expected']
            res = await self.runner.executor._eval(fn, ExecutionContext(ctx_dict))
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
        for k, v in merged_env.items():
            if callable(v):
                self.runner.registry.register(k, v)
        return SessionHandle(self.runner, sid=sid, env=merged_env)

    async def start(self):
        pass

    async def stop(self):
        pass
