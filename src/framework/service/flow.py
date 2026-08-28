"""
framework.service.flow
======================

Orchestrazione async e metadati sopra ``returns.result.Result``.

Tutta la logica monadica (map, bind, rescue, alt, ecc.) è delegata a ``returns``.
Questo modulo gestisce esclusivamente:
- Programmazione DATA-DRIVEN (inputs/outputs)
"""

from typing import Generic, TypeVar, Any
import json

T = TypeVar("T")
F = TypeVar("F")

class Scheme(dict):
    """Dict immutabile che genera l'__init__ in automatico dallo SCHEMA."""
    
    SCHEME: dict[str, dict[str, Any]] = {}

    def __init__(self, *args, **kwargs):
        # Se viene passato un dict posizionale (es: Class({"a": 1})) o kwargs (es: Class(a=1))
        input_data = args[0] if args and isinstance(args[0], dict) else kwargs
        
        # 1. Validazione e popolamento dai default dello SCHEMA
        validated_data = self._validate_and_clean(input_data)
        
        # 2. Congelamento ricorsivo (Deep Frozen)
        frozen_data = {}
        for key, value in validated_data.items():
            if isinstance(value, dict) and not isinstance(value, Scheme):
                frozen_data[key] = Scheme(value)
            elif isinstance(value, (list, tuple)):
                frozen_data[key] = tuple(
                    Scheme(v) if isinstance(v, dict) else v for v in value
                )
            else:
                frozen_data[key] = value

        super().__init__(frozen_data)

    @classmethod
    def _validate_and_clean(cls, data: dict[str, Any]) -> dict[str, Any]:
        cleaned = {}

        for field, rules in cls.SCHEME.items():
            is_required = rules.get("required", False)
            is_nullable = rules.get("nullable", False)
            has_default = "default" in rules
            
            # Estrazione valore o fallback al default dello SCHEMA
            if field in data:
                value = data[field]
            elif has_default:
                # Se il default è mutabile (dict/list), ne creiamo una copia per sicurezza
                def_val = rules["default"]
                value = def_val.copy() if isinstance(def_val, (dict, list)) else def_val
            elif not is_required:
                value = None
            else:
                raise ValueError(f"[{cls.__name__}] Campo obbligatorio mancante: '{field}'")

            # Controllo Nullability
            if value is None:
                if is_required and not is_nullable:
                    raise ValueError(f"[{cls.__name__}] Il campo '{field}' non può essere None")
                cleaned[field] = None
                continue

            # Controllo Tipi
            '''expected_type = rules.get("type")
            if expected_type:
                if expected_type == "number" and isinstance(value, (int, float)):
                    pass
                elif not isinstance(value, expected_type):
                    raise TypeError(
                        f"[{cls.__name__}] Il campo '{field}' deve essere '{expected_type}', "
                        f"ricevuto {type(value).__name__}"
                    )

            cleaned[field] = value'''
            expected_type = rules.get("type")
            if expected_type and not isinstance(value, Scheme):
                if expected_type == "number" and isinstance(value, (int, float)):
                    pass
                elif not isinstance(value, expected_type):
                    raise TypeError(
                        f"[{cls.__name__}] Il campo '{field}' deve essere '{expected_type}', "
                        f"ricevuto {type(value).__name__}"
                    )

            cleaned[field] = value

        return cleaned

    # Dot Access & Immutabilità
    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"Campo '{item}' non presente in {self.__class__.__name__}")

    def __setattr__(self, key, value): raise TypeError(f"{self.__class__.__name__} è immutabile")
    def __setitem__(self, key, value): raise TypeError(f"{self.__class__.__name__} è immutabile")
    def __delitem__(self, key): raise TypeError(f"{self.__class__.__name__} è immutabile")


class Success(Scheme, Generic[T]):
    SCHEME = {
        "is_success": {"type": bool, "required": True, "default": True},
        "value": {"required": True, "nullable": True}
    }
    # Per praticità possiamo lasciare un costruttore veloce a posizionale singola
    def __init__(self, value: T):
        super().__init__(value=value)


class Failure(Scheme, Generic[F]):
    SCHEME = {
        "is_success": {"type": bool, "required": True, "default": False},
        "error": {"required": True, "nullable": True}
    }
    def __init__(self, error: F):
        super().__init__(error=error)


class Result(Scheme, Generic[T, F]):
    # TUTTO È DEFINITO QUI: tipi, obbligatorietà e valori di default!
    SCHEME = {
        "result": {"required": True},
        "execution_time_ms": {"type": "number", "required": False, "default": 0.0},
        "action": {"type": str, "required": False, "nullable": True, "default": None},
        "component": {"type": str, "required": False, "nullable": True, "default": None},
        "diagnostics": {"type": dict, "required": False, "default": {}},
        "transactions": {"type": (tuple, list), "required": False, "default": ()}
    }

# ==============================================================================
# HELPERS INTERNI DI INVOCAZIONE E DISPATCH
# ==============================================================================


import inspect
import time
from typing import Any, Callable, Sequence

# Definizione tipo per lo Step (può accettare posizionali o kwargs)
Step = Callable[..., Any]

