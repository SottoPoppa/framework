from abc import abstractmethod
from typing import Any, Awaitable, Callable, Protocol

import framework.core.flow as flow


class Port(Protocol):
    """Contratto comune per gli adapter di percezione sensoriale e processing (Sensation Adapters).

    Mentre gli adapter Sensor gestiscono la lettura diretta del dato grezzo dall'hardware,
    gli adapter Sensation astraggono la percezione di alto livello del sistema:
    elaborazione di segnali, sensori virtuali/fusi (data fusion), riconoscimento di pattern,
    rilevamento di anomalie ed estrazione del contesto operativo.
    """

    capabilities: dict[str, Any] = {
        "data_fusion": False,          # Capacità di combinare più fonti di senso
        "anomaly_detection": False,    # Rilevamento automatico di valori/comportamenti anomali
        "real_time_stream": True,      # Elaborazione di flussi sensoriali in tempo reale
        "context_awareness": False,    # Estrazione di contesti operativi di alto livello
    }

    _method_decorators: dict[str, Callable[..., Any]] = {
        "start": flow.result(inputs=("session", "sensation")),
        "stop": flow.result(inputs=("session", "sensation")),
        "perceive": flow.result(inputs=("session", "sensation")),
        "process_stream": flow.result(inputs=("session", "sensation")),
        "evaluate_threshold": flow.result(inputs=("session", "sensation")),
        "get_context": flow.result(inputs=("session", "sensation")),
    }

    _seeds: list[Any] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Applica automaticamente i decoratori flow.result ai metodi dell'adapter concreto
        for method_name, decorator in Port._method_decorators.items():
            original = cls.__dict__.get(method_name)

            if original is not None:
                setattr(cls, method_name, decorator(original))

    # ------------------------------------------------------------------
    # Ciclo di Vita dell'Adapter Sensoriale
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self, session: object) -> Awaitable[flow.FlowResult]:
        """Inizializza la pipeline di percezione o la connessione al motore di analisi."""
        ...

    @abstractmethod
    def stop(
        self,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Arresta le pipeline e libera i buffer di elaborazione sensoriale."""
        ...

    # ------------------------------------------------------------------
    # Operazioni Principali di Percezione (Perception & Data Processing)
    # ------------------------------------------------------------------

    @abstractmethod
    def perceive(
        self,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Elabora i dati grezzi ricevuti da uno o più sensori per restituire uno stato percepito.
        
        Es: trasforma i gradi centigradi in uno stato percepito ('Too Hot', 'Normal', 'Overheating').
        """
        ...

    @abstractmethod
    def process_stream(
        self,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Applica algoritmi di filtraggio (es. filtri Kalman, medie mobili) su un flusso di dati."""
        ...

    @abstractmethod
    def evaluate_threshold(
        self,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Valuta se uno specifico valore sensoriale viola regole o pattern di sicurezza."""
        ...

    @abstractmethod
    def get_context(
        self,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Restituisce il contesto sensoriale globale o lo stato aggregato del sistema."""
        ...