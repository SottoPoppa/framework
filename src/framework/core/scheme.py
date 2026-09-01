import re
import json
import hashlib
import copy
from typing import Any, Callable, Dict, List, Tuple
from collections.abc import Mapping
from functools import partial

try:
    import tomllib as tomli
except ImportError:
    import tomli

from jinja2 import Environment
from cerberus import Validator

import framework.core.flow as flow

# ==============================================================================
# API PUBBLICA UNIFICATA (Tutte basate su Pipe)
# ==============================================================================

@flow.result(action="data.get", component="accessor")
async def get(data: Any = None, path: str = "", default: Any = None) -> flow.Result:
    """
    Estrae un valore da strutture annidate.
    Supporta l'uso diretto `await get(data, path)` o curried per le pipe.
    """
    return await pipe(
        {"data": data, "path": path, "default": default},
        _get_path_step,
        action="get_pipeline"
    )


@flow.result(action="data.set", component="accessor")
async def put(data: Any = None, path: str = "", value: Any = None) -> flow.Result:
    """
    Imposta un valore in modo immutabile.
    Supporta l'uso diretto `await set(data, path, value)` o curried per le pipe.
    """
    return await pipe(
        {"data": data, "path": path, "value": value},
        _set_path_step,
        action="set_pipeline"
    )

@flow.result(action="data.transform", component="transformer")
async def transform(data_dict: dict, mapper: dict, values: dict, input_data: dict, output_data: dict) -> flow.Result:
    """
    Trasforma e proietta dizionari riutilizzando direttamente l'API pubblica get().
    """
    async def _project(ctx: dict) -> dict:
        d, m, out = ctx["data"], ctx["mapper"], ctx["output"]
        translated = {}

        for k, v in m.items():
            res = await get(d, k)
            val = res.output.value if res.is_success else None
            
            if val is not None and isinstance(v, dict):
                out_key = v.get("out") or k
                translated[out_key] = val
                
        for f in d.keys():
            if f in out:
                res = await get(d, f)
                if res.is_success and res.output.value is not None:
                    translated[f] = res.output.value

        return translated

    return await pipe(
        {"data": data_dict, "mapper": mapper, "output": output_data},
        _project,
        action="transform_pipeline"
    )


@flow.result(action="normalize")
async def normalize(value: Any, schema: dict) -> flow.Result:
    """Normalizza e valida dizionari o liste tramite pipeline ricorsiva."""
    validator = Validator(schema)
    return await flow.pipe(
        tuple(value.keys()) if isinstance(value, dict) else (),
        flow.tuple_filter_tuple(lambda k: k in schema),                                # solo campi nello schema
        flow.tuple_map_tuple(lambda k: {k: value[k]}),                                  # costruisce {k: value[k]}
        flow.tuple_validate_each_tuple(validator.validate, lambda kv: str(validator.errors)), # valida, fail-fast
        flow.tuple_merge_map(),                                                         # unisce in un unico map
    )

class Scheme(flow.Immutable):
    """Dict immutabile basato su schema nativo."""
    SCHEME: dict[str, dict[str, Any]] = {}

    def __init__(self, *args, **kwargs):
        input_data = args[0] if (args and isinstance(args[0], dict) and not kwargs) else kwargs
        super().__init__(self._validate_and_clean(input_data))

    @classmethod
    def _validate_and_clean(cls, data: dict[str, Any]) -> dict[str, Any]:
        if not cls.SCHEME and isinstance(data, dict):
            return {k: cls._freeze(v) for k, v in data.items()}

        cleaned = {}
        for field, rules in cls.SCHEME.items():
            req, nullable, has_def = rules.get("required", False), rules.get("nullable", False), "default" in rules

            if field in data:
                val = data[field]
            elif has_def:
                def_val = rules["default"]
                val = def_val.copy() if isinstance(def_val, (dict, list)) else def_val
            elif not req:
                val = None
            else:
                raise ValueError(f"[{cls.__name__}] Campo obbligatorio mancante: '{field}'")

            if val is None:
                if req and not nullable:
                    raise ValueError(f"[{cls.__name__}] Il campo '{field}' non può essere None")
                cleaned[field] = None
                continue

            expected_type = rules.get("type")
            if expected_type and not isinstance(val, flow.Immutable):
                if isinstance(expected_type, (type, tuple)) and not isinstance(val, expected_type):
                    raise TypeError(f"[{cls.__name__}] '{field}' deve essere {expected_type}, ricevuto {type(val).__name__}")

            cleaned[field] = cls._freeze(val)
        return cleaned