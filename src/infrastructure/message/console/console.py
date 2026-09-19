import fnmatch
from typing import Any, Dict, List

import framework.port.message as message
import framework.manager.storekeeper as storekeeper
from framework.core.infrastructure import Infrastructure

class Adapter(message.Port):
    """
    Enterprise-grade Console Adapter progettato per il logging strutturato e l'auditing.
    Garantisce la conformità dei log per aggregatori esterni (Splunk, ELK, Datadog)
    evitando formattazioni ANSI non standard in ambienti di produzione.
    """

    def __init__(
        self,
        storekeeper: storekeeper.Manager,
        infrastructure: Infrastructure,
        **constants,
    ) -> None:
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
        self._logger = infrastructure.get_logger("message.console")
        self.persistence = constants.get('persistence')
        self.project_meta: Dict[str, Any] = self.config.get('project', {})
        
        # Identificativi univoci dell'applicazione per la tracciabilità nei microservizi
        self.project_id: str = self.project_meta.get('identifier', 'enterprise-service')
        self.environment: str = self.project_meta.get('mode', 'production').lower()
        
        # History interna per il pattern Message Queue (Struttura: {dominio: [pointer, [messaggi]]})
        self._history: Dict[str, List[Any]] = {}
        self.processable: List[str] = ['log', 'audit']


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
        log_method = getattr(self._logger, level.lower(), self._logger.info)
        log_method(message_text, **audit_context)
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