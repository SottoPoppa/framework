from typing import Any

import framework.service.flow as flow


class Adapter:
    """Driver UI senza runtime grafico per i test del Presenter."""

    def __init__(self, **constants: Any) -> None:
        self.name = constants.get("name", "stub")
        self.config = constants
        self.attributes = dict(constants.get("attributes", {}))
        self.url = constants.get("url", "/")
        self.routes: dict[str, dict[str, Any]] = {}
        self.rebuilt: list[tuple[Any, ...]] = []

    async def start(self, session):
        return flow.success({"provider": self.name, "started": True})

    async def stop(self, session):
        return flow.success({"provider": self.name, "stopped": True})

    async def get_attribute(self, widget: str, field: str):
        return flow.success(self.attributes.get(widget, {}).get(field))

    async def selector(self, **constants: Any):
        return flow.success(constants.get("selector"))

    async def apply_route(self, **constants: Any):
        self.url = constants.get("url", constants.get("path", self.url))
        return flow.success({"url": self.url})

    async def rebuild(self, *args: Any):
        self.rebuilt.append(args)
        return flow.success({"rebuilt": True})

    async def render_view(self, url: str):
        self.url = url
        return flow.success({"url": url})