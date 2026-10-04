import asyncio
import copy
import re
from functools import reduce as _reduce, wraps
import inspect
import time
import traceback
import contextvars
import uuid
from typing import (
    Any,
    Awaitable as _Awaitable,
    Callable,
    Generic,
    Iterable,
    Mapping,
    Never as _Never,
    ParamSpec as _ParamSpec,
    TypeAlias as _TypeAlias,
    TypeGuard,
    TypeVar,
    cast as _cast,
)

from framework.service.diagnostic import (
    get_logger,
    reset_log_context,
    set_log_context,
)
from framework.service.trace import (
    exception_location as _exception_location,
    failure_location as _failure_location,
    safe_value as _safe_log_value,
)

T = TypeVar("T")
F = TypeVar("F")
_P = _ParamSpec("_P")
Step = Callable[[Any], Any]
_NO_INITIAL = object()

_dev_logger = get_logger("flow")
_dev_logging_enabled = False
_dev_sinks: list[Callable[..., Any]] = []
_trace_state: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "flow_trace_state",
    default=None,
)


def request_boundary(
    func: Callable[_P, Any],
) -> Callable[_P, _Awaitable[Any]]:
    """Isola una nuova richiesta root dal contesto di una task longeva."""
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any):
        trace_token = _trace_state.set(None)
        log_token = set_log_context({})
        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        finally:
            _trace_state.reset(trace_token)
            reset_log_context(log_token)

    return wrapper


class LocatedError(ValueError):
    """Errore con posizione nel sorgente usabile dalla diagnostica Flow."""

    def __init__(self, message: str, **location: Any) -> None:
        super().__init__(message)
        self.location = {
            key: value for key, value in location.items() if value is not None
        }


class FlowError(ValueError):
    """Eccezione per un Failure il cui payload non è un'eccezione Python."""

    def __init__(self, value: Any) -> None:
        self.value = value
        super().__init__(str(value))


def configure_dev_logging(
    enabled: bool = False,
) -> None:
    """Abilita o disabilita il tracing Flow senza persistenza su file."""
    global _dev_logging_enabled
    _dev_logging_enabled = bool(enabled)


def set_dev_sink(sink: Callable[..., Any] | None = None) -> None:
    """Imposta il destinatario runtime degli eventi di tracing Flow.

    Il core non conosce l'interfaccia che visualizza gli eventi: un adapter può
    registrare una callback e decidere se stamparli, mostrarli nella UI o
    inoltrarli a un altro canale. Il tracing Flow non viene mai persistito su file.
    """
    _dev_sinks.clear()
    if sink is not None:
        _dev_sinks.append(sink)


