import inspect
from secrets import token_urlsafe
from typing import Dict, Any
from urllib.parse import urlparse, parse_qs, urljoin


import framework.core.interpreter as interpreter
import framework.core.model as model
import framework.service.scheme as scheme
import framework.core.flow as flow
import framework.manager.loader as loader
import framework.core.framework as framework_module
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
    def __init__(
        self,
        loader: loader.Loader,
        framework: framework_module.Framework,
        authentications: list[authentication.Port],
        **constants,
    ):
        """
        Inizializza il manager con i servizi necessari alla gestione delle richieste.

        :param loader: Carica risorse, manager e file DSL dell'applicazione.
        :param authentications: Provider usati per autenticare, registrare e
            disconnettere gli utenti.
        :param constants: Configurazioni del manager, incluse le policy da
            caricare durante l'avvio.
        """

        # Interpreta i file DSL e gestisce le sessioni dell'interprete.
        self.interpreter = interpreter.Interpreter(scheme.schemes)
        self.framework = framework

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
        self.port_adapters = {}

    def _register_capabilities(self, session, port, capabilities, adapter=None):
        """Registra capability e istanza concreta di un adapter per una Port."""
        profiles = self.port_capabilities.setdefault(port, [])
        normalized = dict(capabilities)
        if normalized not in profiles:
            profiles.append(normalized)
        if adapter is not None:
            adapters = self.port_adapters.setdefault(port, [])
            if adapter not in adapters:
                adapters.append(adapter)
        return True

    def compatible_adapters(self, session, port, requirements, adapters=None):
        """Restituisce gli adapter le cui capability soddisfano i requisiti tecnici."""
        candidates = self.port_adapters.get(port, []) if adapters is None else adapters
        return [
            adapter for adapter in candidates
            if self._profile_satisfies(requirements, getattr(adapter, "capabilities", adapter))
        ]

    def authorized_adapters(self, session, port, policy, adapters=None):
        """Seleziona gli adapter compatibili con la sezione security di una policy."""
        if not isinstance(policy, dict):
            return []
        security = policy.get("security", {})
        return self.compatible_adapters(session, port, security, adapters)

    def capabilities_authorized(self, session, policy, port=None, profile=None) -> bool:
        """Verifica che almeno un profilo adapter soddisfi la sicurezza della policy."""
        if not isinstance(policy, dict):
            return False
        requirements = policy.get("security", {})
        if not requirements:
            return True
        profiles = profile
        if profiles is None:
            profiles = self.port_capabilities.get(port, [])
        if isinstance(profiles, dict):
            profiles = (profiles,)
        return bool(profiles) and any(
            self._profile_satisfies(
                requirements, getattr(candidate, "capabilities", candidate)
            )
            for candidate in profiles
        )

    def _profile_satisfies(self, requirements: dict, profile: dict) -> bool:
        """Confronta un profilo adapter con i requisiti tecnici richiesti."""
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

    @flow.result(inputs=(), outputs=())
    async def shutdown(self, session):
        """Arresta l'interprete DSL e chiude il ciclo di vita del Defender."""
        await self.interpreter.stop()
    
    @flow.result(inputs=(), outputs=())
    async def startup(self, session=None):
        """Avvia l'interprete e carica policy e controller applicativi."""
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
            code_result = await self.loader.resource(path)
            if flow.is_result(code_result) and not flow.check(code_result):
                self.framework.logger.error(
                    "Caricamento policy fallito",
                    policy=policy,
                    error=flow.output(code_result),
                )
                return code_result
            code = flow.output(code_result)
            load_result = await self.interpreter.load_file(path, code)
            if flow.is_result(load_result) and not flow.check(load_result):
                self.framework.logger.error(
                    "Compilazione policy fallita",
                    policy=policy,
                    error=flow.output(load_result),
                )
                return load_result
            session_result = await self.session_create()
            if flow.is_result(session_result) and not flow.check(session_result):
                self.framework.logger.error(
                    "Creazione sessione policy fallita",
                    policy=policy,
                    error=flow.output(session_result),
                )
                return session_result
            policy_session = flow.output(session_result)
            async with policy_session:
                run_result = await policy_session.run(path)
                if flow.is_result(run_result) and not flow.check(run_result):
                    self.framework.logger.error(
                        "Esecuzione policy fallita",
                        policy=policy,
                        error=flow.output(run_result),
                    )
                    return run_result
                policy_data = flow.output(run_result)
            validation = self._validate_policy(policy, policy_data)
            if not validation.is_success:
                return validation
            validated_policy = validation.output.value
            self.policies[policy] = validated_policy
            self.port_configurations[policy] = validated_policy["configuration"]
            self.framework.logger.info("Policy caricata", policy=f"{policy}/{filename}")

        from pathlib import Path

        controllers_path = Path("src/application/controller")
        for file in controllers_path.glob("*.dsl"):
            code_result = await self.loader.resource(file)
            if flow.is_result(code_result) and not flow.check(code_result):
                self.framework.logger.error(
                    "Caricamento controller fallito",
                    controller=file.stem,
                    error=flow.output(code_result),
                )
                return code_result
            code = flow.output(code_result)
            controller_name = file.stem
            load_result = await self.interpreter.load_file(controller_name, code)
            if flow.is_result(load_result) and not flow.check(load_result):
                self.framework.logger.error(
                    "Compilazione controller fallita",
                    controller=controller_name,
                    error=flow.output(load_result),
                )
                return load_result
            self.controllers.append(controller_name)
        
        self.framework.logger.info("Controller caricati", controllers=self.controllers)

    def _validate_policy(self, port, policy):
        """Valida configurazione, schema e capability della policy di una Port."""
        if not isinstance(policy, dict):
            return flow.error(f"Policy '{port}' non valida: il risultato DSL non è un dizionario")
        policy = dict(policy)
        configuration = policy.get("configuration") or policy.get(f"{port}:configuration") or (policy.get(port, {}).get("configuration") if isinstance(policy.get(port), dict) else None)
        if configuration is None:
            return flow.error(f"Configurazione globale mancante per la Port '{port}'")
        schema = scheme.schemes.get(port)
        if not schema:
            return flow.error(f"Schema '{port}' non trovato per la policy '{port}'")
        normalized = scheme.normalize(configuration, schema)
        if not normalized.is_success:
            return flow.error(f"Configurazione policy '{port}' non valida: {normalized.output.error}")
        policy["configuration"] = normalized.output.value
        return flow.success(policy)

    @flow.result(inputs=(), outputs=())
    async def session_create(self, env=None, **session):
        """Crea una sessione DSL con un identificatore univoco e l'ambiente runtime."""
        env = env or {}
        env = env | {**self.managers}
        if not session.get("id"):
            session["id"] = token_urlsafe(16)
        authentication = {
            key: value for key, value in session.items() if key != "id"
        }
        return self.interpreter.open_session(
            env=env,
            sid=session["id"],
            authentication=authentication,
        )

    def session_get(self, sid):
        """Restituisce l'handle runtime dato un id o uno snapshot sessione."""
        session_data = getattr(sid, "session_data", sid)
        sid = session_data.get("id") if isinstance(session_data, dict) else getattr(
            session_data, "id", session_data
        )
        if sid not in self.interpreter.session_data:
            return None
        return self.interpreter.open_session(sid=sid)
    
    def get_policy(self, policy):
        """Restituisce la policy caricata con il nome indicato."""
        return self.policies.get(policy)

    def get_configuration(self, port):
        """Restituisce la configurazione globale validata di una Port."""
        return self.port_configurations.get(port)

    @staticmethod
    def _policy_session(session):
        session_data = getattr(session, "session_data", session)
        if not isinstance(session_data, dict):
            return session
        snapshot = (
            session_data.to_dict()
            if callable(getattr(session_data, "to_dict", None))
            else dict(session_data)
        )
        authentication = snapshot.get("authentication", {})
        return {
            **authentication,
            **snapshot,
            "id": snapshot.get("id"),
            "authentication": authentication,
        }

    async def authorized(self, policy, **constants) -> bool:
        """Valuta le regole DSL di una policy per azione, risorsa, posizione e sessione."""
        policy_name = policy
        policy = self.get_policy(policy_name)
        if not policy:
            return False
        if not self.capabilities_authorized(None, policy, policy_name, self.port_capabilities.get(policy_name)):
            return False
        rules = policy.get('rules', {})
        action, resource, location = constants.get('action', ''), constants.get('resource', ''), constants.get('location', '')
        runtime_session = constants.get("session")
        policy_session = self._policy_session(runtime_session)
        target = {
            'action': action,
            'resource': resource,
            'location': location,
            'session': policy_session,
            'request': constants.get('request', {}),
        }
        filted_rules = []
        if location in rules:
            filted_rules = rules.get(location)
        elif resource in rules:
            filted_rules = rules.get(resource)
        elif action in rules:
            filted_rules = rules.get(action)
        else:
            pass

        denied = False
        allowed = False
        for rule in filted_rules:
            for_target = rule.get('target', {}) | target
            condition = model.decode(rule.get('condition'))
            if callable(condition):
                tes = condition(**for_target)
                if inspect.isawaitable(tes):
                    tes = await tes
            elif isinstance(condition, bool):
                tes = condition
            elif isinstance(
                condition,
                (model.Call, model.Deferred, model.ExecutionSpec, model.Literal, model.Ref),
            ):
                tes = await self.interpreter.evaluate(
                    condition,
                    for_target,
                    session=runtime_session,
                )
            else:
                continue

            if rule.get('effect') == 'allow':
                allowed = allowed or bool(tes)
            elif rule.get('effect') == 'deny':
                denied = denied or bool(tes)
        return allowed and not denied