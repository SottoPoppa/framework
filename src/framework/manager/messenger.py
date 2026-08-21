import asyncio

import framework.port.message as message
import framework.port.manager as manager
import framework.service.flow as flow

from framework.manager.defender import Manager as Defender


class Manager(manager.Port):
    def __init__(
        self,
        messages: list[message.Port],
        defender: Defender,
        **constants,
    ):
        self.defender = defender
        self.providers = messages

    @staticmethod
    def _split_domain(domain: str | None) -> tuple[str | None, str | None]:
        """
        Spezza 'controller:domain' in (controller, domain).

        Se non c'è ':' ritorna (None, domain).
        """
        if domain and ':' in domain:
            controller, domain = domain.split(':', 1)
            return controller, domain

        return None, domain

    def _matching_providers(self, controller: str | None) -> list:
        """
        Ritorna i provider che corrispondono al controller.

        Se controller è None, ritorna tutti i provider.
        """
        if controller is None:
            return list(self.providers)

        return [
            provider
            for provider in self.providers
            if (
                provider.config.get('name') == controller
                or provider.adapter == controller
            )
        ]

    async def _dispatch(
        self,
        session,
        controller: str | None,
        domain: str | None,
        **constants,
    ):
        """
        Instrada il messaggio verso i provider/controller appropriati.
        """
        matched = self._matching_providers(controller)

        message_text = constants.get('message')

        if controller and not matched:
            if controller in self.defender.controllers:
                await session.emit(controller, domain, message_text)

            return

        for provider in matched:
            await provider.post(**constants | {'domain': domain})

    @flow.result(inputs='messenger')
    async def send(self, session, **constants):
        """
        Invia un messaggio.

        Il routing effettivo viene delegato a _dispatch().
        """
        controller, domain = self._split_domain(constants.get('domain'))
        dispatch_constants = {
            key: value
            for key, value in constants.items()
            if key != 'domain'
        }

        await self._dispatch(session, controller, domain, **dispatch_constants)

    @flow.result()
    async def receive(self, session, **constants):
        """
        Riceve il primo risultato disponibile dai provider.
        """
        controller, domain = self._split_domain(constants.get('domain'))

        matched = self._matching_providers(controller)

        if controller and not matched:
            if controller in self.defender.controllers:
                # TODO: definire come ricevere dal defender
                return None

            return None

        tasks = [
            asyncio.create_task(provider.read(session, **constants | {'domain': domain}))
            for provider in matched
        ]

        if not tasks:
            return None

        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            result = done.pop().result()

            for task in pending:
                task.cancel()

                try:
                    await task
                except asyncio.CancelledError:
                    pass

            return result

        except Exception as e:
            print(f"[Messenger] Errore nel loop di ricezione: {e}")
            return None