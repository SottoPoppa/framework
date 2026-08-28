"""
framework.service.flow
======================

Orchestrazione async e metadati sopra ``returns.result.Result``.
Programmazione DATA-DRIVEN con tracciamento completo Input/Output.
"""

from typing import Generic, TypeVar, Any, Sequence, Callable
from functools import wraps
import inspect
import time
import asyncio

T = TypeVar("T")
F = TypeVar("F")


class Scheme(dict):
    """Dict immutabile basato su schema nativo."""

    SCHEME: dict[str, dict[str, Any]] = {}

    def __init__(self, *args, **kwargs):
        input_data = args[0] if (args and isinstance(args[0], dict) and not kwargs) else kwargs
        validated_data = self._validate_and_clean(input_data)
        super().__init__(validated_data)

    @classmethod
    def _freeze_value(cls, value: Any) -> Any:
        if isinstance(value, Scheme):
            return value
        if isinstance(value, (list, tuple)):
            return tuple(cls._freeze_value(v) for v in value)
        return value

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
                if expected_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
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

            cleaned[field] = cls._freeze_value(value)

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
        return self.output.is_success

    @property
    def failed_step(self) -> "Result | None":
        if self.is_success:
            return None
        return self.transactions[-1] if self.transactions else None

    @property
    def successful_transactions(self) -> tuple["Result", ...]:
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


def _dispatch_args(step: Step, value: Any) -> tuple[tuple, dict]:
    """
    Dispatching STRICT e deterministico.
    Nessun fallback magico: i dizionari si mappano SOLO per chiave o tramite **options.
    """
    try:
        sig = inspect.signature(step)
    except (ValueError, TypeError):
        return (value,), {}

    params = sig.parameters
    num_params = len(params)

    # 1. La funzione non accetta parametri
    if num_params == 0:
        return (), {}

    # 2. Gestione Input Dict / Scheme
    if isinstance(value, dict):
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        matching_kwargs = {k: v for k, v in value.items() if k in params}

        # CASO A: Ha **options / **kwargs -> passa tutto il dict in modo esplicito
        if has_kwargs:
            return (), dict(value)

        # CASO B: Esistono chiavi del dict corrispondenti AI PARAMETRI -> passa solo quelle
        if matching_kwargs:
            return (), matching_kwargs

        # CASO C: Nessun parametro corrisponde e non c'è **options -> ERRORE TASSATIVO
        step_name = getattr(step, "__name__", str(step))
        raise ValueError(
            f"[{step_name}] Impossibile eseguire lo step: le chiavi del dizionario {list(value.keys())} "
            f"non corrispondono ai parametri richiesti dalla funzione {list(params.keys())}."
        )

    # 3. Gestione Tupla / Lista
    if isinstance(value, (tuple, list)):
        has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values())
        if has_varargs:
            return tuple(value), {}
        return tuple(value[:num_params]), {}

    # 4. Valore singolo primitivo o Istanza (NON dict)
    return (value,), {}


async def _invoke(step: Step, value: Any) -> Valor:
    try:
        args, kwargs = _dispatch_args(step, value)
        out = step(*args, **kwargs)
        if inspect.isawaitable(out):
            out = await out
        return _normalize_result(out)
    except Exception as exc:
        return Failure(error=exc)


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
        step_input = current_valor.value
        
        current_valor = await _invoke(step, step_input)
        step_time = (time.perf_counter() - step_started_at) * 1000
        
        transactions.append(Result(
            input=step_input,
            output=current_valor,
            execution_time_ms=step_time,
            action=step_name,
            component=component
        ))

    return Result(
        input=value,
        output=current_valor,
        execution_time_ms=(time.perf_counter() - pipeline_started_at) * 1000,
        action=action,
        component=component,
        transactions=tuple(transactions)
    )


def result(
    inputs: Sequence[str] | str | None = None,
    outputs: Sequence[str] | str | None = None,
) -> Callable:
    """Decoratore di confine che incapsula l'esecuzione di una funzione in un Result tramite pipe."""

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Result:
            input_keys = [inputs] if isinstance(inputs, str) else (inputs or [])
            output_keys = [outputs] if isinstance(outputs, str) else (outputs or [])
            
            input_payload = args if args and not kwargs else (kwargs if kwargs and not args else (args, kwargs) if args and kwargs else None)

            async def _main_step(_):
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)

            _main_step.__name__ = getattr(func, "__name__", "main_step")

            return await pipe(
                input_payload if input_payload is not None else {},
                _main_step,
                action=getattr(func, "__qualname__", repr(func)),
                component=getattr(func, "__module__", None),
            )

        return wrapper

    return decorator


def is_result(value: Any) -> bool:
    return isinstance(value, Result)


def output(value: Any) -> Any:
    if not is_result(value):
        return value
    return value.output.value if value.is_success else value.output.error


def success(value: Any = None) -> Result:
    return Result(output=Success(value))


def error(value: Any = None) -> Result:
    return Result(output=Failure(value))


def check(value: Any) -> bool:
    return not is_result(value) or value.is_success