def _request_metadata(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    for value in (*args, *kwargs.values()):
        if not hasattr(value, "id") or not hasattr(value, "context"):
            continue
        details = {"session_id": str(value.id)}
        authentication = getattr(value, "authentication", {})
        if isinstance(authentication, dict):
            authentication_data = _cast(dict[str, Any], authentication)
            actor = (
                authentication_data.get("user_id")
                or authentication_data.get("username")
                or authentication_data.get("email")
            )
            if actor is not None:
                details["actor"] = str(actor)
        return details
    return {}


def _enter_trace(operation: str, args: tuple[Any, ...], kwargs: dict[str, Any]):
    parent = _trace_state.get()
    request = _request_metadata(args, kwargs)
    trace_id = parent["trace_id"] if parent else uuid.uuid4().hex[:10]
    path = f"{parent['path']} > {operation}" if parent else operation
    state = dict(parent or {})
    state.setdefault("failure_state", (parent or {}).get("failure_state", {}))
    state.update(request)
    state.update(trace_id=trace_id, path=path)
    return _trace_state.set(state)


def _trace_metadata() -> dict[str, Any]:
    state = _trace_state.get()
    if state is None:
        return {}
    metadata: dict[str, str] = {}
    if "trace_id" in state:
        metadata["trace_id"] = state["trace_id"]
    if "path" in state:
        chain_nodes = state["path"].split(" > ")
        logical_nodes = [
            node
            for node in chain_nodes
            if not node.rsplit(".", 1)[-1].startswith("_")
        ]
        metadata["stage"] = logical_nodes[-1] if logical_nodes else chain_nodes[-1]
        metadata["chain"] = " > ".join(logical_nodes or chain_nodes)
    for key in ("session_id", "actor"):
        if key in state:
            metadata[key] = state[key]
    return metadata


def dev_log(
    message: str,
    *args: Any,
    exc_info: bool = False,
    exception: BaseException | None = None,
    **metadata: Any,
) -> None:
    if _dev_logging_enabled:
        metadata = {**_trace_metadata(), **metadata}
        state = _trace_state.get()
        if metadata.get("success") is False and message in {"result.end", "pipe.result", "pipe_sync.result"}:
            signature = (
                metadata.get("error_type"),
                metadata.get("error_message"),
            )
            failure_state = state.get("failure_state") if state is not None else None
            if failure_state is not None and failure_state.get("signature") == signature:
                metadata = {**metadata, "propagated": True}
            elif failure_state is not None:
                failure_state["signature"] = signature
        if exception is not None:
            metadata = {
                **_exception_location(exception),
                **metadata,
            }
        rendered = message % args if args else message
        for sink in tuple(_dev_sinks):
            try:
                sink(
                    rendered,
                    exception=exception,
                    level="ERROR" if exc_info or metadata.get("success") is False else "DEBUG",
                    metadata=metadata,
                )
            except Exception as sink_error:
                _dev_logger.warning(
                    f"flow.sink.error sink={sink!r} error={sink_error!r}"
                )
        if not _dev_sinks:
            logger_metadata = dict(metadata)
            if "component" in logger_metadata:
                logger_metadata["flow_component"] = logger_metadata.pop("component")
            if exc_info or metadata.get("success") is False:
                _dev_logger.error(rendered, exception=exception, **logger_metadata)
            else:
                _dev_logger.debug(rendered, **logger_metadata)


# ==============================================================================
# CHANGELOG rispetto all'originale
# ==============================================================================
# 1. Immutable._freeze ora e' davvero ricorsiva: i dict annidati diventano
#    Immutable (non dict "nudi" mutabili) e Immutable e' ora hashable.
# 2. tuple_unique_tuple() beneficia automaticamente del fix (1): tuple di Success/
#    Failure/Result/Immutable ora sono hashabili con la key_fn di default.
# 3. tuple_reduce_value usa un sentinel dedicato invece di None per "initial",
#    cosi' None e' un valore iniziale legittimo.
# 4. pipe_tap_value / pipe_foreach_tuple ora supportano correttamente funzioni async
#    (prima la coroutine veniva creata e scartata senza essere awaitata).
# 5. map_pick_map preserva l'Immutable-ness dell'input, come fa gia' map_compute_value.
# 6. tuple_merge_map solleva TypeError su elementi non-dict invece di
#    ignorarli in silenzio (con opzione skip_invalid per il vecchio comportamento).
# 7. tuple_zip_tuple materializza l'iterable passato (niente piu' generatori che si
#    esauriscono al primo uso) e puo' segnalare mismatch di lunghezza.
# 8. _named prova a ricavare un nome leggibile anche per le lambda, per
#    step tracing/debug piu' utili in result.transactions.
# ==============================================================================


def _fn_label(fn: Callable[..., Any]) -> str:
    """Restituisce un'etichetta leggibile per una funzione, incluse le lambda."""
    name = getattr(fn, "__name__", None)
    if name and name != "<lambda>":
        return name
    try:
        src = inspect.getsource(fn).strip()
        # tiene solo la parte della lambda su una riga, troncata
        return (src[:40] + "...") if len(src) > 40 else src
    except (OSError, TypeError):
        return repr(fn)


def _named(fn: Callable[_P, T], name: str) -> Callable[_P, T]:
    """Assegna un nome descrittivo alle closure per l'ispezione della pipeline."""
    fn.__name__ = name
    return fn


# ==============================================================================
# STRUTTURE DATI IMMUTABILI E RISULTATI
# ==============================================================================

class Immutable(dict[Any, Any]):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        input_data: dict[Any, Any] = (
            _cast(dict[Any, Any], args[0])
            if args and isinstance(args[0], dict) and not kwargs
            else kwargs
        )
        super().__init__(self._freeze(input_data))

    @classmethod
    def _freeze(cls, val: Any) -> Any:
        if isinstance(val, Immutable):
            return val
        # FIX(1): il ramo dict ora avvolge ricorsivamente in Immutable, non
        # produce piu' un dict "nudo" mutabile ai livelli annidati.
        #
        # NB: qui NON si puo' scrivere `cls({...})` (o `Immutable({...})`):
        # invocare il costruttore rientrerebbe in __init__, che richiama di
        # nuovo _freeze sullo stesso contenuto gia' processato, causando una
        # ricorsione infinita. Si costruisce quindi l'oggetto direttamente
        # con dict.__new__/dict.__init__, bypassando __init__ di Immutable.
        # I livelli annidati diventano sempre Immutable "puro" (non Success/
        # Failure/Result, anche se cls e' un loro sottotipo), perche' quelle
        # sottoclassi hanno uno SCHEME specifico che non ha senso imporre a
        # un dizionario annidato arbitrario.
        if isinstance(val, dict):
            frozen_items: dict[Any, Any] = {}
            for key, value in _cast(dict[Any, Any], val).items():
                frozen_items[key] = cls._freeze(value)
            obj: Immutable = dict.__new__(Immutable)
            dict[Any, Any].__init__(obj, frozen_items)
            return obj
        if isinstance(val, (list, tuple)):
            return tuple(
                cls._freeze(value) for value in _cast(Iterable[Any], val)
            )
        return val

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"Campo '{item}' non presente in {self.__class__.__name__}")

    def __setattr__(self, k: str, v: Any) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def __setitem__(self, k: Any, v: Any) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def __delitem__(self, k: Any) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def clear(self) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def pop(self, *args: Any, **kwargs: Any) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def popitem(self) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def setdefault(self, *args: Any, **kwargs: Any) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def update(self, *args: Any, **kwargs: Any) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")
    def __ior__(self, other: Any) -> _Never: raise TypeError(f"{self.__class__.__name__} è immutabile")

    def __copy__(self) -> dict[Any, Any]:
        return dict(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[Any, Any]:
        copied: dict[Any, Any] = {}
        memo[id(self)] = copied
        for key, value in self.items():
            copied[copy.deepcopy(key, memo)] = copy.deepcopy(value, memo)
        return copied

    # FIX(1): rende Immutable davvero hashable (era dict, quindi __hash__
    # era None nonostante il nome della classe). Il contenuto non puo'
    # cambiare dopo __init__ (vedi __setitem__/__setattr__ sopra), quindi
    # e' sicuro calcolare e cachare l'hash una sola volta.
    def __hash__(self) -> int:  # type: ignore[override]
        cached = self.__dict__.get("_hash_cache")
        if cached is None:
            try:
                cached = hash(frozenset(self.items()))
            except TypeError as exc:
                raise TypeError(
                    f"{self.__class__.__name__} non è hashable: contiene un valore "
                    f"non hashable non gestito da _freeze ({exc})"
                ) from exc
            object.__setattr__(self, "_hash_cache", cached)
        return cached


class Success(Immutable, Generic[T]):
    SCHEME = {
        "is_success": {"type": bool, "required": True, "default": True},
        "value": {"required": True, "nullable": True}
    }
    def __init__(self, value: T) -> None:
        super().__init__(is_success=True, value=value)


class Failure(Immutable, Generic[F]):
    SCHEME = {
        "is_success": {"type": bool, "required": True, "default": False},
        "error": {"required": True, "nullable": True},
        "traceback": {"type": str, "required": False, "nullable": True, "default": None}
    }
    def __init__(self, error: F, tb: str | None = None) -> None:
        super().__init__(is_success=False, error=error, traceback=tb)


class Result(Immutable, Generic[T, F]):
    SCHEME = {
        "output": {"required": True},
        "input": {"required": False, "nullable": True, "default": None},
        "execution_time_ms": {"type": (int, float), "required": False, "default": 0.0},
        "action": {"type": str, "required": False, "nullable": True, "default": None},
        "component": {"type": str, "required": False, "nullable": True, "default": None},
        "transactions": {"type": tuple, "required": False, "default": ()}
    }

    @property
    def is_success(self) -> bool:
        return self.output.is_success

    @property
    def failed_step(self) -> "Result[Any, Any] | None":
        return None if self.is_success else (self.transactions[-1] if self.transactions else None)

    @property
    def successful_transactions(self) -> tuple["Result[Any, Any]", ...]:
        return tuple(tx for tx in self.transactions if tx.output.is_success)

    @property
    def steps(self) -> dict[str, Any]:
        """Restituisce un dizionario {nome_step: valore_output} per tutti gli step completati con successo."""
        return {
            tx.action: tx.output.value 
            for tx in self.transactions 
            if tx.output.is_success and tx.action
        }

    def get_step(self, step_name: str, default: Any = None) -> Any:
        """Recupera l'output di uno specifico step intermedio."""
        return self.steps.get(step_name, default)


FlowResult: _TypeAlias = Result[Any, Any]


Valor = Immutable


# ==============================================================================
# CORE PIPELINE & DECORATORS
# ==============================================================================

def _normalize(raw: Any, transactions: list[FlowResult]) -> Valor:
    if isinstance(raw, Result):
        nested_transactions: Iterable[FlowResult] = raw.get("transactions", ())
        transactions.extend(nested_transactions)
        return _cast(Valor, raw.output)
    if isinstance(raw, (Success, Failure)):
        return _cast(Valor, raw)
    return Success(value=raw)


async def _invoke(step: Step, value: Any, transactions: list[FlowResult]) -> Valor:
    try:
        out = step(value)
        if inspect.isawaitable(out):
            out = await out
        return _normalize(out, transactions)
    except Exception as exc:
        dev_log(
            "step.error",
            operation=getattr(step, "__name__", repr(step)),
            error_message=str(exc),
            exc_info=True,
            exception=exc,
            **_exception_location(exc),
        )
        return Failure(error=exc, tb=traceback.format_exc())


async def pipe(value: Any, *steps: Step, action: str = "flow.pipe", component: str | None = None) -> FlowResult:
    start = time.perf_counter()
    transactions: list[FlowResult] = []
    current: Valor = _normalize(value, transactions)
    for step in steps:
        match current:
            # 1. Short-circuit immediato se lo stato corrente è un Failure
            case Failure():
                break

            # 2. Se è un Success, destrutturiamo ed estraiamo direttamente 'value' in 'step_input'
            case Success():
                step_input = current["value"]
                step_start = time.perf_counter()
                step_name = getattr(step, "__name__", str(step))

                current = await _invoke(step, step_input, transactions)
                transactions.append(Result[Any, Any](
                    input=step_input,
                    output=current,
                    execution_time_ms=(time.perf_counter() - step_start) * 1000,
                    action=step_name,
                    component=component
                ))

            # 3. Fallback di sicurezza per istanze generiche con is_success=False
            case _ if getattr(current, "is_success", None) is False:
                break
            case _:
                pass

    result: FlowResult = Result[Any, Any](
        input=value,
        output=current,
        execution_time_ms=(time.perf_counter() - start) * 1000,
        action=action,
        component=component,
        transactions=tuple(transactions)
    )
    failure_details = _failure_location(current) if isinstance(current, Failure) else {}
    current_object = _cast(object, current)
    dev_log(
        "pipe.result",
        operation=action,
        component=component,
        success=result.is_success,
        output_type=type(current_object).__name__,
        transactions=len(transactions),
        elapsed_ms=round(result.execution_time_ms, 2),
        **failure_details,
    )
    return result

def pipe_sync(value: Any, *steps: Step, action: str = "flow.pipe_sync", component: str | None = None) -> FlowResult:
    """Esegue una pipeline composta da step sincroni."""
    start = time.perf_counter()
    transactions: list[FlowResult] = []
    current: Valor = _normalize(value, transactions)
    for step in steps:
        match current:
            case Failure():
                break
            case Success():
                step_input = current["value"]
                step_start = time.perf_counter()
                step_name = getattr(step, "__name__", str(step))
                try:
                    current = _normalize(step(step_input), transactions)
                except Exception as exc:
                    dev_log(
                        "step.error",
                        operation=step_name,
                        error_message=str(exc),
                        exc_info=True,
                        exception=exc,
                        **_exception_location(exc),
                    )
                    current = Failure(error=exc, tb=traceback.format_exc())
                transactions.append(Result[Any, Any](
                    input=step_input,
                    output=current,
                    execution_time_ms=(time.perf_counter() - step_start) * 1000,
                    action=step_name,
                    component=component
                ))
            case _ if getattr(current, "is_success", None) is False:
                break
            case _:
                pass

    result: FlowResult = Result[Any, Any](
        input=value,
        output=current,
        execution_time_ms=(time.perf_counter() - start) * 1000,
        action=action,
        component=component,
        transactions=tuple(transactions)
    )
    failure_details = _failure_location(current) if isinstance(current, Failure) else {}
    current_object = _cast(object, current)
    dev_log(
        "pipe_sync.result",
        operation=action,
        component=component,
        success=result.is_success,
        output_type=type(current_object).__name__,
        transactions=len(transactions),
        elapsed_ms=round(result.execution_time_ms, 2),
        **failure_details,
    )
    return result

def result(
    inputs: Iterable[str] = [],
    outputs: Iterable[str] = [],
    action: str | None = None,
    component: str | None = None,
) -> Callable[[Callable[_P, object]], Callable[_P, _Awaitable[FlowResult]]]:
    def decorator(
        func: Callable[_P, object],
    ) -> Callable[_P, _Awaitable[FlowResult]]:
        configuration = (inputs, outputs, action, component)
        if getattr(func, "__flow_result_config__", None) == configuration:
            return _cast(Callable[_P, _Awaitable[FlowResult]], func)

        @wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> FlowResult:
            start = time.perf_counter()
            txs: list[FlowResult] = []
            operation = action or getattr(func, "__qualname__", repr(func))
            trace_token = _enter_trace(operation, args, kwargs)
            log_token = set_log_context(_trace_metadata())
            try:
                out = func(*args, **kwargs)
                if inspect.isawaitable(out):
                    out = await out
                valor = _normalize(out, txs)
            except Exception as exc:
                dev_log(
                    "result.error",
                    operation=operation,
                    error_message=str(exc),
                    exc_info=True,
                    exception=exc,
                    **_exception_location(exc),
                )
                valor = Failure(error=exc, tb=traceback.format_exc())
            except BaseException:
                _trace_state.reset(trace_token)
                reset_log_context(log_token)
                raise

            result: FlowResult = Result[Any, Any](
                input={"args": args, "kwargs": kwargs},
                output=valor,
                execution_time_ms=(time.perf_counter() - start) * 1000,
                action=operation,
                component=component or getattr(func, "__module__", None),
                transactions=tuple(txs),
            )
            dev_log(
                "result.end",
                operation=operation,
                component=component or getattr(func, "__module__", None),
                success=result.is_success,
                output_type=type(valor).__name__,
                transactions=len(txs),
                elapsed_ms=round(result.execution_time_ms, 2),
                request_data=_safe_log_value(kwargs if kwargs else args),
                **(_failure_location(valor) if isinstance(valor, Failure) else {}),
            )
            _trace_state.reset(trace_token)
            reset_log_context(log_token)
            return result
        setattr(wrapper, "__flow_result_config__", configuration)
        return wrapper
    return decorator


def is_result(value: object) -> TypeGuard[FlowResult]: return isinstance(value, Result)
def success(value: T | None = None) -> Result[T | None, _Never]:
    return Result(output=Success(value))


def error(value: F | None = None) -> Result[_Never, F | None]:
    return Result(output=Failure(value))

def output(value: Any) -> Any:
    if not is_result(value):
        return value
    return value.output.value if value.is_success else value.output.error


def unwrap(value: Any) -> Any:
    """Restituisce il valore di un Result oppure solleva il suo errore."""
    if not is_result(value):
        return value
    if not value.is_success:
        error = value.output.error
        if isinstance(error, BaseException):
            raise error
        raise FlowError(error)
    return value.output.value


def check(value: object) -> bool:
    """Controlla se il valore è un Result e se è un Success."""
    return is_result(value) and value.is_success


# ==============================================================================
# 1. MAP / DICT (map_*) - Impatto su Dizionari e Schemi
# ==============================================================================

def map_get_value(
    path: str | int, default: Any = None
) -> Callable[[Any], Any]:
    """
    Estrae valori annidati tramite dot-notation:
    - 'data.id' -> naviga nei dizionari o Scheme
    - 'data.0' -> naviga nelle liste/tuple
    - 'users.*.id' -> estrae 'id' da tutti gli elementi di 'users'
    - 'users.*[role=admin].id' -> estrae 'id' solo dagli elementi che soddisfano il filtro
    """
    filter_pattern = re.compile(r"^\*\[(\w+)=(.*)\]$")

    def _resolve(current: Any, tokens: list[str]) -> Any:
        if not tokens:
            return current
        
        token = tokens[0]
        rest = tokens[1:]

        # Wildcard condizionale '*[campo=valore]' per liste/tuple di dict
        filter_match = filter_pattern.match(token)
        if filter_match:
            field, expected_value = filter_match.groups()
            if isinstance(current, (list, tuple)):
                matches: list[dict[Any, Any]] = []
                for item in _cast(Iterable[Any], current):
                    if not isinstance(item, dict):
                        continue
                    item_map = _cast(dict[Any, Any], item)
                    if str(item_map.get(field)) == expected_value:
                        matches.append(item_map)
                resolved = [_resolve(item, rest) for item in matches]
                return resolved if resolved else default
            return default

        # Wildcard '*' per sequenze e dizionari
        if token == "*":
            if isinstance(current, (list, tuple)):
                sequence = _cast(Iterable[Any], current)
                res = tuple(_resolve(item, rest) for item in sequence)
                return res if any(x is not None for x in res) else default
            elif isinstance(current, dict):
                current_map = _cast(dict[Any, Any], current)
                res = tuple(_resolve(val, rest) for val in current_map.values())
                return res if any(x is not None for x in res) else default
            return default

        # Indice numerico per liste e tuple
        if token.isdigit() and isinstance(current, (list, tuple)):
            idx = int(token)
            sequence = _cast(list[Any] | tuple[Any, ...], current)
            if 0 <= idx < len(sequence):
                return _resolve(sequence[idx], rest)
            return default

        # Chiave per Dict / Scheme / Attributo
        if isinstance(current, dict):
            current_map = _cast(dict[Any, Any], current)
            if token in current_map:
                return _resolve(current_map[token], rest)
        current_object = _cast(Any, current)
        if hasattr(current_object, token):
            return _resolve(getattr(current_object, token), rest)

        return default

    def _get(data: Any) -> Any:
        if isinstance(path, int):
            tokens = [str(path)]
        else:
            tokens = str(path).split(".")
        return _resolve(data, tokens)

    return _named(_get, f"map_get_value({path})")

def map_put_map(
    path: str, value: Any
) -> Callable[[Any], dict[Any, Any]]:
    """Inserisce un valore in un map tramite dot-notation senza mutare l'input."""
    def _put(data: Any) -> dict[Any, Any]:
        if not isinstance(data, dict):
            raise TypeError(f"map_put_map: atteso un dict, ricevuto {type(data).__name__}")
        if not path:
            raise ValueError("map_put_map: il path non può essere vuoto")

        result: dict[Any, Any] = copy.deepcopy(_cast(dict[Any, Any], data))
        current: dict[Any, Any] = result
        parts = str(path).split(".")
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = _cast(dict[Any, Any], nested)
        current[parts[-1]] = value
        return Immutable(result) if isinstance(data, Immutable) else result

    return _named(_put, f"map_put_map({path})")

def map_freeze_map() -> Callable[[Any], Immutable]:
    """Congela ricorsivamente un map e i suoi valori."""
    return _named(lambda data: Immutable(data), "map_freeze_map")

def map_compute_value(
    key: str,
    transform: Callable[[Any], Any],
) -> Callable[[dict[Any, Any]], dict[Any, Any]]:
    """Calcola e aggiunge un campo a un dict usando l'intero dict in input."""
    def _compute(data: dict[Any, Any]) -> dict[Any, Any]:
        new_data = dict(data)
        new_data[key] = transform(data)
        return Immutable(new_data) if isinstance(data, Immutable) else new_data
    return _named(_compute, f"map_compute_value({key})")

def map_construct_value(
    factory: Callable[..., Any], *paths: str
) -> Callable[[Any], Any]:
    """Costruisce un valore passando a ``factory`` i valori indicati nei path."""
    getters = tuple(map_get_value(path) for path in paths)

    def _construct(data: Any) -> Any:
        return factory(*(getter(data) for getter in getters))

    return _named(_construct, f"map_construct_value({_fn_label(factory)})")

def map_pick_map(
    *keys: str,
) -> Callable[[dict[Any, Any]], dict[Any, Any]]:
    """Estrae solo un sottoinsieme di chiavi da un dict/Scheme."""
    # FIX(5): preserva l'Immutable-ness dell'input, coerente con map_compute_value.
    def _pick(data: dict[Any, Any]) -> dict[Any, Any]:
        picked = {k: data[k] for k in keys if k in data}
        return Immutable(picked) if isinstance(data, Immutable) else picked
    return _named(_pick, f"map_pick_map({', '.join(keys)})")

def map_keys_map(
    fn: Callable[[Any], Any],
) -> Callable[[dict[Any, Any]], dict[Any, Any]]:
    """Trasforma le chiavi di un dict/Scheme tramite una funzione."""
    def _key_transform(data: dict[Any, Any]) -> dict[Any, Any]:
        return {fn(k): v for k, v in data.items()}
    return _named(_key_transform, f"map_keys_map({_fn_label(fn)})")

def map_items_tuple() -> Callable[
    [Mapping[Any, Any]], tuple[tuple[Any, Any], ...]
]:
    """Converte gli elementi di una mappa in una tupla di coppie."""
    return _named(lambda data: tuple(data.items()), "map_items_tuple")

def map_select_key_tuple(
    key: Any, reverse: bool = False
) -> Callable[
    [Mapping[Any, Any]], tuple[tuple[Any, Any], ...]
]:
    """Seleziona una chiave dai map annidati e restituisce coppie in una tuple.

    Per esempio, dato ``{"name": {"github": "login"}}`` e ``key="github"``,
    restituisce ``(("name", "login"),)``. Con ``reverse=True`` restituisce
    ``(("login", "name"),)``. E' indipendente da provider e mapper, quindi
    riutilizzabile per qualunque map di configurazioni annidate.
    """
    def _select(
        data: Mapping[Any, Any]
    ) -> tuple[tuple[Any, Any], ...]:
        entries: list[tuple[Any, Any]] = []
        for outer_key, nested in data.items():
            if not isinstance(nested, dict):
                continue
            nested_map = _cast(dict[Any, Any], nested)
            if key not in nested_map:
                continue
            pair = (outer_key, nested_map[key])
            entries.append(pair[::-1] if reverse else pair)
        return tuple(entries)

    return _named(_select, f"map_select_key_tuple({key}, reverse={reverse})")

# ==============================================================================
# 2. LIST / SEQUENZE (list_*) - Impatto su Liste e Collezioni
# ==============================================================================


def tuple_map_tuple(
    fn: Callable[[T], F],
) -> Callable[[Iterable[T]], tuple[F, ...]]:
    """Applica 'fn' a ciascun elemento di una tupla/sequenza."""
    return _named(lambda data: tuple(fn(x) for x in data), f"tuple_map_tuple({_fn_label(fn)})")

def tuple_map_async_tuple(
    async_fn: Callable[[Any], Any], concurrency: int | None = None
) -> Callable[[Iterable[Any]], _Awaitable[tuple[Any, ...]]]:
    """Applica una funzione asincrona in parallelo su una tupla di elementi."""
    async def _map_async(data: Iterable[Any]) -> tuple[Any, ...]:
        sem = asyncio.Semaphore(concurrency) if concurrency else None
        
        async def worker(item: Any) -> Any:
            if sem:
                async with sem:
                    res = async_fn(item)
                    return await res if inspect.isawaitable(res) else res
            res = async_fn(item)
            return await res if inspect.isawaitable(res) else res

        return tuple(await asyncio.gather(*[worker(x) for x in data]))
    return _named(_map_async, f"tuple_map_async_tuple({_fn_label(async_fn)})")

def tuple_filter_tuple(
    predicate: Callable[[T], bool],
) -> Callable[[Iterable[T]], tuple[T, ...]]:
    """Filtra gli elementi di una tupla in base al predicato."""
    return _named(lambda data: tuple(x for x in data if predicate(x)), f"tuple_filter_tuple({_fn_label(predicate)})")

def tuple_reduce_value(
    fn: Callable[[Any, Any], Any], initial: Any = _NO_INITIAL
) -> Callable[[Iterable[Any]], Any]:
    """Aggrega gli elementi di una tupla in un singolo valore."""
    return _named(
        lambda data: _reduce(fn, data) if initial is _NO_INITIAL else _reduce(fn, data, initial),
        f"tuple_reduce_value({_fn_label(fn)})"
    )

def tuple_flatten_tuple() -> Callable[[Iterable[Any]], tuple[Any, ...]]:
    """Appiattisce sequenze o liste annidate di un solo livello."""
    def _flatten(data: Iterable[Any]) -> tuple[Any, ...]:
        flat: list[Any] = []
        for item in data:
            if isinstance(item, (list, tuple, set)):
                flat.extend(_cast(Iterable[Any], item))
            else:
                flat.append(item)
        return tuple(flat)
    return _named(_flatten, "tuple_flatten_tuple")

def tuple_unique_tuple(
    key_fn: Callable[[Any], Any] = lambda x: x,
) -> Callable[[Iterable[Any]], tuple[Any, ...]]:
    """Rimuove i duplicati da una tupla mantenendo l'ordine originale.

    Nota: con key_fn di default (identita'), l'elemento deve essere hashable.
    Grazie al fix su Immutable._freeze, tuple di Success/Failure/Result/
    Immutable sono ora hashabili automaticamente. Per dati custom non
    hashabili, passa una key_fn che proietti su un valore hashable
    (es. key_fn=lambda x: x.id).
    """
    def _unique(data: Iterable[Any]) -> tuple[Any, ...]:
        seen: set[Any] = set()
        res: list[Any] = []
        for item in data:
            val = key_fn(item)
            if val not in seen:
                seen.add(val)
                res.append(item)
        return tuple(res)
    return _named(_unique, f"tuple_unique_tuple({_fn_label(key_fn)})")

def tuple_group_by_map(
    key_fn: Callable[[Any], Any],
) -> Callable[[Iterable[Any]], dict[Any, tuple[Any, ...]]]:
    """Raggruppa una tupla di elementi in un dizionario basandosi su key_fn."""
    def _group_by(data: Iterable[Any]) -> dict[Any, tuple[Any, ...]]:
        grouped: dict[Any, list[Any]] = {}
        for item in data:
            grouped.setdefault(key_fn(item), []).append(item)
        return {k: tuple(v) for k, v in grouped.items()}  # Convert lists to tuples
    return _named(_group_by, f"tuple_group_by_map({_fn_label(key_fn)})")

def tuple_merge_map(
    skip_invalid: bool = False,
) -> Callable[[Iterable[Any]], dict[Any, Any]]:
    """Unisce una tupla di dizionari in un singolo dizionario.

    FIX(6): per default solleva TypeError se un elemento non e' un dict,
    invece di ignorarlo in silenzio (un bug a monte diventava invisibile).
    Passa skip_invalid=True per il vecchio comportamento permissivo.
    """
    def _union(data: Iterable[Any]) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for d in data:
            if isinstance(d, dict):
                result.update(_cast(dict[Any, Any], d))
            elif not skip_invalid:
                raise TypeError(
                    f"tuple_merge_map: atteso un dict, ricevuto {type(d).__name__}: {d!r}"
                )
        return result
    return _named(_union, "tuple_merge_map")

def tuple_validate_each_tuple(
    predicate: Callable[[Any], bool],
    error_message: Callable[[Any], str] | str = "Validazione fallita",
) -> Callable[[Iterable[Any]], tuple[Any, ...]]:
    """Valida ogni elemento di una tupla con 'predicate'.

    E' l'equivalente per-elemento di flow_ensure_value (che valida l'intero dato
    in un colpo solo): al PRIMO elemento che non soddisfa il predicate,
    solleva un errore. _invoke lo cattura e trasforma l'intero step in
    Failure, facendo fermare il pipe li' (fail-fast), esattamente come
    flow_ensure_value - nessuna gestione manuale di Success/Failure necessaria.

    'error_message' puo' essere:
    - una stringa fissa, oppure
    - una funzione che riceve l'elemento fallito e ritorna il messaggio.
      Utile per leggere uno stato dinamico (es. validator.errors) popolato
      proprio dalla chiamata a 'predicate' un istante prima.

    Esempio (validazione di un dict costruito al volo per ogni chiave):
        tuple_map_tuple(lambda k: {k: value[k]}),
        tuple_validate_each_tuple(validator.validate, lambda kv: str(validator.errors)),
    """
    def _step(data: Iterable[Any]) -> tuple[Any, ...]:
        data = tuple(data)
        for item in data:
            if not predicate(item):
                msg = error_message(item) if callable(error_message) else error_message
                raise ValueError(msg)
        return data
    return _named(_step, f"tuple_validate_each_tuple({_fn_label(predicate)})")
    
def tuple_zip_tuple(
    iterable: Iterable[Any], strict: bool = False
) -> Callable[[Iterable[Any]], tuple[tuple[Any, Any], ...]]:
    """Accoppia gli elementi della lista corrente con un'altra lista/sequenza.

    FIX(7): l'iterable viene materializzato subito in una tupla, cosi' un
    generatore non si esaurisce silenziosamente se lo step viene riusato
    su piu' chiamate a pipe(). Con strict=True, solleva ValueError se le
    due sequenze hanno lunghezza diversa (zip() tronca silenziosamente
    di default).
    """
    fixed = tuple(iterable)

    def _zip(data: Iterable[Any]) -> tuple[tuple[Any, Any], ...]:
        data = tuple(data)
        if strict and len(data) != len(fixed):
            raise ValueError(
                f"tuple_zip_tuple: lunghezze diverse ({len(data)} vs {len(fixed)}) "
                f"con strict=True"
            )
        return tuple(zip(data, fixed))
    return _named(_zip, "tuple_zip_tuple")

def pipe_fork_async_tuple(
    *branches: Step,
) -> Callable[[Any], _Awaitable[tuple[Any, ...]]]:
    """Esegue piu' rami sullo stesso input e raccoglie i loro output."""
    async def _fork(data: Any) -> tuple[Any, ...]:
        outputs: list[Any] = []
        for branch in branches:
            output = branch(data)
            if inspect.isawaitable(output):
                output = await output
            outputs.append(output)
        return tuple(outputs)

    return _named(_fork, "pipe_fork_async_tuple")


# ==============================================================================
# 3. FLOW / CONTROLLO (flow_*) - Impatto sul Flusso ed Eccezioni
# ==============================================================================

def flow_ensure_value(
    predicate: Callable[[Any], bool],
    error_message: str | Callable[[Any], str] = "Validation failed",
    transform: Callable[[Any], Any] = lambda data: data,
) -> Callable[[Any], Any]:
    """Valida il dato nel flusso; solleva un errore se la condizione fallisce."""
    def _ensure(data: Any) -> Any:
        if not predicate(data):
            message = error_message(data) if callable(error_message) else error_message
            raise ValueError(f"[{_ensure.__name__}] {message}")
        return transform(data)
    return _named(_ensure, f"flow_ensure_value({_fn_label(predicate)})")

def flow_branch_value(
    condition: Callable[[Any], bool],
    if_true: Callable[[Any], Any],
    if_false: Callable[[Any], Any] = lambda value: value,
) -> Callable[[Any], Any]:
    """Esegue una biforcazione condizionale del flusso (if-then-else)."""
    return _named(lambda data: if_true(data) if condition(data) else if_false(data), f"flow_branch_value({_fn_label(condition)})")

def flow_match_value(
    *cases: tuple[Callable[[Any], bool], Callable[[Any], Any]],
    default: Callable[[Any], Any] | None = None,
) -> Callable[[Any], Any]:
    """Esegue pattern matching multi-ramo sul valore corrente."""
    def _match(data: Any) -> Any:
        for condition, action in cases:
            if condition(data):
                return action(data)
        if default:
            return default(data)
        raise ValueError(f"Nessun pattern corrisponde al valore: {data}")
    return _named(_match, "flow_match_value")


# ==============================================================================
# 4. PIPE / GLOBALE & SIDE-EFFECTS (pipe_*) - Operazioni Trasversali
# ==============================================================================

def pipe_tap_value(fn: Callable[[Any], Any]) -> Callable[[Any], _Awaitable[Any]]:
    """Ispeziona o esegue side-effect sul dato passante senza modificarlo.

    FIX(4): supporta ora anche fn asincrone. Prima, se fn era una coroutine
    function, veniva creata e mai awaitata: il side-effect non veniva mai
    eseguito, senza alcun errore visibile.
    """
    async def _tap(data: Any) -> Any:
        res = fn(data)
        if inspect.isawaitable(res):
            await res
        return data
    return _named(_tap, f"pipe_tap_value({_fn_label(fn)})")

def pipe_foreach_tuple(
    fn: Callable[[T], Any],
) -> Callable[[Iterable[T]], _Awaitable[Iterable[T]]]:
    """Esegue un side-effect su ogni elemento di una lista senza alterarne il contenuto.

    FIX(4): supporta ora anche fn asincrone (eseguite in sequenza, in ordine,
    per preservare la semantica "foreach"; usa tuple_map_async se serve
    concorrenza).
    """
    async def _foreach(data: Iterable[Any]) -> Iterable[Any]:
        for item in data:
            res = fn(item)
            if inspect.isawaitable(res):
                await res
        return data
    return _named(_foreach, f"pipe_foreach_tuple({_fn_label(fn)})")