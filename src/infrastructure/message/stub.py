import asyncio
from collections import defaultdict
import fnmatch
from typing import Any

import framework.port.message as message
import framework.core.flow as flow


class Adapter(message.Port):
    """Provider di messaggi deterministico per i test di integrazione."""

    def __init__(self, **constants: Any) -> None:
        self.adapter = "stub"
        self.config = constants
        self.name = constants.get("name", "stub")
        self.messages: list[dict[str, Any]] = []
        self.positions: defaultdict[str, int] = defaultdict(int)
        self.events: defaultdict[str, asyncio.Event] = defaultdict(asyncio.Event)

    def loader(self, config: dict[str, Any]) -> None:
        self.config.update(config)

    async def post(self, *services: Any, **constants: Any):
        message_data = dict(constants)
        message_data.setdefault("domain", "general")
        self.messages.append(message_data)
        for event in self.events.values():
            event.set()

    async def read(self, session: Any, *services: Any, **constants: Any):
        reader = str(getattr(session, "id", None) or id(session))
        pattern = constants.get("domain", "*")
        for index in range(self.positions[reader], len(self.messages)):
            message_data = self.messages[index]
            if fnmatch.fnmatch(message_data["domain"], pattern):
                self.positions[reader] = index + 1
                return message_data
        return None

    async def can(self, identity: str, action: str) -> bool:
        return action in {"post", "read", "event"}
