from abc import abstractmethod
from typing import Any, Callable, Protocol

import framework.core.flow as flow

class Port(Protocol):
    name: str
    capabilities: dict[str, Any] = {
        "password_hashing": False,
        "mfa": False,
        "token_rotation": False,
        "sso": False,
        "account_lockout": False,
        "authentication": [],
    }

    # Mappa: nome_metodo -> decoratore da applicare automaticamente
    _method_decorators: dict[str, Callable[..., Any]] = {
        "sign_in":      flow.result(inputs=("email", "password")),
        "sign_up":      flow.result(inputs=("email", "password")),
        "sign_out":     flow.result(inputs=("session",),          outputs=("session",)),
        "sign_aid":     flow.result(),
        "get_user": flow.result(inputs=("session",)),
    }

    _seeds: list[Any] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for method_name, decorator in Port._method_decorators.items():
            if method_name in cls.__dict__:  # solo se definito direttamente
                original = cls.__dict__[method_name]
                setattr(cls, method_name, decorator(original))

    @abstractmethod
    async def sign_in(
        self, email: str, password: str
    ) -> flow.FlowResult:
        ...

    @abstractmethod
    async def sign_up(
        self, email: str, password: str
    ) -> flow.FlowResult:
        ...

    @abstractmethod
    async def sign_out(self, session: dict[str, Any]) -> flow.FlowResult:
        ...

    @abstractmethod
    async def get_user(self, session: dict[str, Any]) -> flow.FlowResult:
        ...

    @abstractmethod
    async def sign_aid(
        self, *, email: str, **constants: Any
    ) -> flow.FlowResult:
        ...