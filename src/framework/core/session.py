"""Stato di sessione del framework.

Il modulo separa esplicitamente due mondi:

* ``UserSessionData`` — dati puri, serializzabili, validabili tramite
  ``framework.service.scheme`` e ricostruibili senza riferimenti runtime;
* ``UserSession`` / ``Session`` — controller runtime che possiedono
  ``Scope``, esecuzioni DAG, eventi asyncio, Manager e Adapter.

Regola invariante: i dati puri non conoscono il runtime, il runtime può usare
i dati puri ma non viene mai inserito nella proiezione persistibile.
"""

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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


USER_SESSION_SCHEME: dict[str, Any] = {
    "id": {"type": "string", "required": True, "empty": False},
    "context": {"type": "dict", "required": True},
    "authentication": {"type": "dict", "required": True},
    "results": {"type": "dict", "required": True},
}


@dataclass
class UserSessionData:
    """Stato puro della sessione utente: nessun riferimento al runtime."""

    id: str
    context: dict[str, Any] = field(default_factory=dict)
    authentication: dict[str, Any] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Proiezione persistibile: solo id, contesto, autenticazione e risultati."""
        return {
            "id": str(self.id),
            "context": pure_value(self.context),
            "authentication": pure_value(self.authentication),
            "results": pure_value(self.results),
        }

    def to_json(self) -> str:
        """Serializza la proiezione persistibile in JSON deterministico."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Any) -> "UserSessionData":
        """Ricostruisce lo stato puro da un dizionario deserializzato."""
        if not isinstance(payload, dict):
            raise TypeError("Lo stato della sessione deve essere una mappa")
        return cls(
            id=str(payload.get("id") or ""),
            context=pure_mapping(payload.get("context") or {}),
            authentication=pure_mapping(payload.get("authentication") or {}),
            results={
                str(dag): pure_mapping(nodes)
                for dag, nodes in (payload.get("results") or {}).items()
            },
        )

    @classmethod
    def from_json(cls, payload: str) -> "UserSessionData":
        return cls.from_dict(json.loads(payload))

    def validate(self, schema: dict[str, Any] | None = None):
        """Valida lo stato puro tramite ``framework.service.scheme``."""
        from framework.service import scheme

        return scheme.normalize(self.to_dict(), schema or USER_SESSION_SCHEME)


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

    def __init__(self, dag_name, session_id, context=None, user_session=None, runtime_session=None):
        self.dag_name = dag_name
        self.id = session_id
        self.context = context if isinstance(context, Scope) else Scope(context or {})
        self.user_session = user_session
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
            raise self.errors[node]
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


class UserSession:
    """Controller runtime della sessione utente.

    Possiede lo ``Scope`` operativo e le esecuzioni DAG, mentre lo stato
    condivisibile resta confinato in ``UserSessionData``.
    """

    def __init__(self, session_id, context=None, authentication=None):
        self.id = str(session_id)
        self.context = (
            context
            if isinstance(context, Scope)
            else Scope(pure_mapping(context or {}))
        )
        self.authentication: dict[str, Any] = pure_mapping(authentication or {})
        self.results: dict[str, dict[str, Any]] = {}
        # Riferimenti runtime: non entrano mai nella serializzazione.
        self.executions: dict[str, Session] = {}

    # ── contesto e autenticazione ────────────────────────────────────────────

    def update_context(self, values: Any) -> dict[str, Any]:
        """Aggiorna il contesto con i soli valori puri, scartando il runtime."""
        projection = pure_mapping(values)
        for key, value in projection.items():
            self.context.set(key, value)
        return projection

    def authenticate(self, authentication: Any) -> dict[str, Any]:
        """Fonde nell'autenticazione pubblica i soli dati serializzabili."""
        self.authentication.update(pure_mapping(authentication))
        return self.authentication

    # ── risultati pubblicati dai DAG ─────────────────────────────────────────

    def publish_result(self, dag_name: str, node_name: str, value: Any) -> Any:
        """Pubblica l'ultimo payload riuscito di un nodo nella sessione utente."""
        try:
            safe_value = pure_value(value)
        except ImpureValueError:
            return None
        self.results.setdefault(str(dag_name), {})[str(node_name)] = safe_value
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

    # ── esecuzioni DAG (solo runtime) ────────────────────────────────────────

    def execution(self, dag_name: str) -> Session | None:
        return self.executions.get(dag_name)

    def register_execution(self, dag_name: str, session: Session) -> Session:
        self.executions[dag_name] = session
        return session

    def clear_executions(self) -> None:
        self.executions.clear()

    # ── proiezione pura ──────────────────────────────────────────────────────

    def snapshot(self) -> UserSessionData:
        """Estrae lo stato puro della sessione, senza le esecuzioni DAG."""
        return UserSessionData(
            id=self.id,
            context=pure_mapping(self.context.data),
            authentication=pure_mapping(self.authentication),
            results={dag: dict(nodes) for dag, nodes in self.results.items()},
        )

    def restore(self, data: "UserSessionData | dict[str, Any]") -> "UserSession":
        """Ripristina lo stato puro; l'identità resta quella del runtime."""
        state = data if isinstance(data, UserSessionData) else UserSessionData.from_dict(data)
        self.update_context(state.context)
        self.authentication.update(state.authentication)
        for dag, nodes in state.results.items():
            self.results.setdefault(str(dag), {}).update(nodes)
        return self

    @classmethod
    def from_data(cls, data: "UserSessionData | dict[str, Any]") -> "UserSession":
        """Costruisce un controller runtime a partire dai soli dati puri."""
        state = data if isinstance(data, UserSessionData) else UserSessionData.from_dict(data)
        session = cls(state.id, Scope(dict(state.context)), state.authentication)
        session.results = {str(dag): dict(nodes) for dag, nodes in state.results.items()}
        return session

    def to_dict(self) -> dict[str, Any]:
        """Restituisce la proiezione persistibile, senza esecuzioni DAG."""
        return self.snapshot().to_dict()

    def to_json(self) -> str:
        """Serializza la proiezione persistibile in JSON deterministico."""
        return self.snapshot().to_json()

    def validate(self, schema: dict[str, Any] | None = None):
        """Valida la proiezione pubblica tramite ``framework.service.scheme``."""
        return self.snapshot().validate(schema)


