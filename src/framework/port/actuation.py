from abc import ABC, abstractmethod
import framework.core.flow as flow


class Port(ABC):
    """Contratto comune per gli adapter di attuazione (Actuator Adapters).

    Gli adapter concreti implementano la logica fisica o software per eseguire comandi,
    modificare stati di dispositivi (es. relè, valvole, motori), gestire feature flag
    e controllare flussi di lavoro di sistema o di rete.
    """

    capabilities = {
        "feedback_loop": False,       # Indica se il dispositivo invia feedback di conferma
        "async_execution": True,      # Esecuzione non bloccante dei comandi
        "emergency_stop": False,     # Supporta l'arresto immediato di emergenza
        "protocols": [],              # Protocolli supportati (es. ["GPIO", "MQTT", "REST", "Modbus"])
    }

    _method_decorators = {
        "start": flow.result(inputs=("session", "actuator")),
        "stop": flow.result(inputs=("session", "actuator")),
        "execute": flow.result(inputs=("session", "actuator")),
        "set_state": flow.result(inputs=("session", "actuator")),
        "get_state": flow.result(inputs=("session", "actuator")),
        "toggle_feature": flow.result(inputs=("session", "actuator")),
    }

    _seeds = []

    def __init_subclass__(cls, **kwargs):
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
    async def start(self, *services, **constants):
        """Inizializza la connessione con l'hardware o con il servizio remoto."""
        pass

    @abstractmethod
    async def stop(self, *services, **constants):
        """Rilascia le risorse e chiude la connessione in modo sicuro."""
        pass

    # ------------------------------------------------------------------
    # Operazioni Principali di Attuazione
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, *services, **constants):
        """Esegue un comando diretto sull'attuatore (es. 'open_valve', 'trigger_script')."""
        pass

    @abstractmethod
    async def set_state(self, *services, **constants):
        """Imposta lo stato target del dispositivo (es. target_temp=24, speed=100)."""
        pass

    @abstractmethod
    async def get_state(self, *services, **constants):
        """Legge lo stato attuale o confermato direttamente dall'attuatore."""
        pass

    # ------------------------------------------------------------------
    # Controllo Feature e Flussi Software
    # ------------------------------------------------------------------

    @abstractmethod
    async def toggle_feature(self, *services, **constants):
        """Abilita o disabilita una funzionalità/servizio gestito dall'attuatore."""
        pass