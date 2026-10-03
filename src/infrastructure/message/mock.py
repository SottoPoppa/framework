import asyncio
import fnmatch
from collections import defaultdict
from typing import Any

import framework.core.flow as flow
import framework.port.message as message


class Adapter(message.Port):
    """Provider in memoria per testare il routing del Messenger."""

    def __init__(self, **constants: Any) -> None:
        self.adapter = __name__.split(".")[-1]
        self.config = constants
        self.name = constants.get("name", self.adapter)
        self._history: list[dict[str, Any]] = []
        self._cursors: dict[str, int] = defaultdict(int)
        self._events: dict[str, asyncio.Event] = {}

    @staticmethod
    def _reader_id(session: Any) -> str:
        return str(getattr(session, "id", None) or id(session))

    @staticmethod
    def _matches(pattern: str, domain: str) -> bool:
        return fnmatch.fnmatch(domain, pattern)

    def _event_for(self, reader_id: str) -> asyncio.Event:
        return self._events.setdefault(reader_id, asyncio.Event())

    @flow.result()
    async def can(self, *services: Any, **constants: Any) -> bool:
        return constants.get("name") in {"post", "read", "event"}

    @flow.result()
    async def post(self, *services: Any, **constants: Any) -> None:
        message_data = dict(constants)
        message_data.setdefault("domain", "general")
        self._history.append(message_data)

        for event in self._events.values():
            event.set()

    @flow.result()
    async def read(self, session: Any, *services: Any, **constants: Any) -> dict[str, Any] | None:
        reader_id = self._reader_id(session)
        pattern = constants.get("domain", "*")
        event = self._event_for(reader_id)

        while True:
            cursor = self._cursors[reader_id]
            for index in range(cursor, len(self._history)):
                message_data = self._history[index]
                if self._matches(pattern, message_data["domain"]):
                    self._cursors[reader_id] = index + 1
                    return message_data

            event.clear()
            await event.wait()

    def forget(self, session: Any) -> None:
        reader_id = self._reader_id(session)
        self._cursors.pop(reader_id, None)
        self._events.pop(reader_id, None)