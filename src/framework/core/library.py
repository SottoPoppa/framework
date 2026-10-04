"""Libreria standard del DSL.

Funzioni builtin disponibili a ogni programma. Non conoscono sessioni, Manager
o runtime: operano solo su dati.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Dict, cast

from framework.service.introspection import Reflection


def map_records(
    records: Any, builder: Any, *args: Any, **kwargs: Any
) -> list[Any]:
    if not isinstance(records, (list, tuple)) or not callable(builder):
        return []
    records = cast(list[Any] | tuple[Any, ...], records)
    return [
        builder(record, *args, **kwargs)
        for record in records
        if isinstance(record, Mapping)
    ]


def variants(tags: Any) -> list[Any]:
    if not isinstance(tags, Mapping):
        return []
    tags = cast(Mapping[Any, Any], tags)
    records: list[Any] = []
    for key, values in tags.items():
        values = (
            list(cast(Mapping[Any, Any], values).keys())
            if isinstance(values, Mapping)
            else values
        )
        if not isinstance(values, (list, tuple, set)):
            continue
        records.extend(
            {"key": key, "value": value}
            for value in cast(Iterable[Any], values)
        )
    return records


def tag_variants(tags: Any) -> list[Any]:
    return [
        {
            "inputs": (
                None,
                record["key"],
                {} if record["value"] == record["key"] else {"type": record["value"]},
                ["fixture"],
            ),
            "note": f"Composizione {record['key']}:{record['value']}",
        }
        for record in variants(tags)
    ]


def prefix_match(field: str, prefix: str) -> Callable[[Any], bool]:
    def matches(record: Any) -> bool:
        if isinstance(record, str) and field == "relative_path":
            return record.startswith(prefix)
        if not isinstance(record, Mapping):
            return False
        record_mapping = cast(Mapping[str, Any], record)
        return str(record_mapping.get(field, "")).startswith(prefix)

    return matches


def tuple_filter_tuple(
    records: Any, predicate: Any
) -> tuple[Any, ...]:
    if not isinstance(records, (list, tuple)) or not callable(predicate):
        return ()
    records = cast(list[Any] | tuple[Any, ...], records)
    return tuple(record for record in records if predicate(record))


def flatten_records(records: Any) -> list[Any]:
    """Appiattisce liste annidate di record in una lista singola."""
    if isinstance(records, dict):
        return [records]
    if isinstance(records, (list, tuple)):
        flat: list[Any] = []
        for item in cast(list[Any] | tuple[Any, ...], records):
            flat.extend(flatten_records(item))
        return flat
    return [records] if records else []


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _keys(value: Any) -> list[Any]:
    if not isinstance(value, Mapping):
        return []
    return list(cast(Mapping[Any, Any], value).keys())


def _values(value: Any) -> list[Any]:
    if not isinstance(value, Mapping):
        return []
    return list(cast(Mapping[Any, Any], value).values())


def _union(left: Any, right: Any) -> dict[Any, Any]:
    return {**left, **right}


def _print(*values: Any) -> tuple[Any, ...]:
    print(*values)
    return values


def _pass(*values: Any) -> tuple[Any, ...]:
    return values


def _random(minimum: Any, maximum: Any) -> int:
    return random.randint(int(minimum), int(maximum))


def _format(template: Any, *values: Any) -> str:
    return str(template).format(*values)


def _result(value: Any = None) -> Any:
    return value


BUILTINS: Dict[str, Any] = {
    "map_records": map_records,
    "tag_variants": tag_variants,
    "keys": _keys,
    "values": _values,
    "union": _union,
    "print": _print,
    "pass": _pass,
    "int": int,
    "str": str,
    "bool": bool,
    "random": _random,
    "format": _format,
    "result": _result,
    "utc_now": utc_now,
    "file_dependencies": Reflection.file_dependencies,
    "prefix_match": prefix_match,
    "tuple_filter_tuple": tuple_filter_tuple,
}
