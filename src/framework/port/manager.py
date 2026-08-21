"""Contract for application managers."""

import inspect
from abc import ABC


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
            if len(parameters) < 2 or parameters[1].name != "session":
                raise TypeError(
                    f"{cls.__name__}.{name} deve ricevere 'session' come primo argomento."
                )
