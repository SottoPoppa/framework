from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

import framework.core.flow as flow


@runtime_checkable
class Port(Protocol):
    capabilities: dict[str, Any] = {
        "tls": False,
        "encryption": False,
        "audit": False,
        "rate_limiting": False,
        "authentication": [],
    }
    adapter: str
    config: dict[str, Any]

    _method_decorators: dict[str, Callable[..., Any]] = {
        "read": flow.result(),
        "post": flow.result(),
        "can": flow.result(),
    }

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for method_name, decorator in Port._method_decorators.items():
            original = cls.__dict__.get(method_name)
            if original is not None:
                setattr(cls, method_name, decorator(original))

    def read(
        self,
        session: Any,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Legge messaggi dal provider per la sessione indicata."""
        ...

    def post(
        self,
        session: Any,
        *services: Any,
        **constants: Any,
    ) -> Awaitable[flow.FlowResult]:
        """Invia un messaggio al provider."""
        ...