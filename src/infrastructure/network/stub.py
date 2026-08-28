from typing import Any

import framework.core.flow as flow


class Adapter:
    """Provider di rete locale per testare selezione e delega del Networker."""

    def __init__(self, **constants: Any) -> None:
        self.name = constants.get("name", "stub")
        self.config = constants
        self.capabilities = constants.get("capabilities", {"platform": "stub"})
        self.calls: list[tuple[str, Any]] = []

    async def provision(self, intent: dict[str, Any]):
        self.calls.append(("provision", intent))
        return flow.success({"provider": self.name, "intent": intent})

    async def route(self, application: dict[str, Any], requirements: dict[str, Any]):
        self.calls.append(("route", application, requirements))
        return flow.success({"provider": self.name, "application": application})

    async def compute(self):
        self.calls.append(("compute", None))
        return flow.success({"provider": self.name, "computed": True})

    async def monitor(self):
        self.calls.append(("monitor", None))
        return flow.success({"provider": self.name, "status": "ok"})

    async def status(self):
        self.calls.append(("status", None))
        return flow.success({"provider": self.name, "status": "ready"})