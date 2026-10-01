'''
In ambito informatico, una classe chiamata “sensor” potrebbe essere progettata per rappresentare e gestire dispositivi sensori o strumenti di rilevamento. Ecco alcune possibili funzioni che una classe “sensor” potrebbe avere:

Acquisizione dei dati: La classe “sensor” potrebbe includere metodi per leggere dati dai sensori, come temperatura, umidità, pressione, luminosità o movimento.
Calibrazione: Potrebbe offrire funzionalità per calibrare i sensori, garantendo misurazioni accurate e affidabili.
Gestione degli eventi: La classe potrebbe notificare il sistema quando si verificano eventi rilevanti, come superamento di soglie o cambiamenti significativi nei dati.
Interfaccia con l’hardware: Potrebbe fornire metodi per configurare, attivare o disattivare i sensori fisici collegati al sistema.
Filtraggio e elaborazione dei dati: La classe potrebbe elaborare i dati grezzi dai sensori, applicando filtri o algoritmi per migliorare la qualità delle informazioni.
Monitoraggio continuo: Potrebbe gestire il monitoraggio costante dei sensori e la registrazione dei dati nel tempo.
'''

import framework.port.sensation as sensation
import framework.port.manager as manager
import framework.core.flow as flow
from framework.manager.loader import Loader
import framework.core.framework as framework_module


