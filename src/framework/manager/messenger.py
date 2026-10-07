import asyncio
from collections.abc import Mapping
from typing import Any

import framework.core.interpreter as interpreter
import framework.port.message as message
import framework.port.manager as manager
import framework.core.flow as flow
import framework.core.framework as framework_module
from framework.core.session import SessionData
from framework.service.diagnostic import get_logger

from framework.manager.defender import Manager as Defender


class Manager(manager.Port):
    def __init__(
        self,
        messages: list[message.Port],
        defender: Defender | None,
        framework: framework_module.Framework | None,
        **constants: Any,
    ) -> None:
        self.defender = defender
        self.providers = messages
        self.framework = framework
        self.logger = (
            framework.get_logger("messenger")
            if framework is not None and hasattr(framework, "get_logger")
            else get_logger("messenger")
        )

    def _matching_providers(
        self,
        receiver: str | None,
        adapter: str | None = None,
    ) -> list[message.Port]:
        """
        Ritorna i provider che corrispondono al destinatario.

        Se receiver è None, ritorna tutti i provider.
        """
        if receiver is None:
            return list(self.providers)

        return [
            provider
            for provider in self.providers
            if (
                (provider.config.get('name') == receiver
                    or provider.adapter == receiver)
                and (adapter is None or provider.adapter == adapter)
            )
        ]

    async def _authorized_provider(
        self,
        session: interpreter.SessionHandle | SessionData | Mapping[str, Any] | str,
        action: str,
        provider: message.Port,
        destination: str | None,
        constants: dict[str, Any],
    ) -> bool:
        if self.defender is None:
            return True
        provider_name = provider.config.get("name") or provider.adapter
        request = dict(constants)
        request.update({
            "adapter": provider.adapter,
            "provider": provider_name,
            "receiver": destination,
        })
        return await self.defender.authorized(
            session,
            "message",
            action=action,
            request=request,
        )

    async def _dispatch(
        self,
        session: interpreter.SessionHandle | SessionData | Mapping[str, Any] | str,
        domain: str | None,
        **constants: Any,
    ) -> flow.FlowResult:
        """
        Instrada il messaggio verso i provider/controller appropriati.
        """
        session = self._as_session_data(session)
        destination = constants.get("receiver")
        adapter = constants.get("adapter")

        if adapter == "dsl":
            if not destination or not self.defender or destination not in self.defender.controllers:
                self.logger.warning(
                    "Messenger: controller DSL non trovato",
                    receiver=destination,
                    domain=domain,
                )
                return flow.error("Controller DSL non trovato")
            if not domain:
                self.logger.warning(
                    "Messenger: nodo controller DSL non specificato",
                    receiver=destination,
                )
                return flow.error("Nodo controller DSL non specificato")
            request = dict(constants)
            request.update({"adapter": "dsl", "provider": "dsl", "receiver": destination})
            if not await self.defender.authorized(
                session, "message", action="publish", request=request
            ):
                self.logger.warning(
                    "Messenger: pubblicazione DSL non autorizzata",
                    receiver=destination,
                    domain=domain,
                )
                return flow.error("Messaggio DSL non autorizzato")
            runtime = self.defender.session_get(session)
            if runtime is None:
                self.logger.warning(
                    "Messenger: sessione runtime non trovata",
                    receiver=destination,
                    domain=domain,
                    session_id=(
                        session.get("id") if isinstance(session, Mapping) else session
                    ),
                )
                return flow.error("Sessione runtime non trovata")
            result = await runtime.dispatch_controller_event(
                destination,
                domain,
                constants.get("message"),
            )
            if flow.is_result(result) and not flow.check(result):
                self.logger.error(
                    "Messenger: pubblicazione DSL fallita",
                    receiver=destination,
                    domain=domain,
                    error=flow.output(result),
                )
                return result
            self.logger.debug(
                "Messenger: pubblicazione DSL completata",
                receiver=destination,
                domain=domain,
            )
            return flow.success(result)

        matched = self._matching_providers(destination, adapter)
        if not matched:
            self.logger.warning(
                "Messenger: nessun provider trovato",
                receiver=destination,
                requested_adapter=adapter,
            )
            return flow.error("Nessun provider di messaggistica trovato")

        failure = None
        authorized_count = 0
        for provider in matched:
            provider_name = provider.config.get("name") or provider.adapter
            authorized = await self._authorized_provider(
                session, "publish", provider, destination, constants
            )
            if not authorized:
                self.logger.warning(
                    "Messenger: provider non autorizzato",
                    provider=provider_name,
                    receiver=destination,
                    domain=domain,
                )
                continue

            authorized_count += 1
            try:
                result = await provider.post(session, **constants | {'domain': domain})
            except Exception as exc:
                self.logger.error(
                    "Messenger: eccezione durante l'invio al provider",
                    provider=provider_name,
                    receiver=destination,
                    domain=domain,
                    exception=exc,
                )
                if failure is None:
                    failure = flow.error(exc)
                continue

            if flow.is_result(result) and not flow.check(result):
                self.logger.error(
                    "Messenger: invio al provider fallito",
                    provider=provider_name,
                    receiver=destination,
                    domain=domain,
                    error=flow.output(result),
                )
                if failure is None:
                    failure = result
            else:
                self.logger.debug(
                    "Messenger: invio al provider completato",
                    provider=provider_name,
                    receiver=destination,
                    domain=domain,
                )
        if authorized_count == 0:
            return flow.error("Nessun provider di messaggistica autorizzato")
        return failure or flow.success()

    @staticmethod
    def _as_session_data(
        session: interpreter.SessionHandle | SessionData | Mapping[str, Any] | str,
    ) -> SessionData | Mapping[str, Any] | str:
        """Estrae lo snapshot puro dagli handle runtime legacy."""
        return (
            session.session_data
            if isinstance(session, interpreter.SessionHandle)
            else session
        )

    @flow.result(inputs=('messenger',), outputs=())
    async def send(
        self,
        session: interpreter.SessionHandle | SessionData | Mapping[str, Any] | str,
        **constants: Any,
    ) -> flow.FlowResult:
        """
        Invia un messaggio.

        Il routing effettivo viene delegato a _dispatch().
        """
        dispatch_constants = {
            key: value
            for key, value in constants.items()
            if key != "domain"
        }
        return await self._dispatch(
            session,
            constants.get('domain'),
            **dispatch_constants,
        )

    @flow.result(inputs=(), outputs=())
    async def receive(
        self,
        session: interpreter.SessionHandle | SessionData | Mapping[str, Any] | str,
        **constants: Any,
    ) -> flow.FlowResult:
        """
        Riceve il primo risultato disponibile dai provider.
        """
        session = self._as_session_data(session)
        domain = constants.get("domain")
        destination = constants.get("receiver")
        matched = self._matching_providers(destination)
        if destination and not matched:
            self.logger.warning(
                "Messenger: nessun provider disponibile per la ricezione",
                receiver=destination,
                domain=domain,
            )
            return flow.error("Nessun provider di messaggistica disponibile per la ricezione")

        authorized: list[message.Port] = []
        for provider in matched:
            provider_name = provider.config.get("name") or provider.adapter
            if await self._authorized_provider(
                session, "subscribe", provider, destination, constants
            ):
                authorized.append(provider)
                continue
            self.logger.warning(
                "Messenger: sottoscrizione al provider non autorizzata",
                provider=provider_name,
                receiver=destination,
                domain=domain,
            )

        tasks: list[asyncio.Future[flow.FlowResult]] = [
            asyncio.ensure_future(
                provider.read(session, **constants | {'domain': domain})
            )
            for provider in authorized
        ]

        if not tasks:
            self.logger.warning(
                "Messenger: nessun provider autorizzato per la ricezione",
                receiver=destination,
                domain=domain,
            )
            return flow.error(
                "Nessun provider di messaggistica autorizzato per la ricezione"
            )

        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            results: list[flow.FlowResult] = []
            errors: list[Exception] = []
            for task in tasks:
                if task not in done:
                    continue
                try:
                    results.append(task.result())
                except asyncio.CancelledError:
                    continue
                except Exception as exc:
                    errors.append(exc)
                    self.logger.error(
                        "Messenger: provider in ricezione terminato con eccezione",
                        receiver=destination,
                        domain=domain,
                        exception=exc,
                    )

            failures = [
                result for result in results
                if flow.is_result(result) and not flow.check(result)
            ]
            for result in failures:
                self.logger.error(
                    "Messenger: provider in ricezione fallito",
                    receiver=destination,
                    domain=domain,
                    error=flow.output(result),
                )
            successful: list[flow.FlowResult] = [
                result for result in results if result not in failures
            ]

            message_results: list[flow.FlowResult] = [
                result
                for result in successful
                if (flow.output(result) if flow.is_result(result) else result) is not None
            ]
            if message_results:
                self.logger.debug(
                    "Messenger: ricezione completata",
                    receiver=destination,
                    domain=domain,
                )
                return message_results[0]
            if successful:
                self.logger.error(
                    "Messenger: provider ha completato la ricezione senza un messaggio",
                    receiver=destination,
                    domain=domain,
                )
                return flow.error(
                    "Il provider di messaggistica ha terminato la lettura senza un messaggio"
                )
            if failures:
                return failures[0]
            if errors:
                return flow.error(errors[0])
            return flow.error("Nessun messaggio ricevuto dai provider")

        except Exception as exc:
            self.logger.error("Errore nel loop di ricezione", exception=exc)
            return flow.error(exc)
        finally:
            pending = [task for task in tasks if not task.done()]
            for task in pending:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)