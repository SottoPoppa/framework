from typing import Protocol, Any, runtime_checkable
import framework.core.flow as flow

@runtime_checkable
class Port(Protocol):
    capabilities = {
        "tls": False,
        "encryption": False,
        "audit": False,
        "rate_limiting": False,
        "authentication": [],
    }

    _method_decorators = {
        "read": flow.result(),
        "post": flow.result(),
        "can": flow.result(),
    }

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method_name, decorator in Port._method_decorators.items():
            original = cls.__dict__.get(method_name)
            if original is not None:
                setattr(cls, method_name, decorator(original))

    def loader(self, config: dict[str, Any]) -> None:
        """Inizializza o configura l'adapter con i dati passati dal framework."""
        ...

    async def get(self, endpoint: str, context: dict[str, Any]) -> Any:
        """Gestisce una richiesta in ingresso di tipo GET."""
        ...

    async def post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        """Gestisce una richiesta in ingresso di tipo POST."""
        ...

    async def can(self, identity: str, action: str) -> bool:
        """Verifica i permessi di sicurezza (ACL/RBAC) per un determinato modulo."""
        ...