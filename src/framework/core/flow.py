import asyncio
from functools import reduce as _reduce, wraps
import inspect
import time
import traceback
from typing import Any, Callable, Dict, Generic, Iterable, List, Tuple, TypeVar

T = TypeVar("T")
F = TypeVar("F")
Step = Callable[[Any], Any]


def _named(fn: Callable, name: str) -> Callable:
    """Assegna un nome descrittivo alle closure per l'ispezione della pipeline."""
    fn.__name__ = name
    return fn


# ==============================================================================
# STRUTTURE DATI IMMUTABILI E RISULTATI
# ==============================================================================

class Immutable(dict):

    def __init__(self, *args, **kwargs):
        input_data = args[0] if (args and isinstance(args[0], dict) and not kwargs) else kwargs
        super().__init__(self._freeze(input_data))

    @classmethod
    def _freeze(cls, val: Any) -> Any:
        if isinstance(val, Immutable):
            return val
        if isinstance(val, dict):
            return {k: cls._freeze(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return tuple(cls._freeze(v) for v in val)
        return val

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"Campo '{item}' non presente in {self.__class__.__name__}")

    def __setattr__(self, k, v): raise TypeError(f"{self.__class__.__name__} è immutabile")
    def __setitem__(self, k, v): raise TypeError(f"{self.__class__.__name__} è immutabile")
    def __delitem__(self, k): raise TypeError(f"{self.__class__.__name__} è immutabile")


class Success(Immutable, Generic[T]):
    SCHEME = {
        "is_success": {"type": bool, "required": True, "default": True},
        "value": {"required": True, "nullable": True}
    }
    def __init__(self, value: T):
        super().__init__(is_success=True, value=value)


class Failure(Immutable, Generic[F]):
    SCHEME = {
        "is_success": {"type": bool, "required": True, "default": False},
        "error": {"required": True, "nullable": True},
        "traceback": {"type": str, "required": False, "nullable": True, "default": None}
    }
    def __init__(self, error: F, tb: str | None = None):
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
    def failed_step(self) -> "Result | None":
        return None if self.is_success else (self.transactions[-1] if self.transactions else None)

    @property
    def successful_transactions(self) -> tuple["Result", ...]:
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


Valor = Success[Any] | Failure[Any]


# ==============================================================================
# CORE PIPELINE & DECORATORS
# ==============================================================================

def _normalize(raw: Any, transactions: list["Result"]) -> Valor:
    if isinstance(raw, Result):
        transactions.extend(list(raw.transactions))
        return raw.output
    return raw if isinstance(raw, (Success, Failure)) else Success(value=raw)


async def _invoke(step: Step, value: Any, transactions: list["Result"]) -> Valor:
    try:
        out = step(value)
        if inspect.isawaitable(out):
            out = await out
        return _normalize(out, transactions)
    except Exception as exc:
        return Failure(error=exc, tb=traceback.format_exc())


async def pipe(value: Any, *steps: Step, action: str = "flow.pipe", component: str | None = None) -> Result:
    start = time.perf_counter()
    transactions: list[Result] = []
    current: Valor = _normalize(value, transactions)

    for step in steps:
        match current:
            # 1. Short-circuit immediato se lo stato corrente è un Failure
            case Failure():
                break

            # 2. Se è un Success, destrutturiamo ed estraiamo direttamente 'value' in 'step_input'
            case Success(value=step_input):
                step_start = time.perf_counter()
                step_name = getattr(step, "__name__", str(step))

                current = await _invoke(step, step_input, transactions)
                
                transactions.append(Result(
                    input=step_input,
                    output=current,
                    execution_time_ms=(time.perf_counter() - step_start) * 1000,
                    action=step_name,
                    component=component
                ))

            # 3. Fallback di sicurezza per istanze generiche con is_success=False
            case Immutable(is_success=False):
                break

    return Result(
        input=value,
        output=current,
        execution_time_ms=(time.perf_counter() - start) * 1000,
        action=action,
        component=component,
        transactions=tuple(transactions)
    )

def result(inputs=[], outputs=[], action: str | None = None, component: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Result:
            start = time.perf_counter()
            txs: list[Result] = []
            try:
                out = func(*args, **kwargs)
                if inspect.isawaitable(out):
                    out = await out
                valor = _normalize(out, txs)
            except Exception as exc:
                valor = Failure(error=exc, tb=traceback.format_exc())

            return Result(
                input={"args": args, "kwargs": kwargs},
                output=valor,
                execution_time_ms=(time.perf_counter() - start) * 1000,
                action=action or getattr(func, "__qualname__", repr(func)),
                component=component or getattr(func, "__module__", None),
                transactions=tuple(txs),
            )
        return wrapper
    return decorator


def is_result(value: Any) -> bool: return isinstance(value, Result)
def success(value: Any = None) -> Result: return Result(output=Success(value))
def error(value: Any = None) -> Result: return Result(output=Failure(value))

def output(value: Any) -> Any:
    if not is_result(value):
        return value
    return value.output.value if value.is_success else value.output.error

def check(value) -> bool:
    """Controlla se il valore è un Result e se è un Success."""
    return is_result(value) and value.is_success


# ==============================================================================
# 1. MAP / DICT (map_*) - Impatto su Dizionari e Schemi
# ==============================================================================

def map_get(path: str | int, default: Any = None) -> Callable:
    """
    Estrae valori annidati tramite dot-notation:
    - 'data.id' -> naviga nei dizionari o Scheme
    - 'data.0' -> naviga nelle liste/tuple
    - 'users.*.id' -> estrae 'id' da tutti gli elementi di 'users'
    """
    def _resolve(current: Any, tokens: list[str]) -> Any:
        if not tokens:
            return current
        
        token = tokens[0]
        rest = tokens[1:]

        # Wildcard '*' per sequenze e dizionari
        if token == "*":
            if isinstance(current, (list, tuple)):
                res = tuple(_resolve(item, rest) for item in current)
                return res if any(x is not None for x in res) else default
            elif isinstance(current, dict):
                res = tuple(_resolve(val, rest) for val in current.values())
                return res if any(x is not None for x in res) else default
            return default

        # Indice numerico per liste e tuple
        if token.isdigit() and isinstance(current, (list, tuple)):
            idx = int(token)
            if 0 <= idx < len(current):
                return _resolve(current[idx], rest)
            return default

        # Chiave per Dict / Scheme / Attributo
        if isinstance(current, dict):
            if token in current:
                return _resolve(current[token], rest)
            return default
        elif hasattr(current, token):
            return _resolve(getattr(current, token), rest)

        return default

    def _get(data: Any) -> Any:
        if isinstance(path, int):
            tokens = [str(path)]
        else:
            tokens = str(path).split(".")
        return _resolve(data, tokens)

    return _named(_get, f"map_get({path})")

def map_mutate(**transforms: Callable[[Any], Any]) -> Callable:
    """Modifica o aggiunge chiavi a un dict/Scheme tramite trasformazioni."""
    def _mutate(data: dict) -> dict:
        new_data = dict(data)
        for key, fn in transforms.items():
            new_data[key] = fn(data)
        return Immutable(new_data) if isinstance(data, Immutable) else new_data
    return _named(_mutate, f"map_mutate({', '.join(transforms.keys())})")

def map_pick(*keys: str) -> Callable:
    """Estrae solo un sottoinsieme di chiavi da un dict/Scheme."""
    return _named(lambda data: {k: data[k] for k in keys if k in data}, f"map_pick({', '.join(keys)})")

def map_keys(fn: Callable[[Any], Any]) -> Callable:
    """Trasforma le chiavi di un dict/Scheme tramite una funzione."""
    def _key_transform(data: dict) -> dict:
        return {fn(k): v for k, v in data.items()}
    return _named(_key_transform, f"map_key({getattr(fn, '__name__', str(fn))})")

# ==============================================================================
# 2. LIST / SEQUENZE (list_*) - Impatto su Liste e Collezioni
# ==============================================================================


def tuple_transform(fn: Callable[[Any], Any]) -> Callable:
    """Applica 'fn' a ciascun elemento di una tupla/sequenza."""
    return _named(lambda data: tuple(fn(x) for x in data), f"tuple_transform({getattr(fn, '__name__', str(fn))})")

def tuple_transform_async(async_fn: Callable[[Any], Any], concurrency: int | None = None) -> Callable:
    """Applica una funzione asincrona in parallelo su una tupla di elementi."""
    async def _map_async(data: Iterable[Any]) -> tuple:
        sem = asyncio.Semaphore(concurrency) if concurrency else None
        
        async def worker(item):
            if sem:
                async with sem:
                    res = async_fn(item)
                    return await res if inspect.isawaitable(res) else res
            res = async_fn(item)
            return await res if inspect.isawaitable(res) else res

        return tuple(await asyncio.gather(*[worker(x) for x in data]))
    return _named(_map_async, f"tuple_transform_async({getattr(async_fn, '__name__', str(async_fn))})")

def tuple_filter(predicate: Callable[[Any], bool]) -> Callable:
    """Filtra gli elementi di una tupla in base al predicato."""
    return _named(lambda data: tuple(x for x in data if predicate(x)), f"tuple_filter({getattr(predicate, '__name__', str(predicate))})")

def tuple_reduce(fn: Callable[[Any, Any], Any], initial: Any = None) -> Callable:
    """Aggrega gli elementi di una tupla in un singolo valore."""
    return _named(
        lambda data: _reduce(fn, data) if initial is None else _reduce(fn, data, initial),
        f"tuple_reduce({getattr(fn, '__name__', str(fn))})"
    )

def tuple_flatten() -> Callable:
    """Appiattisce sequenze o liste annidate di un solo livello."""
    def _flatten(data: Iterable[Any]) -> tuple:
        flat = []
        for item in data:
            flat.extend(item) if isinstance(item, (list, tuple, set)) else flat.append(item)
        return tuple(flat)
    return _named(_flatten, "tuple_flatten")

def tuple_dedup(key_fn: Callable[[Any], Any] = lambda x: x) -> Callable:
    """Rimuove i duplicati da una tupla mantenendo l'ordine originale."""
    def _unique(data: Iterable[Any]) -> tuple:
        seen, res = set(), []
        for item in data:
            val = key_fn(item)
            if val not in seen:
                seen.add(val)
                res.append(item)
        return tuple(res)
    return _named(_unique, "tuple_dedup")

def tuple_group(key_fn: Callable[[Any], Any]) -> Callable:
    """Raggruppa una tupla di elementi in un dizionario basandosi su key_fn."""
    def _group_by(data: Iterable[Any]) -> Dict[Any, tuple]:
        grouped: Dict[Any, List[Any]] = {}
        for item in data:
            grouped.setdefault(key_fn(item), []).append(item)
        return {k: tuple(v) for k, v in grouped.items()}  # Convert lists to tuples
    return _named(_group_by, f"tuple_group({getattr(key_fn, '__name__', str(key_fn))})")

def tuple_zip(iterable: Iterable[Any]) -> Callable:
    """Accoppia gli elementi della lista corrente con un'altra lista/sequenza."""
    return _named(lambda data: tuple(zip(data, iterable)), "tuple_zip")


# ==============================================================================
# 3. FLOW / CONTROLLO (flow_*) - Impatto sul Flusso ed Eccezioni
# ==============================================================================

def flow_ensure(predicate: Callable[[Any], bool], error_message: str = "Validation failed") -> Callable:
    """Valida il dato nel flusso; solleva un errore se la condizione fallisce."""
    def _ensure(data: Any) -> Any:
        if not predicate(data):
            raise ValueError(f"[{_ensure.__name__}] {error_message}")
        return data
    return _named(_ensure, f"flow_ensure({getattr(predicate, '__name__', 'cond')})")

def flow_branch(condition: Callable, if_true: Callable, if_false: Callable = lambda x: x) -> Callable:
    """Esegue una biforcazione condizionale del flusso (if-then-else)."""
    return _named(lambda data: if_true(data) if condition(data) else if_false(data), f"flow_branch({getattr(condition, '__name__', 'cond')})")

def flow_match(*cases: Tuple[Callable, Callable], default: Callable | None = None) -> Callable:
    """Esegue pattern matching multi-ramo sul valore corrente."""
    def _match(data: Any) -> Any:
        for condition, action in cases:
            if condition(data):
                return action(data)
        if default:
            return default(data)
        raise ValueError(f"Nessun pattern corrisponde al valore: {data}")
    return _named(_match, "flow_match")


# ==============================================================================
# 4. PIPE / GLOBALE & SIDE-EFFECTS (pipe_*) - Operazioni Trasversali
# ==============================================================================

def pipe_tap(fn: Callable[[Any], None]) -> Callable:
    """Ispeziona o esegue side-effect sul dato passante senza modificarlo."""
    def _tap(data: Any) -> Any:
        fn(data)
        return data
    return _named(_tap, f"pipe_tap({getattr(fn, '__name__', str(fn))})")

def pipe_foreach(fn: Callable[[Any], None]) -> Callable:
    """Esegue un side-effect su ogni elemento di una lista senza alterarne il contenuto."""
    def _foreach(data: Iterable[Any]) -> Iterable[Any]:
        for item in data:
            fn(item)
        return data
    return _named(_foreach, f"pipe_foreach({getattr(fn, '__name__', str(fn))})")