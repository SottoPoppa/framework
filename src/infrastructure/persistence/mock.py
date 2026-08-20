from copy import deepcopy
from typing import Any

import framework.port.persistence as persistence
import framework.service.flow as flow


class Adapter(persistence.Port):
    """Adapter in memoria per testare il contratto di persistenza."""

    def __init__(self, **constants: Any) -> None:
        self.adapter = __name__.split(".")[-1]
        self.config = constants
        self.name = constants.get("name", self.adapter)
        self._records: dict[str, Any] = {}

    async def request(self, *services: Any, **constants: Any):
        operation = constants.get("operation", "read")
        method = getattr(self, operation, None)
        if not callable(method):
            return flow.error(f"Operazione non disponibile: {operation}")
        return await method(*services, **constants)

    @staticmethod
    def _location(storekeeper: dict[str, Any]) -> str:
        return str(storekeeper.get("location", ""))

    async def create(self, session: Any, storekeeper: dict[str, Any]):
        location = self._location(storekeeper)
        if location in self._records:
            return flow.error(f"Risorsa già esistente: {location}")
        value = deepcopy(storekeeper.get("payload", {}))
        self._records[location] = value
        return flow.success(deepcopy(value))

    async def read(self, session: Any, storekeeper: dict[str, Any]):
        location = self._location(storekeeper)
        if location not in self._records:
            return flow.error(f"Risorsa non trovata: {location}")
        return flow.success(deepcopy(self._records[location]))

    async def update(self, session: Any, storekeeper: dict[str, Any]):
        location = self._location(storekeeper)
        if location not in self._records:
            return flow.error(f"Risorsa non trovata: {location}")
        value = deepcopy(storekeeper.get("payload", {}))
        self._records[location] = value
        return flow.success(deepcopy(value))

    async def delete(self, session: Any, storekeeper: dict[str, Any]):
        location = self._location(storekeeper)
        if location not in self._records:
            return flow.error(f"Risorsa non trovata: {location}")
        del self._records[location]
        return flow.success({})

    async def query(self, session: Any, storekeeper: dict[str, Any]):
        return flow.success(deepcopy(list(self._records.values())))

    async def view(self, session: Any, storekeeper: dict[str, Any]):
        return await self.read(session, storekeeper)
