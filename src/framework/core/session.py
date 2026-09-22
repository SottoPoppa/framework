import asyncio
import json
from enum import Enum
from typing import Any


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"Valore non serializzabile nella sessione: {type(value).__name__}")


def public_value(value: Any) -> Any:
    """Converte valori DSL in payload pubblicabili senza riferimenti runtime."""
    if isinstance(value, SessionView):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_value(item) for item in value]
    return _json_value(value)

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
        safe_value = _json_value(value)
        self.results.setdefault(dag_name, {})[node_name] = safe_value
        return safe_value

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

    def to_dict(self) -> dict[str, Any]:
        """Restituisce la proiezione persistibile, senza esecuzioni DAG."""
        return _json_value({
            "id": self.id,
            "context": self.context.data,
            "results": self.results,
        })

    def to_json(self) -> str:
        """Serializza la proiezione persistibile in JSON deterministico."""
        return json.dumps(self.to_dict(), sort_keys=True)


class SessionView:
    """Vista JSON-safe della UserSession esposta alle espressioni DSL."""

    def __init__(self, data: dict[str, Any]):
        self._data = _json_value(data)

    def get(self, path: str, default: Any = None) -> Any:
        current: Any = self._data
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return default
        return current

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None and key not in self.to_dict():
            raise KeyError(key)
        return value

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self._data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def __getattr__(self, name: str) -> Any:
        value = self.get(name)
        if value is None and name not in self.to_dict():
            raise AttributeError(name)
        return value
