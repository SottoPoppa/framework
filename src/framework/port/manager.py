"""Contract for application managers."""

import inspect
from abc import ABC

from framework.core.data import session_injection


class Port(ABC):
    """Validate that public manager operations receive a session first."""

    _session_exempt_methods: set[str] = set()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        exempt = set().union(
            *(getattr(base, "_session_exempt_methods", set()) for base in cls.__mro__)
        )
        exempt.update(getattr(cls, "_session_exempt_methods", set()))

        for name, method in cls.__dict__.items():
            if name.startswith("_") or name in exempt or not callable(method):
                continue
            signature = inspect.signature(method)
            parameters = list(signature.parameters.values())
            if not parameters or parameters[0].name != "self":
                continue
            injection = session_injection(method)
            expected_session_parameter = injection[0] if injection else "session"
            if len(parameters) < 2 or parameters[1].name != expected_session_parameter:
                raise TypeError(
                    f"{cls.__name__}.{name} deve ricevere '{expected_session_parameter}' come primo argomento."
                )
