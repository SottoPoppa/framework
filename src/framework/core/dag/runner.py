import asyncio, inspect, uuid
from .context import ExecutionContext
from .execution import Executor
from .graph import Dag
from .model import DagDefinition
from .registry import FunctionRegistry
from .session import Session, NodeState
from .errors import DependencyFailed, NodeNotFound
class DagRunner:
    def __init__(self, registry=None, *, concurrency=32):
        self.registry=registry or FunctionRegistry(); self.executor=Executor(self.registry); self.dags={}; self.sessions={}; self._sem=asyncio.Semaphore(concurrency)
    def register(self, dag):
        dag = Dag(dag) if isinstance(dag, DagDefinition) else dag; self.dags[dag.name]=dag; return dag
    def create_session(self, dag_name, *, initial_context=None):
        dag=self.dags[dag_name]; sid=uuid.uuid4().hex; ctx=dict(dag.definition.context); ctx.update(initial_context or {}); s=Session(dag.name,sid,ExecutionContext(ctx)); self.sessions[sid]=s
        for n in dag.nodes: s.mark(n,NodeState.PENDING)
        return s
    async def run(self, dag_name, *, session=None):
        dag=self.dags[dag_name]; session=session or self.create_session(dag_name)
        await asyncio.gather(*(self._run_node(dag,session,n) for n in dag.entries()))
        return session
    async def _run_node(self,dag,s,n):
        node=dag.get(n)
        if s.states[n] in (NodeState.SUCCESS,NodeState.FAILED,NodeState.SKIPPED): return
        for dep in node.deps:
            await s.wait(dep)
            if s.states[dep] != NodeState.SUCCESS:
                s.errors[n]=DependencyFailed(f'{n} blocked by {dep}'); s.mark(n,NodeState.SKIPPED); return
        async with self._sem:
            s.mark(n,NodeState.RUNNING); attempt=0
            while True:
                try:
                    value=self.executor.execute(node.action,s.context)
                    if inspect.isawaitable(value): value=await asyncio.wait_for(value,node.timeout) if node.timeout else await value
                    s.results[n]=value; s.context.set(n,value); s.mark(n,NodeState.SUCCESS)
                    await asyncio.gather(*(self._run_node(dag,s,c) for c in dag.successors[n])); return
                except Exception as exc:
                    if attempt >= node.retries: s.errors[n]=exc; s.mark(n,NodeState.FAILED); return
                    attempt+=1
                    if node.retry_delay: await asyncio.sleep(node.retry_delay)
    async def wait(self,session_id,node): return await self.sessions[session_id].wait(node)
    async def emit(self,session_id,node,payload=None):
        s=self.sessions[session_id]; dag=self.dags[s.dag_name]
        if node not in dag.nodes: raise NodeNotFound(node)
        s.context.set(f'events.{node}',payload); return await self._run_node(dag,s,node)
    def close_session(self,session_id): self.sessions.pop(session_id,None)
