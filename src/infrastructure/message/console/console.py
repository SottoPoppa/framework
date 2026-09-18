import datetime
import fnmatch
import logging
import os
import sys
from typing import Any, Dict, List

import framework.port.message as message
import framework.manager.storekeeper as storekeeper

class Adapter(message.Port):
    """
    Enterprise-grade Console Adapter progettato per il logging strutturato e l'auditing.
    Garantisce la conformità dei log per aggregatori esterni (Splunk, ELK, Datadog)
    evitando formattazioni ANSI non standard in ambienti di produzione.
    """

    class AuditFormatter(logging.Formatter):
        """Formatter enterprise per audit log conformi allo standard ISO 8601."""
        
        def format(self, record: logging.LogRecord) -> str:
            # Generazione del timestamp standardizzato ISO 8601 con Timezone locale/UTC
            record.asctime = datetime.datetime.fromtimestamp(
                record.created, datetime.timezone.utc
            ).isoformat(timespec='milliseconds')

            # Iniezione sicura dei campi obbligatori per l'auditing aziendale
            record.transaction_id = getattr(record, 'transaction_id', 'SYSTEM')
            record.domain = getattr(record, 'domain', 'UNKNOWN')
            record.user_id = getattr(record, 'user_id', 'ANONYMOUS')
            record.action = getattr(record, 'action', 'NOT_SPECIFIED')

            return super().format(record)

    def __init__(self, storekeeper: storekeeper.Manager, **constants) -> None:
        """
        Inizializza il sottosistema di logging aziendale verificando i parametri di runtime.
        """
        if constants.get('name'):
            self.name = __name__ + "." + constants['name'].lower()
        else:
            self.name = __name__
        self.adapter = __name__.split('.')[-1]
        self.config = constants
        self.storekeeper = storekeeper
        self.persistence = constants.get('persistence')
        self.project_meta: Dict[str, Any] = self.config.get('project', {})
        
        # Identificativi univoci dell'applicazione per la tracciabilità nei microservizi
        self.project_id: str = self.project_meta.get('identifier', 'enterprise-service')
        self.environment: str = self.project_meta.get('mode', 'production').lower()
        
        # History interna per il pattern Message Queue (Struttura: {dominio: [pointer, [messaggi]]})
        self._history: Dict[str, List[Any]] = {}
        self.processable: List[str] = ['log', 'audit']

        # Configurazione del Logger Core dell'Adapter
        self._logger = logging.getLogger(f"audit.{self.project_id}")
        self._logger.propagate = False
        
        # Gestione dei Log Level in base all'ambiente (Principio del Least Privilege sui dati di log)
        if self.environment == 'production':
            self._logger.setLevel(logging.INFO)
        else:
            self._logger.setLevel(logging.DEBUG)

        self._initialize_handler(constants.get('format'))

    def _initialize_handler(self, custom_format: str = None) -> None:
        """Configura lo stream di output standard per l'architettura a container (Twelve-Factor App)."""
        # Utilizza stdout per convogliare correttamente i log nei collettori di container (Docker/Kubernetes)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(self._logger.level)

        # Formato standard di Audit aziendale (Scannabile sia da umani che da regex/parser)
        # Struttura: TIMESTAMP | ENV | ENV_ID | TX_ID | DOMAIN | USER | LEVEL | LOCATION | MSG
        default_audit_format = (
            "%(asctime)s | "
            f"[{self.environment.upper()}] | "
            f"[{self.project_id}] | "
            "[TX:%(transaction_id)s] | "
            "[DOM:%(domain)s] | "
            "[USER:%(user_id)s] | "
            "%(levelname)-8s | "
            "%(filename)s:%(lineno)d | "
            "%(message)s"
        )

        log_format = custom_format if custom_format else default_audit_format
        formatter = self.AuditFormatter(log_format)
        stdout_handler.setFormatter(formatter)
        
        # Reset preventivo degli handler per evitare duplicazioni in caso di hot-reload
        self._logger.handlers.clear()
        self._logger.addHandler(stdout_handler)

    async def can(self, *services: Any, **constants: Any) -> bool:
        """Verifica se l'operazione richiesta rientra nelle capacità dell'interfaccia."""
        return constants.get('name') in self.processable

    async def post(self, *services: Any, **constants: Any) -> None:
        """
        Traccia e persiste un evento di Audit nel sistema loggandolo in formato standard.
        
        Metadati supportati in **constants:
            - message (str): Il corpo del messaggio/evento
            - level (str): Gravità (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            - domain (str): Dominio logico dell'evento (es. "billing", "auth")
            - transaction_id (str): Id di correlazione della richiesta
            - user_id (str): Identificativo dell'operatore/sistema che esegue l'azione
            - action (str): Tipo di operazione (es. "READ_RECORD", "UPDATE_PASSWORD")
        """
        message_text: str = constants.get('message', str(constants))
        level: str = constants.get('level', 'INFO').upper()
        domain: str = constants.get('domain', 'system')

        # Estrazione metadati di Audit con fallback difensivo
        audit_context = {
            'transaction_id': constants.get('transaction_id', 'SYSTEM'),
            'domain': domain,
            'user_id': constants.get('user_id', 'ANONYMOUS'),
            'action': constants.get('action', 'NOT_SPECIFIED')
        }

        # Mapping dinamico dei livelli di log nativi senza costrutti condizionali pesanti
        log_level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        
        target_level = log_level_map.get(level, logging.INFO)
        
        # Scrittura nel flusso di log con iniezione del contesto di Audit
        self._logger.log(target_level, message_text, extra=audit_context)
        if self.persistence:
            from datetime import datetime

            adesso = datetime.now().strftime("%Y-%m-%d")
            await self.storekeeper.store("id",repository="logging",payload=constants,filter={'eq':{'filename':f'{adesso}.log'}})
        # Persistenza strutturata nella history interna per scopi di riconciliazione ordinaria
        '''if domain not in self._history:
            self._history[domain] = [0, []]
        
        # Archiviamo l'evento come dizionario strutturato per agevolare il filtraggio successivo
        self._history[domain][1].append({
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'payload': message_text,
            **audit_context
        })'''

    async def read(self, *services: Any, **constants: Any) -> List[Dict[str, Any]]:
        """
        Consente ai moduli interni la lettura degli audit log accumulati e non ancora processati.
        Supporta il filtraggio per domini tramite pattern matching.
        """
        domain_pattern: str = constants.get('domain', '*')
        results: List[Dict[str, Any]] = []

        for registered_domain in self._history.keys():
            if fnmatch.fnmatch(registered_domain, domain_pattern):
                pointer, messages = self._history[registered_domain]
                
                if pointer < len(messages):
                    # Avanzamento atomico dell'indice di lettura per evitare race condition logiche
                    self._history[registered_domain][0] = len(messages)
                    results.append({
                        'domain': registered_domain,
                        'events': messages[pointer:]
                    })

        return results