from typing import Any, Protocol


class Port(Protocol):
    def loader(self, *services: Any, **constants: Any) -> None:
        ...

    async def process(self, *services: Any, **constants: Any) -> object:
        ...


port = Port