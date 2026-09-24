from typing import Any


import framework.core.flow as flow
import framework.manager.loader as loader
import framework.manager.defender as defender
import framework.port.authentication as authentication
import framework.port.manager as manager
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
    def _authentication_data(session):
        user_session = getattr(session, "user_session", session)
        authentication = getattr(user_session, "authentication", None)
        return authentication if isinstance(authentication, dict) else user_session

    @staticmethod
    def _merge_authentication_result(session, authentication, session_result):
        session = Manager._authentication_data(session)
        if flow.is_result(session_result):
            if not flow.check(session_result):
                return session_result
            payload = flow.output(session_result)
        else:
            payload = session_result

        if not isinstance(payload, dict):
            return flow.error("Authentication provider returned an invalid payload")

        providers = payload.get('providers', {})
        user = payload.get('user')
        provider = providers.get(authentication.name)
        if not isinstance(provider, dict) or not isinstance(user, dict):
            return flow.error("Authentication provider returned incomplete identity data")

        session.setdefault('providers', {})
        session.setdefault('user', {})
        session['providers'][authentication.name] = provider
        session['user'] |= user
        return None
    
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
        session_data = self._authentication_data(session)
        for authentication in self.authentications:
            session_result = await authentication.sign_out(session_data)
            if flow.is_result(session_result) and not flow.check(session_result):
                self.logger.warning(
                    "Authenticator: invalidazione provider fallita",
                    provider=type(authentication).__name__,
                    error=flow.output(session_result),
                )
                return session_result

        session_data.pop('providers', None)
        session_data.pop('user', None)

        self.logger.debug("Authenticator: invalidazione completata")
        return flow.success(session_data)

    @flow.result(inputs=('session',), outputs=('session',))
    async def regenerate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        session_data = self._authentication_data(session)
        if not await self._authorized("sign_aid"):
            self.logger.warning("Authenticator: rigenerazione negata dalla policy")
            return flow.error("Authentication policy denied sign_aid")
        for authentication in self.authentications:
            session_result = await authentication.sign_aid(**constants)
            merge_error = self._merge_authentication_result(session_data, authentication, session_result)
            if merge_error:
                self.logger.warning(
                    "Authenticator: rigenerazione provider fallita",
                    provider=type(authentication).__name__,
                )
                return merge_error
        self.logger.debug("Authenticator: rigenerazione completata")
        return flow.success(session_data)

    @flow.result(inputs=('session',), outputs=('session',))
    async def authenticate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        session_data = self._authentication_data(session)
        if not await self._authorized("sign_in"):
            self.logger.warning("Authenticator: autenticazione negata dalla policy")
            return flow.error("Authentication policy denied sign_in")
        for authentication in self.authentications:
            session_result = await authentication.sign_in(**constants)
            merge_error = self._merge_authentication_result(session_data, authentication, session_result)
            if merge_error:
                self.logger.warning(
                    "Authenticator: autenticazione provider fallita",
                    provider=type(authentication).__name__,
                )
                return merge_error
        self.logger.debug("Authenticator: autenticazione completata")
        return flow.success(session_data)


    @flow.result(inputs=('session',), outputs=('session',))
    async def activate(self, session, **constants) -> Any:
        """
        Registra un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se la registrazione ha successo, altrimenti None.
        """
        session_data = self._authentication_data(session)
        if not await self._authorized("sign_up"):
            self.logger.warning("Authenticator: attivazione negata dalla policy")
            return flow.error("Authentication policy denied sign_up")
        for authentication in self.authentications:
            session_result = await authentication.sign_up(**constants)
            merge_error = self._merge_authentication_result(session_data, authentication, session_result)
            if merge_error:
                self.logger.warning(
                    "Authenticator: attivazione provider fallita",
                    provider=type(authentication).__name__,
                )
                return merge_error
        self.logger.debug("Authenticator: attivazione completata")
        return flow.success(session_data)