Valor = Success[Any] | Failure[Any]

def _normalize_result(raw: Any) -> Valor:
    """Estrae o incapsula il valore in un Success o Failure di SchemaFrozenDict."""
    # Se è un FlowResult, estraiamo la sua proprietà interna 'result'
    if isinstance(raw, Result):
        return raw.result
    
    # Se è già un'istanza di Success o Failure, la restituiamo direttamente
    if isinstance(raw, (Success, Failure)):
        return raw
    
    # Se è un'eccezione, la incapsuliamo in Failure(error=...)
    if isinstance(raw, Exception):
        return Failure(error=raw)
    
    # Negli altri casi, incapsuliamo il valore restituito in Success(value=...)
    return Success(value=raw)


async def _invoke(step: Step, *args: Any, **kwargs: Any) -> Valor:
    """Esegue uno step (sync/async) convertendo eventuali eccezioni in Failure."""
    try:
        out = step(*args, **kwargs)
        if inspect.isawaitable(out):
            out = await out
        return _normalize_result(out)
    except Exception as exc:
        return Failure(error=exc)


def _as_raw_step(fn: Step) -> Step:
    """Marca uno step per essere eseguito passando il valore grezzo senza unpack."""
    setattr(fn, "__flow_raw__", True)
    return fn


async def _call_step(step: Step, value: Any) -> Valor:
    """Dispatch flessibile: dict -> **kwargs, tuple -> *args, altro -> arg singolo."""
    if getattr(step, "__flow_raw__", False):
        return await _invoke(step, value)

    # Se il valore in ingresso è un dict (o SchemaFrozenDict) usiamo i kwargs
    if isinstance(value, dict) and all(isinstance(k, str) for k in value.keys()):
        return await _invoke(step, **value)

    # Se è una tupla, spacchettiamo in posizionali (*args)
    if isinstance(value, tuple):
        return await _invoke(step, *value)

    return await _invoke(step, value)


def _flow_result(
    result: Any,
    started_at: float,
    action: str,
    component: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    transactions: Sequence[Any] = (),
    ) -> Result:
    """Crea una nuova istanza immutabile FlowResult partendo dallo SCHEMA."""
    return Result(
        result=_normalize_result(result),
        execution_time_ms=(time.perf_counter() - started_at) * 1000,
        action=action,
        component=component,
        diagnostics=diagnostics if diagnostics is not None else {},
        transactions=transactions,
    )

# ==============================================================================
# DECORATORE E ORCHESTRATORI PRINCIPALI
# ==============================================================================

async def pipe(
    value: Any, 
    *steps: Step, 
    action: str = "flow.pipe",
    component: str | None = None
) -> Result:
    """Pipeline asincrona sequenziale con corto-circuito sul primo Failure."""
    started_at = time.perf_counter()
    transactions: list[Result] = []
    
    # Normalizziamo il dato iniziale in un Success o Failure di SchemaFrozenDict
    current: Result = _normalize_result(Success(value))

    print(f"Starting pipeline with initial value: {current}, action: {action}, component: {component}")

    for step in steps:
        # Corto-circuito immediato se lo stato attuale è un Failure (oppure is_success is False)
        if not current.is_success:
            break
            
        # Passiamo il contenuto interno (.value) allo step successivo
        current = await _call_step(step, current.value)
        #print(f"Step '{step.__name__}' executed. Current result: {current}")
        transactions.append(current)
    transactions = tuple(transactions)  # Convertiamo in tupla per l'immutabilità
    print(f"Pipeline completed. Final result: {current}, Transactions: {transactions}")
    # Restituisce l'oggetto FlowResult immutabile tracciato
    return _flow_result(
        result=current,
        started_at=started_at,
        action=action,
        component=component,
        transactions=tuple(transactions)
    )

import asyncio

def result(
    inputs: Sequence[str] | str | None = None,
    outputs: Sequence[str] | str | None = None,
) -> Callable[[Step], Step]:
    """Decoratore di confine in stile puro e monadico."""

    def decorator(
        func,
    ):
        is_async = asyncio.iscoroutinefunction(func)

        async def _execute_wrapped_func(clean_kwargs: dict[str, Any]) -> Result[Any, Any]:
            if is_async:
                return _normalize_result(await func(**clean_kwargs))
            return _normalize_result(await asyncio.to_thread(func, **clean_kwargs))

        async def wrapper(*args, **kwargs) -> Result[Any, Any]:
            started_at = time.perf_counter()
            explicit_txs = tuple(kwargs.pop("_txs", ()))

            # Flusso di esecuzione completamente gestito tramite pipe_flow
            return await pipe(
                kwargs,
                #lambda kw: filter_kwargs(kw, inputs),
                _execute_wrapped_func,
                #lambda val: normalize_output(val, outputs),
            )

            '''return _flow_result(
                final_result,
                started_at=started_at,
                action=getattr(func, "__qualname__", repr(func)),
                component=getattr(func, "__module__", None),
                transactions=explicit_txs,
            )'''

        wrapper.__name__ = getattr(func, "__name__", "result_wrapper")
        wrapper.__qualname__ = getattr(func, "__qualname__", wrapper.__name__)
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator