"""Stato di sessione del framework.

Il modulo separa esplicitamente lo snapshot puro ``SessionData`` dalle
esecuzioni runtime ``Session``. Lo snapshot è serializzabile e validato tramite
``framework.service.scheme``; non contiene Scope, handle, task o Manager.
"""

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.service.scheme import Scheme

from . import model
from .scope import Scope


class ImpureValueError(TypeError):
    """Sollevata quando un oggetto runtime finisce in una struttura di dati puri."""


_PRIMITIVES = (str, int, float, bool)


def pure_value(value: Any) -> Any:
    """Proietta un valore nella sua forma pura, rifiutando gli oggetti runtime."""
    if value is None or isinstance(value, _PRIMITIVES):
        return value
    if isinstance(value, Enum):
        return pure_value(value.value)
    if isinstance(value, dict):
        return {str(key): pure_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [pure_value(item) for item in value]
    encoded = model.encode(value, pure_value)
    if encoded is not None:
        return encoded
    raise ImpureValueError(
        f"Valore runtime non serializzabile nella sessione: {type(value).__name__}"
    )


def revive(value: Any) -> Any:
    """Ricostruisce le espressioni sospese da una struttura pura."""
    return model.decode(value)


def is_pure(value: Any) -> bool:
    """True se il valore è interamente proiettabile in dati puri."""
    try:
        pure_value(value)
    except ImpureValueError:
        return False
    return True


def pure_mapping(mapping: Any) -> dict[str, Any]:
    """Proietta una mappa scartando le chiavi che contengono oggetti runtime."""
    if not isinstance(mapping, dict):
        return {}
    projection: dict[str, Any] = {}
    for key, value in mapping.items():
        try:
            projection[str(key)] = pure_value(value)
        except ImpureValueError:
            continue
    return projection


SESSION_DATA_SCHEME: dict[str, Any] = {
    "id": {"type": "string", "required": True, "empty": False},
    "context": {"type": "dict", "required": True},
    "authentication": {"type": "dict", "required": True},
    "results": {"type": "dict", "required": True},
}


class SessionData(Scheme):
    """Snapshot immutabile e validato dei soli dati di sessione."""

    SCHEME = SESSION_DATA_SCHEME

    def __init__(self, payload: dict[str, Any]):
        if not isinstance(payload, dict):
            raise TypeError("Lo stato della sessione deve essere una mappa")
        state = {
            "id": str(payload.get("id") or ""),
            "context": pure_value(payload.get("context") or {}),
            "authentication": pure_value(payload.get("authentication") or {}),
            "results": pure_value(payload.get("results") or {}),
        }
        super().__init__(state)

    def clear(self):
        raise TypeError("SessionData è immutabile; usa evolve()")

    def pop(self, key, default=None):
        raise TypeError("SessionData è immutabile; usa evolve()")

    def popitem(self):
        raise TypeError("SessionData è immutabile; usa evolve()")

    def setdefault(self, key, default=None):
        raise TypeError("SessionData è immutabile; usa evolve()")

    def update(self, *args, **kwargs):
        raise TypeError("SessionData è immutabile; usa evolve()")

    def __ior__(self, other):
        raise TypeError("SessionData è immutabile; usa evolve()")

    def evolve(self, **changes) -> "SessionData":
        """Restituisce un nuovo snapshot validato con i campi aggiornati."""
        return SessionData(self.to_dict() | changes)

    def get_result(self, dag_name: str, node_name: str, default=None):
        """Restituisce un risultato DAG senza esporre strutture mutabili."""
        dag_results = self["results"].get(str(dag_name), {})
        return dag_results.get(str(node_name), default)

    def publish_result(self, dag_name: str, node_name: str, value: Any):
        """Restituisce uno snapshot con un risultato DAG puro pubblicato."""
        try:
            safe_value = pure_value(value)
        except ImpureValueError:
            return self
        results = self.to_dict()["results"]
        results.setdefault(str(dag_name), {})[str(node_name)] = safe_value
        return self.evolve(results=results)

    def clear_result(self, dag_name: str, node_name: str):
        """Restituisce uno snapshot senza il risultato DAG indicato."""
        results = self.to_dict()["results"]
        dag_results = results.get(str(dag_name))
        if not dag_results:
            return self
        dag_results.pop(str(node_name), None)
        if not dag_results:
            results.pop(str(dag_name), None)
        return self.evolve(results=results)

    def to_dict(self) -> dict[str, Any]:
        """Restituisce una copia mutabile per confini di serializzazione."""
        return pure_value(dict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Any) -> "SessionData":
        return cls(payload)

    @classmethod
    def from_json(cls, payload: str) -> "SessionData":
        return cls.from_dict(json.loads(payload))

    def validate(self, schema: dict[str, Any] | None = None):
        """Valida lo snapshot con lo schema sessione o uno schema fornito."""
        from framework.service import scheme

        return scheme.normalize(self.to_dict(), schema or SESSION_DATA_SCHEME)


class NodeState(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    SKIPPED = 'skipped'


@dataclass
class ExecutionReport:
    """Esito puro di un'esecuzione DAG: stati, risultati ed errori come testo."""

    dag: str
    id: str
    states: dict[str, str] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dag": self.dag,
            "id": self.id,
            "states": dict(self.states),
            "results": pure_value(self.results),
            "errors": dict(self.errors),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @property
    def failed(self) -> bool:
        return bool(self.errors)


class Session:
    """Sessione di esecuzione di un DAG: struttura puramente runtime.

    Contiene eventi asyncio, eccezioni e valori non serializzabili, quindi non
    compare mai nella proiezione persistibile della sessione utente. Per
    l'osservabilità si usa ``report()``, che è puro.
    """

    def __init__(self, dag_name, session_id, context=None, runtime_session=None):
        self.dag_name = dag_name
        self.id = session_id
        self.context = context if isinstance(context, Scope) else Scope(context or {})
        self.runtime_session = runtime_session
        self.results: dict[str, Any] = {}
        self.states: dict[str, NodeState] = {}
        self.errors: dict[str, Any] = {}
        self._events: dict[str, asyncio.Event] = {}

    def event_for(self, node):
        return self._events.setdefault(node, asyncio.Event())

    async def wait(self, node):
        await self.event_for(node).wait()
        if node in self.errors:
            error = self.errors[node]
            if isinstance(error, BaseException):
                raise error
            from framework.core.flow import FlowError

            raise FlowError(error)
        return self.results.get(node)

    def mark(self, node, state):
        self.states[node] = state
        if state == NodeState.PENDING:
            self._events[node] = asyncio.Event()
        if state in (NodeState.SUCCESS, NodeState.FAILED, NodeState.SKIPPED):
            self.event_for(node).set()

    def report(self) -> ExecutionReport:
        """Proiezione pura dell'esecuzione, utilizzabile da TUI e telemetria."""
        return ExecutionReport(
            dag=str(self.dag_name),
            id=str(self.id),
            states={str(node): NodeState(state).value for node, state in self.states.items()},
            results=pure_mapping(self.results),
            errors={str(node): str(error) for node, error in self.errors.items()},
        )











