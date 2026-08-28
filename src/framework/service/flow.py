"""
framework.service.flow
======================

Orchestrazione async e metadati sopra ``returns.result.Result``.
 Programmazione DATA-DRIVEN con tracciamento completo Input/Output.
"""

from typing import Generic, TypeVar, Any, Sequence, Callable
import inspect
import time

T = TypeVar("T")
F = TypeVar("F")


class Scheme(dict):
    """Dict immutabile che genera l'__init__ in automatico dallo SCHEMA."""

    SCHEME: dict[str, dict[str, Any]] = {}

    def __init__(self, *args, **kwargs):
        if args and isinstance(args[0], dict) and not kwargs:
            input_data = args[0]
        else:
            input_data = kwargs

        validated_data = self._validate_and_clean(input_data)

        # Deep Freeze senza ricorsione infinita su istanze Scheme già create
        frozen_data = {}
        for key, value in validated_data.items():
            if isinstance(value, Scheme):
                frozen_data[key] = value
            elif isinstance(value, dict):
                frozen_data[key] = Scheme(value)
            elif isinstance(value, (list, tuple)):
                frozen_data[key] = tuple(
                    v if isinstance(v, Scheme) else (Scheme(v) if isinstance(v, dict) else v)
                    for v in value
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

            if field in data:
                value = data[field]
            elif has_default:
                def_val = rules["default"]
                value = def_val.copy() if isinstance(def_val, (dict, list)) else def_val
            elif not is_required:
                value = None
            else:
                raise ValueError(f"[{cls.__name__}] Campo obbligatorio mancante: '{field}'")

            if value is None:
                if is_required and not is_nullable:
                    raise ValueError(f"[{cls.__name__}] Il campo '{field}' non può essere None")
                cleaned[field] = None
                continue

            expected_type = rules.get("type")
            if expected_type and not isinstance(value, Scheme):
                if expected_type == "number" and isinstance(value, (int, float)):
                    pass
                elif isinstance(expected_type, tuple) and not isinstance(value, expected_type):
                    raise TypeError(
                        f"[{cls.__name__}] Il campo '{field}' deve essere uno tra {expected_type}, "
                        f"ricevuto {type(value).__name__}"
                    )
                elif isinstance(expected_type, type) and not isinstance(value, expected_type):
                    raise TypeError(
                        f"[{cls.__name__}] Il campo '{field}' deve essere '{expected_type.__name__}', "
                        f"ricevuto {type(value).__name__}"
                    )

            cleaned[field] = value

        return cleaned

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

    def __init__(self, value: T):
        super().__init__(is_success=True, value=value)


class Failure(Scheme, Generic[F]):
    SCHEME = {
        "is_success": {"type": bool, "required": True, "default": False},
        "error": {"required": True, "nullable": True}
    }

    def __init__(self, error: F):
        super().__init__(is_success=False, error=error)


class Result(Scheme, Generic[T, F]):
    SCHEME = {
        "output": {"required": True},
        "input": {"required": False, "nullable": True, "default": None},
        "execution_time_ms": {"type": "number", "required": False, "default": 0.0},
        "action": {"type": str, "required": False, "nullable": True, "default": None},
        "component": {"type": str, "required": False, "nullable": True, "default": None},
        "diagnostics": {"type": dict, "required": False, "default": {}},
        "transactions": {"type": (tuple, list), "required": False, "default": ()}
    }

    @property
    def is_success(self) -> bool:
        """Restituisce True se l'output finale è un Success."""
        return self.output.is_success

    @property
    def failed_step(self) -> "Result | None":
        """Restituisce la transazione che ha causato l'errore (se presente)."""
        if self.is_success:
            return None
        return self.transactions[-1] if self.transactions else None

    @property
    def successful_transactions(self) -> tuple["Result", ...]:
        """Restituisce solo le transazioni che si sono concluse con successo (utili per il Rollback)."""
        return tuple(tx for tx in self.transactions if tx.output.is_success)


# ==============================================================================
# HELPERS INTERNI ED ESECUZIONE PIPELINE
# ==============================================================================

Step = Callable[..., Any]
Valor = Success[Any] | Failure[Any]


def _normalize_result(raw: Any) -> Valor:
    if isinstance(raw, Result):
        return raw.output
    if isinstance(raw, (Success, Failure)):
        return raw
    if isinstance(raw, Exception):
        return Failure(error=raw)
    return Success(value=raw)


async def _invoke(step: Step, *args: Any, **kwargs: Any) -> Valor:
    try:
        out = step(*args, **kwargs)
        if inspect.isawaitable(out):
            out = await out
        return _normalize_result(out)
    except Exception as exc:
        return Failure(error=exc)


def _as_raw_step(fn: Step) -> Step:
    setattr(fn, "__flow_raw__", True)
    return fn


async def _call_step(step: Step, value: Any) -> Valor:
    if getattr(step, "__flow_raw__", False):
        return await _invoke(step, value)

    if isinstance(value, dict) and all(isinstance(k, str) for k in value.keys()):
        return await _invoke(step, **value)

    if isinstance(value, tuple):
        return await _invoke(step, *value)

    return await _invoke(step, value)


async def pipe(
    value: Any, 
    *steps: Step, 
    action: str = "flow.pipe",
    component: str | None = None
) -> Result:
    pipeline_started_at = time.perf_counter()
    transactions: list[Result] = []
    
    current_valor: Valor = _normalize_result(value)

    for step in steps:
        if not current_valor.is_success:
            break
            
        step_started_at = time.perf_counter()
        step_name = getattr(step, "__name__", str(step))
        
        # L'input di QUESTO step è il valore corrente
        step_input = current_valor.value
        
        # Esecuzione
        current_valor = await _call_step(step, step_input)
        step_time = (time.perf_counter() - step_started_at) * 1000
        
        # Registriamo SOLO gli step effettivi
        transactions.append(Result(
            input=step_input,
            output=current_valor,
            execution_time_ms=step_time,
            action=step_name,
            component=component
        ))

    # Il Result finale contiene l'input iniziale globale e la lista delle transazioni reali
    return Result(
        input=value,
        output=current_valor,
        execution_time_ms=(time.perf_counter() - pipeline_started_at) * 1000,
        action=action,
        component=component,
        transactions=tuple(transactions)
    )

from functools import wraps
from typing import Sequence, Callable, Any
import asyncio

def result(
    inputs: Sequence[str] | str | None = None,
    outputs: Sequence[str] | str | None = None,
) -> Callable:
    """Decoratore di confine che incapsula l'esecuzione di una funzione in un Result tramite pipe."""

    def decorator(func: Callable) -> Callable:
        
        async def _execute_wrapped_func(*args: Any, **kwargs: Any) -> Any:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Result:
            # Prepariamo l'input da tracciare per la pipe
            input_payload = args if args and not kwargs else (kwargs if kwargs and not args else (args, kwargs) if args and kwargs else None)
            
            return await pipe(
                input_payload if input_payload is not None else {},
                _as_raw_step(lambda _: _execute_wrapped_func(*args, **kwargs)),
                action=getattr(func, "__qualname__", repr(func)),
                component=getattr(func, "__module__", None),
            )

        return wrapper

    return decorator