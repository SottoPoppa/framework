"""Registry delle funzioni e dei dati disponibili al DSL.

Il registry è gerarchico: ogni sessione ottiene un livello figlio e non può
sovrascrivere le voci del livello condiviso. Questo garantisce l'isolamento fra
sessioni diverse dello stesso interprete.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - solo diagnostica
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


class Registry:
    """Contenitore a catena di funzioni, dati e istanze esposti al DSL."""

    __slots__ = ("_items", "_parent")

    def __init__(self, initial: Dict[str, Any] | None = None, parent: "Registry | None" = None):
        self._items: Dict[str, Any] = {}
        self._parent = parent
        if initial:
            self.register_dict(initial)

    def child(self, initial: Dict[str, Any] | None = None) -> "Registry":
        """Livello figlio isolato: le scritture non risalgono al padre."""
        return Registry(initial, self)

    def register(self, name: str, item: Any) -> None:
        """Registra un singolo elemento (funzione, dato, istanza, ecc.)."""
        self._items[name] = item

    def register_dict(self, items: Dict[str, Any]) -> None:
        """Registra un intero dizionario di elementi nel registry."""
        for name, item in items.items():
            self.register(name, item)

    def register_callables(self, items: Dict[str, Any]) -> None:
        """Registra le sole callable di una mappa, ignorando i dati."""
        for name, item in items.items():
            if callable(item):
                self.register(name, item)

    def chain(self) -> Iterator["Registry"]:
        registry: Registry | None = self
        while registry is not None:
            yield registry
            registry = registry._parent

    def lookup(self, name: str) -> Any:
        """Risolve lungo la catena; ``MISSING`` se assente."""
        for registry in self.chain():
            if name in registry._items:
                return registry._items[name]
            parts = name.split(".")
            value = registry._items.get(parts[0], MISSING)
            for part in parts[1:]:
                if part.startswith("_"):
                    value = MISSING
                    break
                if isinstance(value, dict):
                    value = value.get(part, MISSING)
                elif isinstance(value, (list, tuple)) and part.lstrip("-").isdigit():
                    index = int(part)
                    value = value[index] if -len(value) <= index < len(value) else MISSING
                else:
                    value = getattr(value, part, MISSING)
                if value is MISSING:
                    break
            if value is not MISSING:
                return value
        return MISSING

    def resolve(self, name: str) -> Any:
        """Restituisce l'elemento cercato, risalendo la catena dei registry."""
        item = self.lookup(name)
        if item is MISSING:
            raise KeyError(f"Funzione o dato '{name}' non trovato nel Registry.")
        return item

    def has(self, name: str) -> bool:
        """Verifica se un elemento è registrato nella catena."""
        return self.lookup(name) is not MISSING

    def __repr__(self) -> str:  # pragma: no cover - solo diagnostica
        return f"Registry(items={len(self._items)}, parent={self._parent is not None})"
