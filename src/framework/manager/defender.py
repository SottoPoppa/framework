from secrets import token_urlsafe
import framework.service.language as language
import framework.service.scheme as scheme
import framework.service.flow as flow
import framework.manager.loader as loader
import framework.manager.authenticator as authenticator
import framework.port.manager as manager
from returns.result import Success

class Manager(manager.Port):
    _session_exempt_methods = {
        "session_create",
        "session_get",
        "get_policy",
        "authorized",
        "resolve_route",
    }
    def __init__(self, loader: loader.Loader, authenticator:authenticator.Manager, **configuration):
        """
        Inizializza il manager con i servizi necessari alla gestione delle richieste.

        :param loader: Carica risorse, manager e file DSL dell'applicazione.
        :param authenticator: Provider usato per autenticare, registrare e
            disconnettere gli utenti.
        :param configuration: Configurazioni del manager, incluse le policy da
            caricare durante l'avvio.
        """

        # Interpreta i file DSL e gestisce le sessioni dell'interprete.
        self.interpreter = language.Interpreter(scheme.schemes)

        # Loader condiviso dal framework per leggere risorse e manager.
        self.loader = loader

        # Configurazione ricevuta dal container, conservata per il bootstrap.
        self.config = configuration

        # Provider di autenticazione utilizzati dai metodi del ciclo di vita
        # dell'utente: authenticate, activate, reinstate e terminate.
        self.authenticator = authenticator

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
            if not isinstance(session_result, Success):
                return session_result
            async with session_result.unwrap() as session:
                run_result = await session.run(path)
                if not isinstance(run_result, Success):
                    return run_result
                self.policies[policy] = run_result.unwrap()
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
    async def session_create(self, env=None, **session):
        env = env or {}
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