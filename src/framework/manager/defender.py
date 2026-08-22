from secrets import token_urlsafe
from typing import Dict, Any
from urllib.parse import urlparse, parse_qs, urljoin


import framework.service.language as language
import framework.service.scheme as scheme
import framework.service.flow as flow
import framework.manager.loader as loader
import framework.port.authentication as authentication
import framework.port.manager as manager

class Manager(manager.Port):
    _session_exempt_methods = {
        "session_create",
        "session_get",
        "get_policy",
        "authorized",
        "resolve_route",
    }
    def __init__(self, loader: loader.Loader, authentications: list[authentication.Port], **constants):
        """
        Inizializza il manager con i servizi necessari alla gestione delle richieste.

        :param loader: Carica risorse, manager e file DSL dell'applicazione.
        :param authentications: Provider usati per autenticare, registrare e
            disconnettere gli utenti.
        :param constants: Configurazioni del manager, incluse le policy da
            caricare durante l'avvio.
        """

        # Interpreta i file DSL e gestisce le sessioni dell'interprete.
        self.interpreter = language.Interpreter(scheme.schemes)

        # Loader condiviso dal framework per leggere risorse e manager.
        self.loader = loader

        # Configurazione ricevuta dal container, conservata per il bootstrap.
        self.config = constants

        # Provider di autenticazione utilizzati dai metodi del ciclo di vita
        # dell'utente: authenticate, activate, reinstate e terminate.
        self.authentications = authentications

        # Nomi dei controller DSL caricati durante startup().
        self.controllers = []

        # Policy caricate e valutate dall'interprete, indicizzate per nome.
        self.policies = {}

    @flow.result()
    async def shutdown(self, session):
        await self.interpreter.stop()
    
    @flow.result()
    async def startup(self, session=None):
        if session is not None:
            return None
        self.managers = self.loader.get_managers()
        await self.interpreter.start()
        TARGET_PORTS = {'presentation', 'persistence', 'message'}

        # Genera la lista filtrata
        filtered_keys = [x for x in self.config if x in TARGET_PORTS]
        for policy in filtered_keys:
            filename = self.config[policy]
            path = f"src/application/policy/{policy}/{filename}"
            code = await self.loader.resource(path)
            await self.interpreter.load_file(path, code)
            #await self.load_file(name, source)
            session_result = await self.session_create()
            async with flow.output(session_result) as session:
                self.policies[policy] = await session.run(path)
            print(f"[+] Policy: {policy}/{filename}")

        from pathlib import Path

        controllers_path = Path("src/application/controller")
        for file in controllers_path.glob("*.dsl"):
            code = await self.loader.resource(file)
            controller_name = file.stem
            self.controllers.append(controller_name)
            await self.interpreter.load_file(controller_name, code)
        
        print("[+] Controllers: ",self.controllers)

    @flow.result(inputs='session')
    async def session_create(self, env={},**session):
        env = env | {**self.managers}
        if not session.get("id"):
            session["id"] = token_urlsafe(16)
        self.interpreter.session_create(sid=session, env=env)
        return language.SessionHandle(self.interpreter, session=session)

    def session_get(self, sid) -> language.SessionHandle | None:
        # ricostruisce l'handle senza duplicare stato
        if sid not in self.interpreter._runner.sessions:
            return None
        return language.SessionHandle(self.interpreter, sid)

    
    def get_policy(self, policy):
        return self.policies.get(policy)

    @flow.result(inputs=('session',))
    async def new_session(self, session):
        return flow.success(session)
    
    @flow.result(outputs=('session',))
    async def terminate(self, session, **constants) -> bool:
        """
        Termina la sessione di un utente specificato.

        :param constants: Deve includere 'identifier'.
        :return: True se la sessione è stata terminata, False se l'utente non esiste.
        """

        for authentication in self.authentications:
            session_result = await authentication.sign_out(session)
            if session_result.get('success'):
                session.update(session_result['outputs'])
            else:
                return flow.error(session_result['errors'])

        return flow.success(session)

    @flow.result(outputs=('session',), safe_kwargs=True)
    async def reinstate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        for authentication in self.authentications:
            #provider_persistence = authentication.config.get('persistence')
            session_result = await authentication.sign_aid(**constants)
            if session_result.get('success'):
                session.setdefault('providers', {})
                session.setdefault('user', {})
                session['providers'][authentication.name] = session_result['outputs']['providers'][authentication.name]
                session['user'] |= session_result['outputs']['user']
            else:
                return flow.error(session_result['errors'])
            '''if provider_persistence:
                await storekeeper.store(repository='sessions',payload=session)
                pass'''
        return flow.success(session)

    @flow.result(outputs=('session',))
    async def authenticate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        for authentication in self.authentications:
            #provider_persistence = authentication.config.get('persistence')
            session_result = await authentication.sign_in(**constants)
            if session_result.get('success'):
                session.setdefault('providers', {})
                session.setdefault('user', {})
                session['providers'][authentication.name] = session_result['outputs']['providers'][authentication.name]
                session['user'] |= session_result['outputs']['user']
            else:
                return flow.error(session_result['errors'])
            '''if provider_persistence:
                await storekeeper.store(repository='sessions',payload=session)
                pass'''
        return flow.success(session)


    @flow.result(outputs=('session',))
    async def activate(self, session, **constants) -> Any:
        """
        Registra un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se la registrazione ha successo, altrimenti None.
        """
        for authentication in self.authentications:
            session_result = await authentication.sign_up(**constants)
            if session_result.get('success'):
                session.setdefault('providers', {})
                session.setdefault('user', {})
                session['providers'][authentication.name] = session_result['outputs']['providers'][authentication.name]
                session['user'] |= session_result['outputs']['user']
            else:
                return flow.error(session_result['errors'])
        return flow.success(session)

    def authorized(self, policy, **constants) -> bool:
        policy = self.get_policy(policy)
        if not policy:
            return False
        rules = policy.get('rules', {})
        action, resource, location = constants.get('action', ''), constants.get('resource', ''), constants.get('location', '')
        target = {'action':action, 'resource':resource, 'location':location}
        filted_rules = []
        all_resutl = []
        if location in rules:
            filted_rules = rules.get(location)
        elif resource in rules:
            filted_rules = rules.get(resource)
        else:
            pass

        #print("--------------->2",constants)  
        for rule in filted_rules:
            #print("--------------->3",rule)
            for_target = rule.get('target', {}) | target
            #print("--------------->4",for_target)
            condition = rule.get('condition')
            if callable(condition):
                tes = condition(**for_target)
                effect = rule.get('effect')
                if effect == 'allow':
                    all_resutl.append(tes)
                elif effect == 'deny':
                    all_resutl.append(not tes)
            elif isinstance(condition, bool):
                if rule.get('effect') == 'allow':
                    all_resutl.append(condition)
                elif rule.get('effect') == 'deny':
                    all_resutl.append(not condition)
            else:
                all_resutl.append(False)
        return any(all_resutl) if len(all_resutl) > 0 else False

    def resolve_route(self, risorse, request_url, request_method, base_url=None,**kargs):
        
        try:
            # 1. Normalizzazione URL
            # Se request_url è relativo (es. "/home"), urljoin lo unisce a base_url
            full_url = urljoin(base_url, request_url) if base_url else request_url
            parsed = urlparse(full_url)
            
            # Pulizia del path: togliamo slash vuoti per la lista, ma manteniamo il path stringa per il match
            path_list = [p for p in parsed.path.split('/') if p]
            
            # Trasformiamo query e fragment in dizionari puliti
            query_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
            frag_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.fragment).items()}

            url_payload = {
                'url': full_url,
                'protocol': parsed.scheme,
                'host': parsed.hostname,
                'port': parsed.port,
                'path': path_list,
                'query': query_params,
                'fragment': frag_params
            }

            # 2. Ciclo di Matching (Aggiornato per supportare la struttura nidificata {path: {metodo: config}})
            for methods_dict in risorse.values():
                # Tutte le configurazioni per lo stesso path condividono lo stesso pattern
                # ne prendiamo una qualsiasi per eseguire il match del path
                first_config = next(iter(methods_dict.values()))
                match = first_config['pattern'].match(parsed.path)
                
                if match:
                    # Trovato il path, cerchiamo se il metodo richiesto è supportato
                    route_data = methods_dict.get(request_method.upper())
                    
                    if not route_data:
                        # Metodo non trovato per questo path specifico
                        continue
                        
                    # Recuperiamo i metadati
                    metadata = route_data.get('metadata', route_data)
                    
                    # Estrazione parametri dinamici dalla Regex (es. {'id': '123'})
                    dynamic_params = match.groupdict()
                    
                    return {
                        'metadata': metadata,
                        'params': dynamic_params,
                        'url_details': url_payload
                    }

            print(f"[-] No route matched for: {request_method} {parsed.path}")
            return None

        except Exception as e:
            print(f"[!] Resolve Error: {e}")
            return None
