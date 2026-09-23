"""Libreria standard del DSL.

Funzioni builtin disponibili a ogni programma. Non conoscono sessioni, Manager
o runtime: operano solo su dati.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any, Dict

from framework.service.introspection import Reflection


def map_records(records: Any, builder: Any, *args, **kwargs) -> list:
    if not isinstance(records, (list, tuple)) or not callable(builder):
        return []
    return [
        builder(record, *args, **kwargs)
        for record in records
        if isinstance(record, Mapping)
    ]


def variants(tags: Any) -> list:
    if not isinstance(tags, Mapping):
        return []
    records = []
    for key, values in tags.items():
        values = list(values.keys()) if isinstance(values, Mapping) else values
        if not isinstance(values, (list, tuple, set)):
            continue
        records.extend({"key": key, "value": value} for value in values)
    return records


def tag_variants(tags: Any) -> list:
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


def prefix_match(field: str, prefix: str):
    return lambda record: (
        str(record).startswith(str(prefix))
        if isinstance(record, str) and field == "relative_path"
        else isinstance(record, Mapping)
        and str(record.get(field, "")).startswith(str(prefix))
    )


def tuple_filter_tuple(records: Any, predicate: Any) -> tuple:
    if not isinstance(records, (list, tuple)) or not callable(predicate):
        return ()
    return tuple(record for record in records if predicate(record))


def flatten_records(records: Any) -> list:
    """Appiattisce liste annidate di record in una lista singola."""
    if isinstance(records, dict):
        return [records]
    if isinstance(records, (list, tuple)):
        flat = []
        for item in records:
            flat.extend(flatten_records(item))
        return flat
    return [records] if records else []


BUILTINS: Dict[str, Any] = {
    "map_records": map_records,
    "tag_variants": tag_variants,
    "keys": lambda value: list(value.keys()) if isinstance(value, Mapping) else [],
    "values": lambda value: list(value.values()) if isinstance(value, Mapping) else [],
    "union": lambda left, right: {**left, **right},
    "print": lambda *values: (print(*values), values)[1],
    "pass": lambda *values: values,
    "int": int,
    "str": str,
    "bool": bool,
    "random": lambda minimum, maximum: random.randint(int(minimum), int(maximum)),
    "format": lambda template, *values: str(template).format(*values),
    "result": lambda value=None: value,
    "file_dependencies": Reflection.file_dependencies,
    "prefix_match": prefix_match,
    "tuple_filter_tuple": tuple_filter_tuple,
}
