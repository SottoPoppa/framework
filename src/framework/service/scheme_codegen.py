from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
import types
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, ForwardRef, Literal, Union, cast, get_args, get_origin


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIRECTORIES = (
    Path("src/framework/scheme"),
    Path("src/application/model"),
)
STUB_PATH = Path("src/framework/scheme/models.pyi")
_SCHEME_REFERENCE = re.compile(
    r"^\{\{\s*scheme\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$"
)


def class_name(schema_name: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", schema_name)
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    if not name or name[0].isdigit():
        name = f"Schema{name}"
    return f"{name}Scheme"


def load_json_schemas(root: Path = PROJECT_ROOT) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for relative_directory in SCHEMA_DIRECTORIES:
        directory = root / relative_directory
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError(f"Lo schema {path} deve avere una mappa al livello radice")
            schemas[path.stem] = dict(cast(Mapping[str, Any], value))
    return schemas


def class_names(schemas: Mapping[str, Any]) -> dict[str, str]:
    names = {schema_name: class_name(schema_name) for schema_name in schemas}
    reverse: dict[str, str] = {}
    for schema_name, generated_name in names.items():
        previous = reverse.get(generated_name)
        if previous is not None and previous != schema_name:
            raise ValueError(
                f"I nomi schema {previous!r} e {schema_name!r} generano "
                f"entrambi la classe {generated_name}"
            )
        reverse[generated_name] = schema_name
    return names


def _union(annotations: tuple[Any, ...] | list[Any]) -> Any:
    unique: list[Any] = []
    for annotation in annotations:
        if annotation not in unique:
            unique.append(annotation)
    if not unique:
        return Any
    if len(unique) == 1:
        return unique[0]
    return cast(Any, Union)[tuple(unique)]


def _reference_name(value: Any, names: Mapping[str, str]) -> str | None:
    if not isinstance(value, str):
        return None
    match = _SCHEME_REFERENCE.fullmatch(value.strip())
    if match is None:
        return None
    return names.get(match.group(1))


def _base_annotation(type_name: Any) -> Any:
    if isinstance(type_name, list):
        type_names = cast(list[Any], type_name)
        return _union([_base_annotation(name) for name in type_names])
    if not isinstance(type_name, str):
        return Any

    match type_name:
        case "string":
            return str
        case "integer":
            return int
        case "float":
            return float
        case "number":
            return _union([int, float])
        case "boolean":
            return bool
        case "binary":
            return bytes
        case "date":
            return date
        case "datetime":
            return datetime
        case "dict":
            return dict[str, Any]
        case "list":
            return list[Any]
        case "set":
            return set[Any]
        case "tuple":
            return tuple[Any, ...]
        case _:
            return Any


def annotation_from_rule(
    rule: Any,
    names: Mapping[str, str],
) -> Any:
    if not isinstance(rule, Mapping):
        return Any
    typed_rule = cast(Mapping[str, Any], rule)
    schema_rule = typed_rule.get("schema")
    type_name = typed_rule.get("type")

    allowed = typed_rule.get("allowed")
    if (
        isinstance(allowed, list)
        and allowed
        and all(
            value is None or type(value) in (str, int, float, bool)
            for value in cast(list[Any], allowed)
        )
    ):
        annotation = cast(Any, Literal)[tuple(cast(list[Any], allowed))]
    else:
        alternatives = typed_rule.get("anyof", typed_rule.get("oneof"))
        if isinstance(alternatives, list):
            annotation = _union(
                [
                    annotation_from_rule(option, names)
                    for option in cast(list[Any], alternatives)
                ]
            )
        else:
            referenced_model = _reference_name(schema_rule, names)
            if referenced_model is not None:
                referenced_type = ForwardRef(referenced_model)
                if type_name == "list":
                    annotation = list[referenced_type]
                else:
                    annotation = referenced_type
            elif type_name == "list":
                if isinstance(schema_rule, Mapping) and "type" in schema_rule:
                    item_type = annotation_from_rule(
                        cast(Mapping[str, Any], schema_rule), names
                    )
                else:
                    item_type = Any
                annotation = list[item_type]
            elif type_name == "dict":
                key_rule = typed_rule.get("keysrules")
                value_rule = typed_rule.get("valuesrules")
                key_type = (
                    annotation_from_rule(cast(Mapping[str, Any], key_rule), names)
                    if isinstance(key_rule, Mapping)
                    else str
                )
                value_type = (
                    annotation_from_rule(cast(Mapping[str, Any], value_rule), names)
                    if isinstance(value_rule, Mapping)
                    else Any
                )
                annotation = dict[key_type, value_type]
            else:
                annotation = _base_annotation(type_name)

    if typed_rule.get("nullable") and type(None) not in get_args(annotation):
        annotation = _union([annotation, type(None)])
    return annotation


def render_annotation(annotation: Any) -> str:
    if annotation is Any:
        return "Any"
    if annotation is type(None):
        return "None"
    if isinstance(annotation, ForwardRef):
        return annotation.__forward_arg__

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Literal:
        return f"Literal[{', '.join(_literal_repr(value) for value in arguments)}]"
    if origin in (Union, types.UnionType):
        return " | ".join(render_annotation(argument) for argument in arguments)
    if origin in (list, dict, set, tuple):
        if origin is tuple and len(arguments) == 2 and arguments[1] is Ellipsis:
            return f"tuple[{render_annotation(arguments[0])}, ...]"
        rendered_arguments = ", ".join(
            render_annotation(argument) for argument in arguments
        )
        return f"{origin.__name__}[{rendered_arguments}]"
    if annotation is date or annotation is datetime:
        return annotation.__name__
    if isinstance(annotation, type):
        return annotation.__name__
    return "Any"


def _literal_repr(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if value is True:
        return "True"
    if value is False:
        return "False"
    if value is None:
        return "None"
    return repr(value)


def render_stub(root: Path = PROJECT_ROOT) -> str:
    schemas = load_json_schemas(root)
    names = class_names(schemas)
    init_declarations: list[str] = []
    class_declarations: list[str] = []
    rendered_annotations: list[str] = []

    for schema_name, schema in schemas.items():
        generated_name = names[schema_name]
        init_name = f"{generated_name}Kwargs"
        init_declarations.append(f"class {init_name}(TypedDict, total=False):")
        init_fields: list[str] = []
        fields: list[str] = []
        for field_name, rule in schema.items():
            if not field_name.isidentifier() or keyword.iskeyword(field_name):
                continue
            rule_mapping: Mapping[str, Any] = (
                cast(Mapping[str, Any], rule)
                if isinstance(rule, Mapping)
                else cast(Mapping[str, Any], {})
            )
            input_type = annotation_from_rule(rule_mapping, names)
            input_annotation = render_annotation(input_type)
            rendered_annotations.append(input_annotation)
            optional = (
                not rule_mapping.get("required", False)
                or "default" in rule_mapping
            )
            read_type = input_type
            if optional and "default" not in rule_mapping:
                read_type = _union([input_type, type(None)])
            read_annotation = render_annotation(read_type)
            rendered_annotations.append(read_annotation)
            field_presence = "NotRequired" if optional else "Required"
            init_fields.append(
                f"    {field_name}: {field_presence}[{input_annotation}]"
            )
            fields.append(f"    {field_name}: {read_annotation}")
        init_declarations.extend(init_fields or ["    pass"])
        init_declarations.append("")
        class_declarations.append(f"class {generated_name}(Scheme):")
        class_declarations.extend(fields or ["    pass"])
        class_declarations.append(
            f"    def __init__(self, **kwargs: Unpack[{init_name}]) -> None: ..."
        )
        class_declarations.append("")

    imports = ["from collections.abc import Mapping", "from typing import Any"]
    if any("Literal[" in annotation for annotation in rendered_annotations):
        imports.append("from typing import Literal")
    datetime_types = {
        annotation
        for annotation in ("date", "datetime")
        if any(re.search(rf"\b{annotation}\b", item) for item in rendered_annotations)
    }
    if datetime_types:
        imports.append(f"from datetime import {', '.join(sorted(datetime_types))}")

    imports = [
        *imports,
        "from typing import NotRequired, Required, TypedDict, Unpack",
    ]
    lines = [
        "# Generated by python -m framework.service.scheme_codegen; do not edit.",
        *imports,
        "from framework.service.scheme import Scheme",
        "",
        *init_declarations,
        *class_declarations,
        "SCHEME_TYPES: dict[str, type[Scheme]]",
        "",
        "def bind_schemas(schemas: Mapping[str, Any]) -> None: ...",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Genera gli stub Pyright dagli schemi JSON del progetto."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="segnala se il file generato non è aggiornato senza modificarlo",
    )
    arguments = parser.parse_args(argv)

    output = PROJECT_ROOT / STUB_PATH
    generated = render_stub(PROJECT_ROOT)
    current = output.read_text(encoding="utf-8") if output.exists() else ""
    if arguments.check:
        if current != generated:
            print(
                f"{output} non è aggiornato; esegui "
                "PYTHONPATH=src venv/bin/python -m framework.service.scheme_codegen",
                file=sys.stderr,
            )
            return 1
        print(f"Stub aggiornato: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generated, encoding="utf-8")
    print(f"Generato {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())