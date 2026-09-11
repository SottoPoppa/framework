import asyncio

import framework.port.message as message
import framework.port.manager as manager
import framework.core.flow as flow

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

    def _matching_providers(self, receiver: str | None, adapter: str | None = None) -> list:
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
                (receiver is None
                    or provider.config.get('name') == receiver
                    or provider.adapter == receiver)
                and (adapter is None or provider.adapter == adapter)
            )
        ]

    async def _authorized_provider(
        self,
        action: str,
        provider,
        destination: str | None,
        constants: dict,
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
            "message",
            action=action,
            request=request,
        )

    async def _dispatch(
        self,
        session,
        domain: str | None,
        **constants,
    ):
        """
        Instrada il messaggio verso i provider/controller appropriati.
        """
        destination = constants.get("receiver")
        adapter = constants.get("adapter")

        if adapter == "dsl":
            if not destination or not self.defender or destination not in self.defender.controllers:
                return
            request = dict(constants)
            request.update({"adapter": "dsl", "provider": "dsl", "receiver": destination})
            if await self.defender.authorized("message", action="publish", request=request):
                await session.emit(domain, constants.get("message"))
            return

        matched = self._matching_providers(destination, adapter)

        message_text = constants.get('message')

        if destination and not matched:
            return

        for provider in matched:
            if await self._authorized_provider("publish", provider, destination, constants):
                await provider.post(session, **constants | {'domain': domain})

    @flow.result(inputs=('messenger',), outputs=())
    async def send(self, session, **constants):
        """
        Invia un messaggio.

        Il routing effettivo viene delegato a _dispatch().
        """
        dispatch_constants = {
            key: value
            for key, value in constants.items()
            if key != "domain"
        }
        await self._dispatch(session, constants.get('domain'), **dispatch_constants)

    @flow.result(inputs=(), outputs=())
    async def receive(self, session, **constants):
        """
        Riceve il primo risultato disponibile dai provider.
        """
        domain = constants.get("domain")
        destination = constants.get("receiver")
        matched = self._matching_providers(destination)

        if destination and not matched:
            return None

        authorized = [
            provider
            for provider in matched
            if await self._authorized_provider("subscribe", provider, destination, constants)
        ]
        tasks = [
            asyncio.create_task(provider.read(session, **constants | {'domain': domain}))
            for provider in authorized
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