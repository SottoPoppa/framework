from __future__ import annotations

import types
from collections.abc import Mapping
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Self,
    TypeGuard,
    Union,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
    get_type_hints,
)

import framework.core.flow as flow

_MISSING = object()


def is_scheme_type(value: Any) -> TypeGuard[type[Scheme]]:
    return isinstance(value, type) and issubclass(value, Scheme)


def _type_hints(scheme_type: type[Scheme]) -> dict[str, Any]:
    try:
        return get_type_hints(scheme_type, include_extras=True)
    except (NameError, TypeError):
        return cast(dict[str, Any], getattr(scheme_type, "__annotations__", {}))


def _annotation_rule(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    arguments = get_args(annotation)

    if origin is Annotated:
        rule = _annotation_rule(arguments[0])
        for metadata in arguments[1:]:
            if isinstance(metadata, Mapping):
                rule.update(cast(Mapping[str, Any], metadata))
        return rule

    if origin is Literal:
        return {"allowed": list(arguments)}

    if origin in (Union, types.UnionType):
        choices = tuple(option for option in arguments if option is not type(None))
        nullable = len(choices) != len(arguments)
        if len(choices) == 1:
            rule = _annotation_rule(choices[0])
        else:
            rule = {"anyof": [_annotation_rule(option) for option in choices]}
        if nullable:
            rule["nullable"] = True
        return rule

    if is_scheme_type(annotation):
        return {"type": "dict", "schema": class_schema(annotation)}

    if origin is list or annotation is list:
        rule: dict[str, Any] = {"type": "list"}
        if arguments:
            rule["schema"] = _annotation_rule(arguments[0])
        return rule

    if origin is tuple or annotation is tuple:
        rule = {"type": "list"}
        if arguments:
            item_types = arguments[:1] if arguments[-1] is Ellipsis else arguments
            item_rules = [_annotation_rule(item_type) for item_type in item_types]
            rule["schema"] = (
                item_rules[0] if len(item_rules) == 1 else {"anyof": item_rules}
            )
        return rule

    if origin in (dict, Mapping) or annotation in (dict, Mapping):
        rule = {"type": "dict"}
        if len(arguments) == 2:
            key_rule = _annotation_rule(arguments[0])
            value_rule = _annotation_rule(arguments[1])
            if key_rule:
                rule["keysrules"] = key_rule
            if value_rule:
                rule["valuesrules"] = value_rule
        return rule

    type_names: dict[type[Any], str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        bytes: "binary",
        list: "list",
        dict: "dict",
    }
    type_name = type_names.get(annotation) if isinstance(annotation, type) else None
    return {"type": type_name} if type_name is not None else {}


def class_schema(scheme_type: type[Scheme]) -> dict[str, Any]:
    declared_schema = getattr(scheme_type, "SCHEME", {})
    schema = (
        dict(cast(Mapping[str, Any], declared_schema))
        if isinstance(declared_schema, Mapping)
        else {}
    )

    for name, annotation in _type_hints(scheme_type).items():
        if get_origin(annotation) is ClassVar:
            continue

        rule = _annotation_rule(annotation)
        default = vars(scheme_type).get(name, _MISSING)
        rule.setdefault("required", default is _MISSING)
        if default is not _MISSING:
            rule.setdefault("default", default)
            if default is None:
                rule.setdefault("nullable", True)

        explicit_rule = schema.get(name)
        if isinstance(explicit_rule, Mapping):
            rule.update(cast(Mapping[str, Any], explicit_rule))
        schema[name] = rule

    return schema


def _coerce_annotation(value: object, annotation: Any) -> object:
    original_value = value
    if value is None:
        return None

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Annotated:
        return _coerce_annotation(value, arguments[0])

    if origin in (Union, types.UnionType):
        for option in arguments:
            if option is type(None):
                continue
            try:
                return _coerce_annotation(value, option)
            except (TypeError, ValueError):
                continue
        return value

    if is_scheme_type(annotation):
        if isinstance(value, annotation):
            return value
        if isinstance(value, Mapping):
            return annotation.from_mapping(cast(Mapping[str, Any], value))
        return value

    if origin in (list, tuple) and isinstance(value, (list, tuple)) and arguments:
        sequence = cast(list[Any] | tuple[Any, ...], value)
        item_types = arguments[:1] if origin is tuple and arguments[-1] is Ellipsis else arguments
        if len(item_types) == 1:
            items = [_coerce_annotation(item, item_types[0]) for item in sequence]
        else:
            items = [
                _coerce_annotation(item, item_types[index])
                if index < len(item_types)
                else item
                for index, item in enumerate(sequence)
            ]
        return tuple(items) if origin is tuple else items

    if origin in (dict, Mapping) and isinstance(value, Mapping) and len(arguments) == 2:
        key_type, value_type = arguments
        mapping = cast(Mapping[Any, Any], value)
        return {
            _coerce_annotation(key, key_type): _coerce_annotation(item, value_type)
            for key, item in mapping.items()
        }

    return original_value


@dataclass_transform()
class Scheme(flow.Immutable):
    """Mapping immutabile validato in base alle annotazioni della classe."""

    SCHEME: ClassVar[dict[str, Any]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        scheme_type = type(self)
        annotations = _type_hints(scheme_type)
        field_names = [
            name
            for name, annotation in annotations.items()
            if get_origin(annotation) is not ClassVar
        ]

        if len(args) == 1 and isinstance(args[0], Mapping) and not kwargs:
            input_data = dict(cast(Mapping[str, Any], args[0]))
        elif args:
            if len(args) > len(field_names):
                raise TypeError(f"Troppi valori per {scheme_type.__name__}")
            input_data = dict(zip(field_names, args))
            duplicate_fields = input_data.keys() & kwargs.keys()
            if duplicate_fields:
                names = ", ".join(sorted(duplicate_fields))
                raise TypeError(f"Valori duplicati per {names}")
            input_data.update(kwargs)
        else:
            input_data = dict(kwargs)

        from framework.service.scheme import normalize

        result = normalize(input_data, class_schema(scheme_type))
        if not result.is_success:
            raise result.output.error

        normalized = cast(Mapping[str, Any], flow.output(result))
        typed_values = {
            name: _coerce_annotation(value, annotations[name])
            if name in annotations and get_origin(annotations[name]) is not ClassVar
            else value
            for name, value in normalized.items()
        }
        super().__init__(typed_values)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        """Crea un'istanza validando un mapping proveniente da runtime/JSON."""
        constructor: Any = cls
        return constructor(dict(value))