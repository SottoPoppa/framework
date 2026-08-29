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

from framework.core.flow import (
    result,
    pipe,
    Success,
    Failure,
    Result
)

jinja_env = Environment()

# ==============================================================================
# COMBINATORI GENERICI E ASINCRONI
# ==============================================================================

def map_flow(fn: Callable[[Any], Any]) -> Callable[[list], list]:
    """Applica una funzione ad ogni elemento di una lista in modo dichiarativo."""
    return lambda items: [fn(item) for item in items] if isinstance(items, list) else items

async def map_async_flow(async_fn: Callable[[Any], Any]) -> Callable[[list], Any]:
    """Applica una funzione asincrona ad ogni elemento di una lista."""
    async def _runner(items: list):
        if not isinstance(items, list):
            return items
        return [await async_fn(item) for item in items]
    return _runner

def filter_flow(pred: Callable[[Any], bool]) -> Callable[[list], list]:
    """Filtra una lista basandosi su un predicato."""
    return lambda items: [item for item in items if pred(item)] if isinstance(items, list) else items


# ==============================================================================
# REGISTRO DI CONVERSIONE DICHIARATIVO
# ==============================================================================

MAPPA = {
    (str, dict, ''): lambda v: v if isinstance(v, dict) else {},
    (dict, dict, ''): lambda v: v,
    (str, str, ''): lambda v: v,
    (str, dict, 'json'): lambda v: json.loads(v) if isinstance(v, str) else v if isinstance(v, dict) else {},
    (dict, dict, 'json'): lambda v: v,
    (dict, str, 'json'): lambda v: json.dumps(v, indent=4) if isinstance(v, dict) else v if isinstance(v, str) else '',
    (str, str, 'json'): lambda v: v,
    (str, str, 'hash'): lambda v: hashlib.sha256(v.encode('utf-8')).hexdigest() if isinstance(v, str) else '',
    (str, dict, 'toml'): lambda content: tomli.loads(content) if isinstance(content, str) else content if isinstance(content, dict) else {},
    (dict, dict, 'toml'): lambda v: v,
    (dict, str, 'toml'): lambda data: tomli.dumps(data) if isinstance(data, dict) else data if isinstance(data, str) else '',
    (str, str, 'toml'): lambda v: v,
    (str, int, ''): lambda v: int(v) if isinstance(v, str) else v if isinstance(v, int) else 0,
    (int, str, ''): lambda v: str(v) if isinstance(v, int) else v if isinstance(v, str) else '',
    (str, bool, ''): lambda v: str(v).lower() == 'true',
    (bool, str, ''): lambda v: str(v) if isinstance(v, bool) else v if isinstance(v, str) else '',
    (str, list, ''): lambda v: [v],
    (type(None), list, ''): lambda v: [],
}


# ==============================================================================
# STEP ATOMICI INTERNI
# ==============================================================================

def _get_path_step(ctx: dict) -> Any:
    """Navigazione ricorsiva pura su dizionari e liste."""
    data = ctx["data"]
    path = ctx["path"]
    default = ctx.get("default")

    if not path:
        return data
    
    key, _, rest = path.partition(".")
    filter_match = re.match(r"([^\[]+)\[([^=]+)=[\"']?([^\"']+)[\"']?\]", key)
    
    if filter_match:
        key_base, attr, expected = filter_match.groups()
        target = (data if isinstance(data, (list, tuple)) else []) if key_base == "*" else (data.get(key_base, []) if isinstance(data, (dict, Mapping)) else [])
        filtered = [x for x in target if isinstance(x, dict) and str(x.get(attr)) == expected]
        results = [_get_path_step({"data": item, "path": rest, "default": default}) for item in filtered]
        return results if results else default

    if key == "*":
        return [_get_path_step({"data": x, "path": rest, "default": default}) for x in data] if isinstance(data, (list, tuple)) else default
        
    try:
        if isinstance(data, (dict, Mapping)):
            value = data.get(key, default)
        elif isinstance(data, (list, tuple)) and key.lstrip("-").isdigit():
            idx = int(key)
            value = data[idx] if 0 <= idx < len(data) else default
        else:
            value = getattr(data, key, default)
            
        return _get_path_step({"data": value, "path": rest, "default": default}) if rest else value
    except Exception:
        return default


def _set_path_step(ctx: dict) -> Any:
    """Impostazione immutabile di un valore in una struttura annidata."""
    data = copy.deepcopy(ctx["data"]) if ctx["data"] is not None else {}
    path = ctx["path"]
    value = ctx["value"]

    if not path:
        return value

    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        if isinstance(current, dict):
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        else:
            raise TypeError(f"Impossibile accedere al path '{path}': elemento intermedio non è un dizionario.")
            
    if isinstance(current, dict):
        current[keys[-1]] = value
    return data


