import asyncio
from enum import Enum
from typing import Any

class NodeState(str, Enum):
    PENDING='pending'; RUNNING='running'; SUCCESS='success'; FAILED='failed'; SKIPPED='skipped'
class Session:
    def __init__(self, dag_name, session_id, context, user_session=None):
        self.dag_name=dag_name; self.id=session_id; self.context=context; self.user_session=user_session; self.results={}; self.states={}; self.errors={}; self._events={}
    def event_for(self,node): return self._events.setdefault(node, asyncio.Event())
    async def wait(self,node):
        await self.event_for(node).wait()
        if node in self.errors: raise self.errors[node]
        return self.results.get(node)
    def mark(self,node,state):
        self.states[node]=state
        if state == NodeState.PENDING:
            self._events[node] = asyncio.Event()
        if state in (NodeState.SUCCESS,NodeState.FAILED,NodeState.SKIPPED): self.event_for(node).set()


class UserSession:
    """Stato condiviso dell'utente e sue esecuzioni DAG."""

    def __init__(self, session_id, context, authentication=None):
        self.id = session_id
        self.context = context
        self.authentication = dict(authentication or {})
        self.executions: dict[str, Session] = {}
        self.results: dict[str, dict[str, Any]] = {}

    def publish_result(self, dag_name: str, node_name: str, value: Any) -> Any:
        """Pubblica l'ultimo payload riuscito di un nodo nella sessione utente."""
        self.results.setdefault(dag_name, {})[node_name] = value
        return value

    def get_result(self, dag_name: str, node_name: str, default: Any = None) -> Any:
        """Recupera un risultato DAG senza appiattirlo nel contesto locale."""
        return self.results.get(dag_name, {}).get(node_name, default)

    def clear_result(self, dag_name: str, node_name: str) -> None:
        dag_results = self.results.get(dag_name)
        if not dag_results:
            return
        dag_results.pop(node_name, None)
        if not dag_results:
            self.results.pop(dag_name, None)
