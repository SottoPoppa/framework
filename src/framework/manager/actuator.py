''' 
In ambito informatico, una classe chiamata “actuator” potrebbe avere il compito di gestire azioni o operazioni che influenzano il comportamento di un sistema. Ecco alcune possibili funzioni:

Controllo di dispositivi fisici: Un “actuator” potrebbe interfacciarsi con dispositivi hardware, come motori, valvole o relè, per attivare o disattivare specifiche azioni. Ad esempio, in un sistema di automazione industriale, un “actuator” potrebbe aprire o chiudere una valvola di controllo.
Risposta a eventi: L’actuator potrebbe reagire a eventi o condizioni specifiche. Ad esempio, in un sistema di riscaldamento, un “actuator” potrebbe regolare la temperatura in base ai sensori ambientali.
Gestione di flussi di dati: In applicazioni di streaming o elaborazione di dati, un “actuator” potrebbe avviare o interrompere flussi di dati, come l’invio di notifiche o l’avvio di processi di calcolo.
Controllo di servizi o componenti software: Un “actuator” potrebbe attivare o disattivare funzionalità specifiche di un’applicazione o di un sistema. Ad esempio, in un’app web, un “actuator” potrebbe abilitare o disabilitare una modalità di manutenzione.
Automazione di processi: L’actuator potrebbe automatizzare sequenze di operazioni, come l’avvio di backup, la sincronizzazione di dati o l’esecuzione di script.
'''

import framework.port.actuation as actuation
import framework.port.manager as manager
import framework.core.flow as flow
from framework.manager.loader import Loader
import framework.core.framework as framework_module


class Actuator(manager.Port):
    def __init__(
        self,
        actuators: list[actuation.Port],
        loader: Loader,
        framework: framework_module.Framework,
        **constants,
    ):
        self.actuators = actuators
        self.loader = loader
        self.framework = framework
        self.logger = framework.get_logger("actuator")
        self._maintenance_mode: bool = False
        self._active_flows: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Ciclo di Vita (Startup e Shutdown)
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def startup(self, session):
        """Inizializza ed avvia tutti gli adapter/porte attuatore registrati."""
        loops = []
        self.logger.info("Actuator startup", active_actuators=len(self.actuators))
        
        for actuator in self.actuators:
            if hasattr(actuator, "start"):
                async def run_actuator(current=actuator):
                    #exit(1)
                    adapter_name = getattr(current, "name", None) or type(current).__name__
                    self.logger.info("Avvio actuator adapter", adapter=adapter_name)
                    result = await current.start(session)
                    
                    if flow.is_result(result) and not flow.check(result):
                        raise RuntimeError(flow.output(result))
                    return flow.output(result) if flow.is_result(result) else result

                loops.append(run_actuator())
                
        return loops

    @flow.result(inputs=(), outputs=())
    async def shutdown(self, session):
        """Spegne in modo sicuro tutti i dispositivi/adapter attivi."""
        self.logger.info("Arresto in corso per gli attuatori...")
        for actuator in self.actuators:
            if hasattr(actuator, "stop"):
                await actuator.stop(session)

    # ------------------------------------------------------------------
    # 1. Controllo Dispositivi Fisici & Hardware
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def execute_command(self, session, device_id: str, command: str, **payload):
        """Invia un comando diretto a un dispositivo hardware (es. valvola, motore, relè)."""
        target = self._get_actuator_driver(device_id)
        if not target:
            self.logger.error("Attuatore/Dispositivo non trovato", device_id=device_id)
            return None

        self.logger.info("Esecuzione comando hardware", device_id=device_id, command=command)
        if hasattr(target, "execute"):
            return await target.execute(session, command, **payload)
        return None

    @flow.result(inputs=(), outputs=())
    async def set_state(self, session, device_id: str, state: dict):
        """Imposta direttamente lo stato di un dispositivo (es. temperatura target, posizione valvola)."""
        target = self._get_actuator_driver(device_id)
        if target and hasattr(target, "set_state"):
            return await target.set_state(session, state)
        return None

    # ------------------------------------------------------------------
    # 2. Controllo Servizi & Feature Toggle (Maintenance Mode, Feature Flags)
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def set_maintenance_mode(self, session, enabled: bool):
        """Abilita o disabilita la modalità manutenzione nell'applicazione."""
        self._maintenance_mode = enabled
        self.logger.info("Stato manutenzione aggiornato", maintenance_mode=enabled)
        return {"maintenance_mode": self._maintenance_mode}

    @flow.result(inputs=(), outputs=())
    async def toggle_feature(self, session, feature_name: str, enabled: bool):
        """Abilita o disabilita al volo un componente software o una funzionalità."""
        self.logger.info("Feature toggle modificato", feature=feature_name, state=enabled)
        for actuator in self.actuators:
            if hasattr(actuator, "toggle_feature"):
                await actuator.toggle_feature(session, feature_name, enabled)
        return True

    # ------------------------------------------------------------------
    # 3. Gestione Flussi Dati & Risposta Eventi
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def control_data_stream(self, session, stream_id: str, action: str):
        """Avvia o interrompe un flusso dati (es. streaming sensori, pipeline notifiche)."""
        action = action.lower()
        if action in ("start", "resume"):
            self._active_flows[stream_id] = True
        elif action in ("stop", "pause"):
            self._active_flows[stream_id] = False
        
        self.logger.info("Stato flusso dati aggiornato", stream_id=stream_id, action=action)
        return {"stream_id": stream_id, "active": self._active_flows.get(stream_id, False)}

    # ------------------------------------------------------------------
    # 4. Automazione di Processi (Job execution)
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def run_task(self, session, task_name: str, **params):
        """Esegue/automatizza un task di sistema (backup, sync dati, script isolati)."""
        self.logger.info("Avvio automazione processo", task=task_name)
        
        # Esempio: delega il task all'infrastructure loader o a uno specifico driver
        infrastructure = getattr(self.loader, "infrastructure", None)
        if infrastructure and hasattr(infrastructure, "run_task"):
            return await infrastructure.run_task(task_name, **params)
            
        return {"status": "executed", "task": task_name}

    # ------------------------------------------------------------------
    # Helper Metodi Interni
    # ------------------------------------------------------------------

    def _get_actuator_driver(self, device_id: str = None):
        """Recupera il driver/adapter specifico per il dispositivo richiesto."""
        if not device_id and self.actuators:
            return self.actuators[-1]

        for actuator in self.actuators:
            # Cerca per ID o per lista dispositivi gestiti dall'adapter
            if getattr(actuator, "id", None) == device_id:
                return actuator
            devices = getattr(actuator, "devices", [])
            if device_id in devices:
                return actuator

        return self.actuators[-1] if self.actuators else None