def _lookup_conversion(args: Tuple[Any, type, str]) -> Callable:
    target, output_type, input_mode = args
    if type(target) == output_type:
        return lambda: target
    
    key = (type(target), output_type, input_mode)
    if key not in MAPPA:
        raise ValueError(f"Conversione non supportata: {type(target)} -> {output_type}")
    
    return lambda: MAPPA[key](target)


def _apply_defaults_and_helpers(ctx: dict) -> dict:
    value = dict(ctx["value"])
    schema = copy.deepcopy(ctx["schema"])

    for field, rules in list(schema.items()):
        val = value.get(field)
        if isinstance(rules, dict):
            if 'default' in rules:
                if rules['default'] == 'time.now.utc()':
                    from datetime import datetime
                    value[field] = str(datetime.now())
                elif rules['default'] == 'uuid.uuid4()':
                    import uuid
                    value[field] = str(uuid.uuid4())

            if 'convert' in rules and field in value:
                c_type = rules.pop('convert')
                if (type(val), c_type, '') in MAPPA:
                    value[field] = MAPPA[(type(val), c_type, '')](val)
            
            rules.pop('comment', None)

    return {"value": value, "schema": schema}


def _validate_schema(ctx: dict) -> dict:
    v = Validator(ctx["schema"], allow_unknown=False, purge_unknown=True)
    if not v.validate(ctx["value"]):
        errors = [{"field": k, "message": str(e)} for k, errs in v.errors.items() for e in errs]
        return {"data": None, "errors": errors}
    return {"data": v.document, "errors": None}


# ==============================================================================
# API PUBBLICA UNIFICATA (Tutte basate su Pipe)
# ==============================================================================

@result(action="data.get", component="accessor")
async def get(data: Any = None, path: str = "", default: Any = None) -> Result:
    """
    Estrae un valore da strutture annidate.
    Supporta l'uso diretto `await get(data, path)` o curried per le pipe.
    """
    return await pipe(
        {"data": data, "path": path, "default": default},
        _get_path_step,
        action="get_pipeline"
    )


@result(action="data.set", component="accessor")
async def put(data: Any = None, path: str = "", value: Any = None) -> Result:
    """
    Imposta un valore in modo immutabile.
    Supporta l'uso diretto `await set(data, path, value)` o curried per le pipe.
    """
    return await pipe(
        {"data": data, "path": path, "value": value},
        _set_path_step,
        action="set_pipeline"
    )


@result(action="data.convert", component="transformer")
async def convert(target: Any, output: type, input: str = '') -> Result:
    """Esegue la conversione di tipo tramite pipeline dichiarativa."""
    return await pipe(
        (target, output, input),
        _lookup_conversion,
        lambda thunk: thunk(),
        action="convert_pipeline"
    )


@result(action="string.format", component="formatter")
async def format(target: str, **constants) -> Result:
    """Formatta una stringa Jinja2 tramite pipeline."""
    def _render(ctx: Tuple[str, dict]) -> str:
        tgt, consts = ctx
        if not tgt or not isinstance(tgt, str) or '{' not in tgt:
            return tgt
        return jinja_env.from_string(tgt).render(consts)

    return await pipe(
        (target, constants),
        _render,
        action="format_pipeline"
    )


@result(action="schema.normalize", component="validator")
async def normalize(value: Any, schema: dict, mode: str = 'full') -> Result:
    """Normalizza e valida dizionari o liste tramite pipeline ricorsiva."""
    if isinstance(value, list):
        norm_item = lambda item: normalize(item, schema, mode)
        items_results = await (await map_async_flow(norm_item))(value)
        
        datas = [r.output.value["data"] for r in items_results if r.is_success and r.output.value.get("data") is not None]
        errors = [r.output.value["errors"] for r in items_results if r.is_success and r.output.value.get("errors") is not None]
        return {"data": datas, "errors": errors or None}

    if not isinstance(schema, Mapping) or not isinstance(value or {}, Mapping):
        return {"data": None, "errors": [{"field": "_root", "message": "Expected dict/mapping"}]}

    return await pipe(
        {"value": dict(value or {}), "schema": schema},
        _apply_defaults_and_helpers,
        _validate_schema,
        action="normalize_dict_pipeline"
    )


@result(action="data.transform", component="transformer")
async def transform(data_dict: dict, mapper: dict, values: dict, input_data: dict, output_data: dict) -> Result:
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