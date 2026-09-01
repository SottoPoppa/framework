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
    return await flow.pipe(
        data,
        flow.map_get_value(path, default),
        action="get_pipeline",
    )


@flow.result(action="data.set", component="accessor")
async def put(data: Any = None, path: str = "", value: Any = None) -> flow.Result:
    """
    Imposta un valore in modo immutabile.
    Supporta l'uso diretto `await set(data, path, value)` o curried per le pipe.
    """
    return await flow.pipe(
        data,
        flow.map_put_map(path, value),
        action="put_pipeline",
    )

@flow.result(action="data.transform", component="transformer")
async def transform(
    data_dict: dict,
    mapper: dict,
    source: str,
    direction: str = "external_to_model",
) -> flow.Result:
    """
    Traduce i dati tra un provider esterno e il modello interno.

    `mapper` usa il campo del modello interno come chiave e associa a ogni
    provider il path del campo esterno:

        {
            "username": {"github": "login", "google": "email"},
            "email": {"github": "email"}
        }

    Con `direction="external_to_model"` (default), legge i path esterni e
    restituisce il modello interno. Con `direction="model_to_external",
    inverte il mapping e restituisce i campi del provider.
    """
    if direction not in {"external_to_model", "model_to_external"}:
        raise ValueError(
            "direction deve essere 'external_to_model' o 'model_to_external'"
        )

    return await flow.pipe(
        # Crea il contesto con i dati, il mapper, il provider e la direzione.
        {"data": data_dict, "mapper": mapper, "source": source, "direction": direction},

        # Isola il mapper e seleziona il provider richiesto.
        flow.map_get_value("mapper"),
        # Normalizza ogni regola nella coppia (chiave_output, path_input):
        # (campo_interno, path_esterno) in ingresso e (path_esterno,
        # campo_interno) in uscita.
        flow.map_select_key_tuple(
            source,
            reverse=direction == "model_to_external",
        ),

        # Mantiene solo le coppie il cui path di input esiste nei dati.
        flow.tuple_filter_tuple(
            lambda item: flow.map_get_value(item[1])(data_dict) is not None
        ),

        # Converte ogni coppia in {chiave_output: valore_input}.
        flow.tuple_map_tuple(
            lambda item: {item[0]: flow.map_get_value(item[1])(data_dict)}
        ),

        # Fonde i campi adattati nel modello interno finale.
        flow.tuple_merge_map(),
        action="transform_pipeline"
    )


def normalize(value: Any, schema: dict) -> flow.Result:
    """Normalizza e valida un dizionario tramite pipeline sincrona."""
    validator = Validator(schema)

    return flow.pipe_sync(
        value,
        flow.flow_ensure_value(
            validator.validate,
            lambda document: str(validator.errors),
            lambda document: validator.document,
        ),
        flow.map_freeze_map(),
        action="normalize_pipeline",
    )

class Scheme(flow.Immutable):
    """Dict immutabile basato su schema nativo."""
    SCHEME: dict[str, dict[str, Any]] = {}

    def __init__(self, *args, **kwargs):
        input_data = args[0] if (args and isinstance(args[0], dict) and not kwargs) else kwargs
        result = normalize(input_data, self.SCHEME)
        if not result.is_success:
            raise result.output.error
        super().__init__(result.output.value)