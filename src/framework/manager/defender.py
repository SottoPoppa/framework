from secrets import token_urlsafe
from typing import Dict, Any
from urllib.parse import urlparse, parse_qs, urljoin


import framework.core.language as language
import framework.core.scheme as scheme
import framework.core.flow as flow
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
        "get_configuration",
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
        self.port_configurations = {}
        self.port_capabilities = {}

    def _register_capabilities(self, session, port, capabilities):
        profiles = self.port_capabilities.setdefault(port, [])
        normalized = dict(capabilities)
        if normalized not in profiles:
            profiles.append(normalized)
        return True

    def security_authorized(self, session, policy, profile=None) -> bool:
        requirements = policy.get("security", {}) if isinstance(policy, dict) else {}
        if not requirements:
            return True
        profiles = profile
        if profiles is None:
            profiles = self.port_capabilities.get(policy.get("port_schema"), [])
        if isinstance(profiles, dict):
            profiles = (profiles,)
        return bool(profiles) and all(
            self._profile_satisfies(requirements, candidate)
            for candidate in profiles
        )

    def _profile_satisfies(self, requirements: dict, profile: dict) -> bool:
        if requirements.get("tls") is True and profile.get("tls") is not True:
            return False
        versions = {"TLSv1.2": 2, "TLSv1.3": 3}
        required_version = requirements.get("min_tls_version")
        if required_version and versions.get(profile.get("min_tls_version"), 0) < versions.get(required_version, 99):
            return False
        for key, required in requirements.items():
            if isinstance(required, bool) and required and profile.get(key) is not True:
                return False
        required_authentication = requirements.get("required_authentication")
        return not required_authentication or required_authentication in profile.get("authentication", [])

    @flow.result()
    async def shutdown(self, session):
        await self.interpreter.stop()
    
    @flow.result()
    async def startup(self, session=None):
        if session is not None:
            return None
        self.managers = self.loader.get_managers()
        await self.interpreter.start()
        policy_managers = {
            "presentation": "presenter",
            "authentication": "authenticator",
            "persistence": "storekeeper",
            "message": "messenger",
        }
        manager_config = self.loader.current_config.get("manager", {})
        for policy, manager_name in policy_managers.items():
            config = manager_config.get(manager_name, {})
            filename = config.get(policy) if isinstance(config, dict) else None
            if not filename:
                continue
            path = f"src/application/policy/{policy}/{filename}"
            code = await self.loader.resource(path)
            await self.interpreter.load_file(path, code)
            #await self.load_file(name, source)
            session_result = await self.session_create()
            async with flow.output(session_result) as session:
                run_result = await session.run(path)
                policy_data = flow.output(run_result)
            validation = self._validate_policy(policy, policy_data)
            if not validation.is_success:
                return validation
            validated_policy = validation.output.value
            self.policies[policy] = validated_policy
            self.port_configurations[policy] = validated_policy["configuration"]
            print(f"[+] Policy: {policy}/{filename}")

        from pathlib import Path

        controllers_path = Path("src/application/controller")
        for file in controllers_path.glob("*.dsl"):
            code = await self.loader.resource(file)
            controller_name = file.stem
            self.controllers.append(controller_name)
            await self.interpreter.load_file(controller_name, code)
        
        print("[+] Controllers: ",self.controllers)

    def _validate_policy(self, port, policy):
        if not isinstance(policy, dict):
            return flow.error(f"Policy '{port}' non valida: il risultato DSL non è un dizionario")
        policy = dict(policy)
        schema_name = policy.get("port_schema", port)
        configuration = policy.get("configuration")
        if configuration is None:
            return flow.error(f"Configurazione globale mancante per la Port '{port}'")
        schema = scheme.schemes.get(schema_name)
        if not schema:
            return flow.error(f"Schema '{schema_name}' non trovato per la policy '{port}'")
        normalized = scheme.normalize(configuration, schema)
        if not normalized.is_success:
            return flow.error(f"Configurazione policy '{port}' non valida: {normalized.output.error}")
        policy["configuration"] = normalized.output.value
        if not self.security_authorized(None, policy, self.port_capabilities.get(port)):
            return flow.error(f"Adapter della Port '{port}' non soddisfa i requisiti di sicurezza")
        return flow.success(policy)

    @flow.result()
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

    def get_configuration(self, port):
        """Restituisce la configurazione globale validata di una Port."""
        return self.port_configurations.get(port)

    def authorized(self, policy, **constants) -> bool:
        policy_name = policy
        policy = self.get_policy(policy_name)
        if not policy:
            return False
        if not self.security_authorized(None, policy, self.port_capabilities.get(policy_name)):
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