class Manager(manager.Port):
    def __init__(
        self,
        sensors: list[sensation.Port],
        loader: Loader,
        framework: framework_module.Framework,
        **constants,
    ):
        self.sensors = sensors
        self.loader = loader
        self.framework = framework
        self.logger = framework.get_logger("sensor")
        self._calibration_offsets: dict[str, float] = constants.get("calibration_offsets", {})
        self._thresholds: dict[str, dict[str, float]] = constants.get("thresholds", {})

    # ------------------------------------------------------------------
    # Ciclo di Vita (Startup e Shutdown)
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def startup(self, session):
        """Inizializza ed avvia l'ascolto/polling di tutti gli adapter sensore."""
        loops = []
        self.logger.info("Sensor Manager startup", active_sensors=len(self.sensors))

        for sensor_adapter in self.sensors:
            if hasattr(sensor_adapter, "start"):
                async def run_sensor(current=sensor_adapter):
                    adapter_name = getattr(current, "name", None) or type(current).__name__
                    self.logger.info("Avvio sensor adapter", adapter=adapter_name)
                    result = await current.start(session)

                    if flow.is_result(result) and not flow.check(result):
                        raise RuntimeError(flow.output(result))
                    return flow.output(result) if flow.is_result(result) else result

                loops.append(run_sensor())

        return loops

    @flow.result(inputs=(), outputs=())
    async def shutdown(self, session):
        """Arresta le letture e chiude le connessioni ai sensori."""
        self.logger.info("Arresto in corso per i sensori...")
        errors = []
        for sensor_adapter in reversed(self.sensors):
            stop = getattr(sensor_adapter, "stop", None)
            if not callable(stop):
                continue
            try:
                result = await stop(session)
            except Exception as exc:
                errors.append(exc)
                self.logger.error(
                    "Arresto sensor adapter fallito",
                    adapter=getattr(sensor_adapter, "name", type(sensor_adapter).__name__),
                    exception=exc,
                )
                continue
            if flow.is_result(result) and not flow.check(result):
                error = flow.output(result)
                errors.append(error)
                self.logger.error(
                    "Arresto sensor adapter fallito",
                    adapter=getattr(sensor_adapter, "name", type(sensor_adapter).__name__),
                    error=error,
                )
        if errors:
            return flow.error(errors)
        return flow.success(None)

    # ------------------------------------------------------------------
    # 1. Acquisizione Dati (Lettura e Streaming)
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def read_data(self, session, sensor_id: str, field: str = None, **constants):
        target = self._get_sensation_driver(sensor_id)
        """Legge i dati da un sensore specifico.
        Applica automaticamente eventuale calibrazione/offset e filtri se presenti.
        """
        driver = self._get_sensation_driver(sensor_id)
        if not driver:
            self.logger.error("Sensore non trovato", sensor_id=sensor_id)
            return None

        raw_data = await driver.read(session, sensor_id=sensor_id, **constants) if hasattr(driver, "read") else None
        if raw_data is None:
            return None

        # Elaborazione e calibrazione dei dati grezzi
        processed_data = self._process_raw_data(sensor_id, raw_data)

        # Gestione eventi / Controllo soglie
        await self._check_thresholds(session, sensor_id, processed_data)

        if field and isinstance(processed_data, dict):
            return processed_data.get(field)

        return processed_data

    @flow.result(inputs=(), outputs=())
    async def read_all(self, session):
        """Effettua una scansione/lettura completa di tutti i sensori registrati."""
        results = {}
        for sensor_adapter in self.sensors:
            if hasattr(sensor_adapter, "read_all"):
                data = await sensor_adapter.read_all(session)
                if isinstance(data, dict):
                    results.update(data)
        return results

    # ------------------------------------------------------------------
    # 2. Calibrazione & Filtraggio
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def calibrate(self, session, sensor_id: str, offset: float):
        """Imposta un valore di offset per la calibrazione delle letture."""
        self._calibration_offsets[sensor_id] = offset
        self.logger.info("Calibrazione sensore aggiornata", sensor_id=sensor_id, offset=offset)
        
        driver = self._get_sensation_driver(sensor_id)
        if driver and hasattr(driver, "calibrate"):
            await driver.calibrate(session, sensor_id, offset)
            
        return {"sensor_id": sensor_id, "offset": offset}

    # ------------------------------------------------------------------
    # 3. Gestione Eventi e Soglie (Threshold Alerts)
    # ------------------------------------------------------------------

    @flow.result(inputs=(), outputs=())
    async def set_threshold(self, session, sensor_id: str, min_value: float = None, max_value: float = None):
        """Definisce i limiti minimi/massimi per scatenare avvisi in caso di superamento."""
        self._thresholds[sensor_id] = {
            "min": min_value,
            "max": max_value,
        }
        self.logger.info("Soglia impostata", sensor_id=sensor_id, min=min_value, max=max_value)
        return True

    # ------------------------------------------------------------------
    # Helper Metodi Interni
    # ------------------------------------------------------------------

    def _process_raw_data(self, sensor_id: str, data):
        """Applica filtri, calibrazione e pulizia ai dati grezzi ricevuti."""
        offset = self._calibration_offsets.get(sensor_id, 0.0)

        if isinstance(data, (int, float)):
            return data + offset

        if isinstance(data, dict):
            # Se è un dizionario (es. {"value": 22.5, "unit": "C"}), applica l'offset al valore
            if "value" in data and isinstance(data["value"], (int, float)):
                data["value"] += offset
            return data

        return data

    async def _check_thresholds(self, session, sensor_id: str, data):
        """Verifica se i dati superano le soglie impostate ed emette eventuali log/notifiche."""
        if sensor_id not in self._thresholds:
            return

        value = data.get("value") if isinstance(data, dict) else data
        if not isinstance(value, (int, float)):
            return

        limits = self._thresholds[sensor_id]
        min_limit = limits.get("min")
        max_limit = limits.get("max")

        if min_limit is not None and value < min_limit:
            self.logger.warning("Soglia minima superata!", sensor_id=sensor_id, value=value, min=min_limit)
        elif max_limit is not None and value > max_limit:
            self.logger.warning("Soglia massima superata!", sensor_id=sensor_id, value=value, max=max_limit)

    def _get_sensor_driver(self, sensor_id: str = None):
        """Recupera l'adapter del sensore appropriato in base all'ID."""
        if not sensor_id and self.sensors:
            return self.sensors[-1]

        for sensor_adapter in self.sensors:
            if getattr(sensor_adapter, "id", None) == sensor_id:
                return sensor_adapter
            managed_sensors = getattr(sensor_adapter, "sensors", [])
            if sensor_id in managed_sensors:
                return sensor_adapter

        return self.sensors[-1] if self.sensors else None