from abc import abstractmethod
from typing import Any, Awaitable, Callable, Protocol

import framework.core.flow as flow


class Port(Protocol):
    """Contratto comune per gli adapter di attuazione (Actuator Adapters).

    Gli adapter concreti implementano la logica fisica o software per eseguire comandi,
    modificare stati di dispositivi (es. relè, valvole, motori), gestire feature flag
    e controllare flussi di lavoro di sistema o di rete.
    """

    capabilities: dict[str, Any] = {
        "feedback_loop": False,       # Indica se il dispositivo invia feedback di conferma
        "async_execution": True,      # Esecuzione non bloccante dei comandi
        "emergency_stop": False,     # Supporta l'arresto immediato di emergenza
        "protocols": [],              # Protocolli supportati (es. ["GPIO", "MQTT", "REST", "Modbus"])
    }

    _method_decorators: dict[str, Callable[..., Any]] = {
        "start": flow.result(inputs=("session", "actuator")),
        "stop": flow.result(inputs=("session", "actuator")),
        "execute": flow.result(inputs=("session", "actuator")),
        "set_state": flow.result(inputs=("session", "actuator")),
        "get_state": flow.result(inputs=("session", "actuator")),
        "toggle_feature": flow.result(inputs=("session", "actuator")),
    }

    _seeds: list[Any] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Applica automaticamente i decoratori flow.result specificati in _method_decorators
        for method_name, decorator in Port._method_decorators.items():
            original = cls.__dict__.get(method_name)

            if original is not None:
                setattr(cls, method_name, decorator(original))

    # ------------------------------------------------------------------
    # Ciclo di Vita dell'Adapter
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self, session: object) -> Awaitable[flow.FlowResult]:
        """Inizializza la connessione con l'hardware o con il servizio remoto."""
        ...

    @abstractmethod
    def stop(
        self,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Rilascia le risorse e chiude la connessione in modo sicuro."""
        ...

    # ------------------------------------------------------------------
    # Operazioni Principali di Attuazione
    # ------------------------------------------------------------------

    @abstractmethod
    def execute(
        self,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Esegue un comando diretto sull'attuatore (es. 'open_valve', 'trigger_script')."""
        ...

    @abstractmethod
    def set_state(
        self,
        session: object,
        state: dict[str, Any],
    ) -> Awaitable[flow.FlowResult]:
        """Imposta lo stato target del dispositivo (es. target_temp=24, speed=100)."""
        ...

    @abstractmethod
    def get_state(self, session: object) -> Awaitable[flow.FlowResult]:
        """Legge lo stato attuale o confermato direttamente dall'attuatore."""
        ...

    # ------------------------------------------------------------------
    # Controllo Feature e Flussi Software
    # ------------------------------------------------------------------

    @abstractmethod
    def toggle_feature(
        self,
        session: object,
        feature_name: str,
        enabled: bool | None = None,
    ) -> Awaitable[flow.FlowResult]:
        """Abilita o disabilita una funzionalità/servizio gestito dall'attuatore."""
        ...