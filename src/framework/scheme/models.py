from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, cast

from framework.scheme.runtime import Scheme
from framework.service.scheme import resolve_schemes
from framework.service.scheme_codegen import (
    PROJECT_ROOT,
    annotation_from_rule,
    class_names,
    load_json_schemas,
)


def _identity_render(value: str, context: dict[str, Any]) -> str:
    return value


class _GeneratedScheme(Scheme):
    __optional_fields__: ClassVar[frozenset[str]] = frozenset()

    def __getattr__(self, item: str) -> Any:
        if item in self.__optional_fields__:
            return None
        return super().__getattr__(item)


def _preserve_json_required(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        return {}
    normalized: dict[str, Any] = {}
    for field_name, rule in cast(Mapping[str, Any], schema).items():
        if isinstance(rule, Mapping):
            normalized_rule = dict(cast(Mapping[str, Any], rule))
            normalized_rule.setdefault("required", False)
            normalized[field_name] = normalized_rule
        else:
            normalized[field_name] = rule
    return normalized


_JSON_SCHEMAS = load_json_schemas(PROJECT_ROOT)
_CLASS_NAMES = class_names(_JSON_SCHEMAS)
_RESOLVED_SCHEMAS = resolve_schemes(_JSON_SCHEMAS, _identity_render)

SCHEME_TYPES: dict[str, type[Scheme]] = {}

for _schema_name, _schema in _JSON_SCHEMAS.items():
    _annotations = {
        field_name: annotation_from_rule(rule, _CLASS_NAMES)
        for field_name, rule in _schema.items()
        if field_name.isidentifier()
    }
    _optional_fields = frozenset(
        field_name
        for field_name, rule in _schema.items()
        if isinstance(rule, Mapping)
        and not cast(Mapping[str, Any], rule).get("required", False)
        and "default" not in cast(Mapping[str, Any], rule)
    )
    _model = cast(
        type[Scheme],
        type(
            _CLASS_NAMES[_schema_name],
            (_GeneratedScheme,),
            {
                "__module__": __name__,
                "__annotations__": _annotations,
                "__optional_fields__": _optional_fields,
                "SCHEME": _preserve_json_required(
                    _RESOLVED_SCHEMAS.get(_schema_name, _schema)
                ),
            },
        ),
    )
    SCHEME_TYPES[_schema_name] = _model
    globals()[_CLASS_NAMES[_schema_name]] = _model


def bind_schemas(schemas: Mapping[str, Any]) -> None:
    """Aggiorna i modelli con gli schemi risolti dal loader dell'applicazione."""
    for schema_name, model_type in SCHEME_TYPES.items():
        schema = schemas.get(schema_name)
        if isinstance(schema, Mapping):
            model_type.SCHEME = _preserve_json_required(schema)