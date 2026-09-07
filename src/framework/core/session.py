import asyncio
from enum import Enum
class NodeState(str, Enum):
    PENDING='pending'; RUNNING='running'; SUCCESS='success'; FAILED='failed'; SKIPPED='skipped'
class Session:
    def __init__(self, dag_name, session_id, context):
        self.dag_name=dag_name; self.id=session_id; self.context=context; self.results={}; self.states={}; self.errors={}; self._events={}
    def event_for(self,node): return self._events.setdefault(node, asyncio.Event())
    async def wait(self,node):
        await self.event_for(node).wait()
        if node in self.errors: raise self.errors[node]
        return self.results.get(node)
    def mark(self,node,state):
        self.states[node]=state
        if state in (NodeState.SUCCESS,NodeState.FAILED,NodeState.SKIPPED): self.event_for(node).set()
