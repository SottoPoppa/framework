from copy import deepcopy
from typing import Any
from collections.abc import Mapping


_DSL_TYPES = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "float",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "dict": "dict",
    "map": "dict",
    "list": "list",
    "array": "list",
    "tuple": "list",
}


def schema_definition(schema: Any) -> dict:
    """Converte uno schema DSL nel formato accettato da Cerberus."""
    if not isinstance(schema, Mapping):
        raise TypeError("Lo schema deve essere una mappa")

    normalized = {}
    for field, definition in schema.items():
        if not isinstance(definition, Mapping):
            raise TypeError(f"La definizione di {field!r} deve essere una mappa")

        rule = {}
        for key, value in definition.items():
            if key == "type" and isinstance(value, str):
                rule[key] = _DSL_TYPES.get(value.lower(), value.lower())
            elif key == "schema" and isinstance(value, Mapping):
                if definition.get("type") in {"list", "array", "tuple"}:
                    rule[key] = field_schema(value)
                else:
                    rule[key] = schema_definition(value)
            elif key == "allowed" and isinstance(value, (list, tuple, set)):
                rule[key] = list(value)
            else:
                rule[key] = value
        normalized[field] = rule
    return normalized


def field_schema(schema: Mapping[str, Any]) -> dict:
    """Normalizza lo schema di un elemento di lista o di una mappa."""
    if "type" in schema:
        result = dict(schema)
        value = result.get("type")
        if isinstance(value, str):
            result["type"] = _DSL_TYPES.get(value.lower(), value.lower())
        if isinstance(result.get("schema"), Mapping):
            result["schema"] = (
                field_schema(result["schema"])
                if result.get("type") == "list"
                else schema_definition(result["schema"])
            )
        return result
    return schema_definition(schema)


class ExecutionContext:

    def __init__(self, initial: dict | None = None):
        self._data: dict[str, Any] = dict(initial) if initial else {}

    @property
    def data(self) -> dict[str, Any]:
        """Ritorna il dizionario interno del contesto."""
        return self._data

    def get(self, path: str, default: Any = None) -> Any:
        """Recupera un valore dal contesto, supportando la dot-notation (es. 'user.name')."""
        if not path:
            return default

        parts = path.split(".")
        current = self._data

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, (list, tuple)) and part.isdigit():
                index = int(part)
                if index >= len(current):
                    return default
                current = current[index]
            elif not isinstance(current, dict) and hasattr(current, part):
                current = getattr(current, part)
            else:
                return default

        return current

    def set(self, path: str, value: Any) -> None:
        """Imposta o aggiorna un valore nel contesto, creando dizionari annidati se necessario."""
        if not path:
            return

        parts = path.split(".")
        current = self._data

        # Naviga fino al penultimo livello creando i dizionari mancanti
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]

        # Imposta il valore nel livello finale
        current[parts[-1]] = value

    def exists(self, path: str) -> bool:
        """Verifica l'esistenza di un percorso/chiave nel contesto."""
        if not path:
            return False

        parts = path.split(".")
        current = self._data

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False

        return True

    def delete(self, path: str) -> bool:
        """Rimuove un percorso dal contesto. Ritorna True se rimosso con successo."""
        if not path:
            return False

        parts = path.split(".")
        current = self._data

        for part in parts[:-1]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False

        if isinstance(current, dict) and parts[-1] in current:
            del current[parts[-1]]
            return True

        return False

    def snapshot(self) -> dict[str, Any]:
        """Ritorna una copia profonda dello stato corrente."""
        return deepcopy(self._data)

    # --- Metodi Dunder per supporto operatore dizionario (context["key"]) ---
    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None and not self.exists(key):
            raise KeyError(key)
        return val

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return self.exists(key)

    def __repr__(self) -> str:
        return f"ExecutionContext({self._data!r})"