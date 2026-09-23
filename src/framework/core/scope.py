"""Scope lessicale dell'interprete.

Un ``Scope`` è una catena di binding: la risoluzione sale verso il padre, la
scrittura resta sempre nel livello corrente. Sostituisce l'accesso globale e
condiviso del vecchio ``ExecutionContext``.

Due scelte deliberate:

* ``MISSING`` è distinto da ``None``: una chiave che vale ``None`` è presente,
  e non innesca fallback impliciti;
* la navigazione per path raggiunge i soli attributi pubblici: il DSL può usare
  ``storekeeper.overview`` o ``imports.model.Literal``, ma non può scendere nei
  membri privati del runtime.
"""

from __future__ import annotations

from typing import Any, Iterator


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - solo diagnostica
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


def _descend(current: Any, part: str) -> Any:
    if isinstance(current, dict):
        if part in current:
            return current[part]
        if type(current) is not dict and not part.startswith("_"):
            return getattr(current, part, MISSING)
        return MISSING
    if isinstance(current, (list, tuple)):
        if not part.lstrip("-").isdigit():
            return MISSING
        index = int(part)
        return current[index] if -len(current) <= index < len(current) else MISSING
    if part.startswith("_"):
        return MISSING
    return getattr(current, part, MISSING)


class Scope:
    """Livello di binding con risoluzione a catena."""

    __slots__ = ("_data", "_parent")

    def __init__(self, data: dict[str, Any] | None = None, parent: "Scope | None" = None):
        self._data: dict[str, Any] = dict(data) if data else {}
        self._parent = parent

    # ── struttura ────────────────────────────────────────────────────────────

    @property
    def data(self) -> dict[str, Any]:
        """Binding del solo livello corrente."""
        return self._data

    @property
    def parent(self) -> "Scope | None":
        return self._parent

    def child(self, data: dict[str, Any] | None = None, **bindings: Any) -> "Scope":
        """Nuovo livello figlio; il padre non viene mai modificato."""
        return Scope({**(data or {}), **bindings}, self)

    def chain(self) -> Iterator["Scope"]:
        scope: Scope | None = self
        while scope is not None:
            yield scope
            scope = scope._parent

    def flatten(self) -> dict[str, Any]:
        """Vista piatta della catena: i livelli interni coprono quelli esterni."""
        merged: dict[str, Any] = {}
        for scope in reversed(list(self.chain())):
            merged.update(scope._data)
        return merged

    # ── lettura ──────────────────────────────────────────────────────────────

    def lookup(self, path: str) -> Any:
        """Risolve un path lungo la catena; ``MISSING`` se non esiste."""
        if not path:
            return MISSING
        head, _, rest = path.partition(".")
        for scope in self.chain():
            if head in scope._data:
                current = scope._data[head]
                if not rest:
                    return current
                for part in rest.split("."):
                    current = _descend(current, part)
                    if current is MISSING:
                        break
                if current is not MISSING:
                    return current
        return MISSING

    def get(self, path: str, default: Any = None) -> Any:
        value = self.lookup(path)
        return default if value is MISSING else value

    def exists(self, path: str) -> bool:
        return self.lookup(path) is not MISSING

    # ── scrittura ────────────────────────────────────────────────────────────

    def set(self, path: str, value: Any) -> None:
        """Scrive nel livello corrente, creando le mappe intermedie mancanti."""
        if not path:
            return
        parts = path.split(".")
        current = self._data
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = nested
        current[parts[-1]] = value

    def delete(self, path: str) -> bool:
        if not path:
            return False
        parts = path.split(".")
        current = self._data
        for part in parts[:-1]:
            current = current.get(part)
            if not isinstance(current, dict):
                return False
        return current.pop(parts[-1], MISSING) is not MISSING

    # ── comodità ─────────────────────────────────────────────────────────────

    def __contains__(self, path: str) -> bool:
        return self.exists(path)

    def __getitem__(self, path: str) -> Any:
        value = self.lookup(path)
        if value is MISSING:
            raise KeyError(path)
        return value

    def __setitem__(self, path: str, value: Any) -> None:
        self.set(path, value)

    def __repr__(self) -> str:  # pragma: no cover - solo diagnostica
        return f"Scope(keys={sorted(self._data)}, parent={self._parent is not None})"
