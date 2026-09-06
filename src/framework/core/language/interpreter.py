import uuid
from typing import Dict, Any
import framework.core.flow as flow
from ..dag.runner import DagRunner
from .parser import Parser
from .compiler import Compiler

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

    async def load_file(self, name: str, code: str):
        ast_prog = self.parser.parse(code)
        dag_def = self.compiler.compile(ast_prog, name=name)
        self.runner.register(dag_def)
        return flow.success(dag_def)

    def open_session(self, env: dict = None, sid: str = None):
        sid = sid or uuid.uuid4().hex
        return SessionHandle(self.runner, sid=sid, env=env)

    async def start(self):
        pass

    async def stop(self):
        pass
