from typing import Any


import framework.core.flow as flow
import framework.manager.loader as loader
import framework.manager.defender as defender
import framework.port.authentication as authentication
import framework.port.manager as manager
from framework.core.session import SessionData
from framework.service.diagnostic import get_logger


class Manager(manager.Port):
    _session_exempt_methods = {
        "session_create",
        "session_get",
        "get_policy",
        "authorized",
        "resolve_route",
    }
    def __init__(self, 
            loader: loader.Loader,
            defender: defender.Manager,
            authentications: list[authentication.Port], 
            **constants
        ):
        """
        Inizializza il manager con i servizi necessari alla gestione delle richieste.

        :param loader: Carica risorse, manager e file DSL dell'applicazione.
        :param authentications: Provider usati per autenticare, registrare e
            disconnettere gli utenti.
        :param constants: Configurazioni del manager, incluse le policy da
            caricare durante l'avvio.
        """

        # Loader condiviso dal framework per leggere risorse e manager.
        self.loader = loader
        self.defender = defender

        # Configurazione ricevuta dal container, conservata per il bootstrap.
        self.config = constants

        # Provider di autenticazione utilizzati dai metodi del ciclo di vita
        # dell'utente: authenticate, activate, reinstate e terminate.
        self.authentications = authentications

        # Nomi dei controller DSL caricati durante startup().
        self.controllers = []

        # Policy caricate e valutate dall'interprete, indicizzate per nome.
        self.policies = {}
        self.logger = get_logger("authenticator")

    @flow.result(inputs=(), outputs=())
    async def shutdown(self, session):
        self.logger.info("Authenticator: arresto", providers=len(self.authentications))
        pass
    
    @flow.result(inputs=(), outputs=())
    async def startup(self, session=None):
        self.logger.info("Authenticator: avvio", providers=len(self.authentications))
        return None

    async def _authorized(self, action):
        return await self.defender.authorized("authentication", action=action)

    @staticmethod
    def _session_data(session) -> SessionData:
        snapshot = getattr(session, "session_data", session)
        if isinstance(snapshot, SessionData):
            return snapshot
        if isinstance(snapshot, dict):
            return SessionData.from_dict(snapshot)
        raise TypeError("Authenticator richiede uno snapshot SessionData")

    @staticmethod
    def _merge_authentication_result(session, authentication, session_result):
        session = Manager._session_data(session)
        if flow.is_result(session_result):
            if not flow.check(session_result):
                return session, session_result
            payload = flow.output(session_result)
        else:
            payload = session_result

        if not isinstance(payload, dict):
            return session, flow.error("Authentication provider returned an invalid payload")

        providers = payload.get('providers', {})
        user = payload.get('user')
        provider = providers.get(authentication.name)
        if not isinstance(provider, dict) or not isinstance(user, dict):
            return session, flow.error("Authentication provider returned incomplete identity data")

        authentication_data = session["authentication"].copy()
        current_providers = authentication_data.get("providers", {}).copy()
        current_providers[authentication.name] = provider
        authentication_data["providers"] = current_providers
        authentication_data["user"] = authentication_data.get("user", {}) | user
        return session.evolve(authentication=authentication_data), None
    
    @flow.result(inputs=('session',), outputs=())
    async def invalidate(self, session, **constants) -> bool:
        """
        Invalida la sessione di un utente specificato.

        :param constants: Deve includere 'identifier'.
        :return: True se la sessione è stata terminata, False se l'utente non esiste.
        """

        if not await self._authorized("sign_out"):
            self.logger.warning("Authenticator: invalidazione negata dalla policy")
            return flow.error("Authentication policy denied sign_out")
        snapshot = self._session_data(session)
        authentication_data = snapshot["authentication"].copy()
        for authentication in self.authentications:
            session_result = await authentication.sign_out(authentication_data.copy())
            if flow.is_result(session_result) and not flow.check(session_result):
                self.logger.warning(
                    "Authenticator: invalidazione provider fallita",
                    provider=type(authentication).__name__,
                    error=flow.output(session_result),
                )
                return session_result

        authentication_data.pop('providers', None)
        authentication_data.pop('user', None)
        snapshot = snapshot.evolve(authentication=authentication_data)

        self.logger.debug("Authenticator: invalidazione completata")
        return flow.success(snapshot)

    @flow.result(inputs=('session',), outputs=('session',))
    async def regenerate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        snapshot = self._session_data(session)
        if not await self._authorized("sign_aid"):
            self.logger.warning("Authenticator: rigenerazione negata dalla policy")
            return flow.error("Authentication policy denied sign_aid")
        for authentication in self.authentications:
            session_result = await authentication.sign_aid(**constants)
            snapshot, merge_error = self._merge_authentication_result(
                snapshot, authentication, session_result
            )
            if merge_error:
                self.logger.warning(
                    "Authenticator: rigenerazione provider fallita",
                    provider=type(authentication).__name__,
                )
                return merge_error
        self.logger.debug("Authenticator: rigenerazione completata")
        return flow.success(snapshot)

    @flow.result(inputs=('session',), outputs=('session',))
    async def authenticate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        snapshot = self._session_data(session)
        if not await self._authorized("sign_in"):
            self.logger.warning("Authenticator: autenticazione negata dalla policy")
            return flow.error("Authentication policy denied sign_in")
        for authentication in self.authentications:
            session_result = await authentication.sign_in(**constants)
            snapshot, merge_error = self._merge_authentication_result(
                snapshot, authentication, session_result
            )
            if merge_error:
                self.logger.warning(
                    "Authenticator: autenticazione provider fallita",
                    provider=type(authentication).__name__,
                )
                return merge_error
        self.logger.debug("Authenticator: autenticazione completata")
        return flow.success(snapshot)


    @flow.result(inputs=('session',), outputs=('session',))
    async def activate(self, session, **constants) -> Any:
        """
        Registra un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se la registrazione ha successo, altrimenti None.
        """
        snapshot = self._session_data(session)
        if not await self._authorized("sign_up"):
            self.logger.warning("Authenticator: attivazione negata dalla policy")
            return flow.error("Authentication policy denied sign_up")
        for authentication in self.authentications:
            session_result = await authentication.sign_up(**constants)
            snapshot, merge_error = self._merge_authentication_result(
                snapshot, authentication, session_result
            )
            if merge_error:
                self.logger.warning(
                    "Authenticator: attivazione provider fallita",
                    provider=type(authentication).__name__,
                )
                return merge_error
        self.logger.debug("Authenticator: attivazione completata")
        return flow.success(snapshot)