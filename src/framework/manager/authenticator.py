from typing import Any


import framework.core.flow as flow
import framework.manager.loader as loader
import framework.manager.defender as defender
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
    def __init__(self, 
            loader: loader.Loader,
            defender: defender.Manager,
            authentications: list[authentication.Port], 
            **configuration
        ):
        """
        Inizializza il manager con i servizi necessari alla gestione delle richieste.

        :param loader: Carica risorse, manager e file DSL dell'applicazione.
        :param authentications: Provider usati per autenticare, registrare e
            disconnettere gli utenti.
        :param configuration: Configurazioni del manager, incluse le policy da
            caricare durante l'avvio.
        """

        # Loader condiviso dal framework per leggere risorse e manager.
        self.loader = loader
        self.defender = defender

        # Configurazione ricevuta dal container, conservata per il bootstrap.
        self.config = configuration

        # Provider di autenticazione utilizzati dai metodi del ciclo di vita
        # dell'utente: authenticate, activate, reinstate e terminate.
        self.authentications = authentications

        # Nomi dei controller DSL caricati durante startup().
        self.controllers = []

        # Policy caricate e valutate dall'interprete, indicizzate per nome.
        self.policies = {}

    @flow.result()
    async def shutdown(self, session):
        pass
    
    @flow.result()
    async def startup(self, session=None):
        return None

    def _authorized(self, action):
        return self.defender.authorized("authentication", action=action)

    @staticmethod
    def _merge_authentication_result(session, authentication, session_result):
        if not session_result.get('success'):
            return session_result

        payload = flow.output(session_result)
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
    
    @flow.result(outputs=('session',))
    async def invalidate(self, session, **constants) -> bool:
        """
        Invalida la sessione di un utente specificato.

        :param constants: Deve includere 'identifier'.
        :return: True se la sessione è stata terminata, False se l'utente non esiste.
        """

        if not self._authorized("sign_out"):
            return flow.error("Authentication policy denied sign_out")
        for authentication in self.authentications:
            session_result = await authentication.sign_out(session)
            if not session_result.get('success'):
                return session_result

        session.pop('providers', None)
        session.pop('user', None)

        return flow.success(session)

    @flow.result(outputs=('session',))
    async def regenerate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        if not self._authorized("sign_aid"):
            return flow.error("Authentication policy denied sign_aid")
        for authentication in self.authentications:
            session_result = await authentication.sign_aid(**constants)
            merge_error = self._merge_authentication_result(session, authentication, session_result)
            if merge_error:
                return merge_error
        return flow.success(session)

    @flow.result(inputs=('session',))
    async def authenticate(self, session, **constants):
        """
        Autentica un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se l'autenticazione ha successo, altrimenti None.
        """
        if not self._authorized("sign_in"):
            return flow.error("Authentication policy denied sign_in")
        for authentication in self.authentications:
            session_result = await authentication.sign_in(**constants)
            merge_error = self._merge_authentication_result(session, authentication, session_result)
            if merge_error:
                return merge_error
        return flow.success(session)


    @flow.result(outputs=('session',))
    async def activate(self, session, **constants) -> Any:
        """
        Registra un utente utilizzando i provider configurati.

        :param constants: Deve includere 'identifier', 'ip' e credenziali.
        :return: Dizionario di sessione aggiornato se la registrazione ha successo, altrimenti None.
        """
        if not self._authorized("sign_up"):
            return flow.error("Authentication policy denied sign_up")
        for authentication in self.authentications:
            session_result = await authentication.sign_up(**constants)
            merge_error = self._merge_authentication_result(session, authentication, session_result)
            if merge_error:
                return merge_error
        return flow.success(session)