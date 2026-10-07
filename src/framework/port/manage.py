from typing import Protocol, Any, runtime_checkable

@runtime_checkable
class Port(Protocol):

    async def start(self, endpoint: str, context: dict[str, Any]) -> object:
        """Inizializza il port."""
        ...

    async def stop(self, endpoint: str, context: dict[str, Any]) -> object:
        """Arresta il port."""
        ...