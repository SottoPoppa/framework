import asyncio
from collections import defaultdict
from typing import List

import framework.port.message as message

class Adapter(message.Port):

    capabilities = {
        "tls": False,
        "encryption": False,
        "audit": False,
        "rate_limiting": False,
        "authentication": [],
    }

    def __init__(self, **constants):
        self.adapter = __name__.split(".")[-1]
        self.config = constants

        self.processable: List[str] = ["event", "broadcast"]

        # (reader_id, pattern) -> Queue
        self._queues = {}

    @staticmethod
    def _reader_id(session):
        return getattr(session, "id", None) or str(id(session))

    @staticmethod
    def _matches(pattern, domain):

        if pattern == "*":
            return True

        p = pattern.split(".")
        d = domain.split(".")

        return len(d) >= len(p) and d[:len(p)] == p

    async def post(self, *services, **constants):

        domain = constants.get("domain", "general")
        message = constants.get("payload", constants.get("message"))

        for (_, pattern), queue in list(self._queues.items()):

            if self._matches(pattern, domain):
                await queue.put(message)

    async def read(self, session, *services, **constants):

        pattern = constants.get("domain", "general")

        key = (self._reader_id(session), pattern)

        queue = self._queues.setdefault(key, asyncio.Queue())

        message = await queue.get()

        return message

    def forget(self, session):

        rid = self._reader_id(session)

        for key in list(self._queues):

            if key[0] == rid:
                del self._queues[key]