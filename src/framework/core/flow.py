import asyncio
import copy
import re
from functools import reduce as _reduce, wraps
import inspect
import time
import traceback
from typing import Any, Callable, Dict, Generic, Iterable, List, Tuple, TypeVar

T = TypeVar("T")
F = TypeVar("F")
Step = Callable[[Any], Any]

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


def _fn_label(fn: Callable) -> str:
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
            frozen_items = {k: cls._freeze(v) for k, v in val.items()}
            obj = dict.__new__(Immutable)
            dict.__init__(obj, frozen_items)
            return obj
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

    def __copy__(self):
        return dict(self)

    def __deepcopy__(self, memo):
        copied = {}
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
                cached = hash(tuple(sorted(self.items(), key=lambda kv: kv[0])))
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
        transactions.extend(list(raw.get("transactions", ())))
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

def pipe_sync(value: Any, *steps: Step, action: str = "flow.pipe_sync", component: str | None = None) -> Result:
    """Esegue una pipeline composta da step sincroni."""
    start = time.perf_counter()
    transactions: list[Result] = []
    current: Valor = _normalize(value, transactions)

    for step in steps:
        match current:
            case Failure():
                break
            case Success(value=step_input):
                step_start = time.perf_counter()
                step_name = getattr(step, "__name__", str(step))
                try:
                    current = _normalize(step(step_input), transactions)
                except Exception as exc:
                    current = Failure(error=exc, tb=traceback.format_exc())
                transactions.append(Result(
                    input=step_input,
                    output=current,
                    execution_time_ms=(time.perf_counter() - step_start) * 1000,
                    action=step_name,
                    component=component
                ))
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


def unwrap(value: Any) -> Any:
    """Restituisce il valore di un Result oppure solleva il suo errore."""
    if not is_result(value):
        return value
    if not value.is_success:
        raise value.output.error
    return value.output.value


def check(value) -> bool:
    """Controlla se il valore è un Result e se è un Success."""
    return is_result(value) and value.is_success


# ==============================================================================
# 1. MAP / DICT (map_*) - Impatto su Dizionari e Schemi
# ==============================================================================

def map_get_value(path: str | int, default: Any = None) -> Callable:
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
                matches = [
                    item for item in current
                    if isinstance(item, dict) and str(item.get(field)) == expected_value
                ]
                resolved = [_resolve(item, rest) for item in matches]
                return resolved if resolved else default
            return default

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
        if hasattr(current, token):
            return _resolve(getattr(current, token), rest)

        return default

    def _get(data: Any) -> Any:
        if isinstance(path, int):
            tokens = [str(path)]
        else:
            tokens = str(path).split(".")
        return _resolve(data, tokens)

    return _named(_get, f"map_get_value({path})")

def map_put_map(path: str, value: Any) -> Callable:
    """Inserisce un valore in un map tramite dot-notation senza mutare l'input."""
    def _put(data: dict) -> dict:
        if not isinstance(data, dict):
            raise TypeError(f"map_put_map: atteso un dict, ricevuto {type(data).__name__}")
        if not path:
            raise ValueError("map_put_map: il path non può essere vuoto")

        result = copy.deepcopy(dict(data))
        current = result
        parts = str(path).split(".")
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = nested
        current[parts[-1]] = value
        return Immutable(result) if isinstance(data, Immutable) else result

    return _named(_put, f"map_put_map({path})")

def map_freeze_map() -> Callable:
    """Congela ricorsivamente un map e i suoi valori."""
    return _named(lambda data: Immutable(data), "map_freeze_map")

def map_compute_value(key: str, transform: Callable[[Any], Any]) -> Callable:
    """Calcola e aggiunge un campo a un dict usando l'intero dict in input."""
    def _compute(data: dict) -> dict:
        new_data = dict(data)
        new_data[key] = transform(data)
        return Immutable(new_data) if isinstance(data, Immutable) else new_data
    return _named(_compute, f"map_compute_value({key})")

def map_construct_value(factory: Callable[..., Any], *paths: str) -> Callable:
    """Costruisce un valore passando a ``factory`` i valori indicati nei path."""
    getters = tuple(map_get_value(path) for path in paths)

    def _construct(data: Any) -> Any:
        return factory(*(getter(data) for getter in getters))

    return _named(_construct, f"map_construct_value({_fn_label(factory)})")

def map_pick_map(*keys: str) -> Callable:
    """Estrae solo un sottoinsieme di chiavi da un dict/Scheme."""
    # FIX(5): preserva l'Immutable-ness dell'input, coerente con map_compute_value.
    def _pick(data: dict) -> dict:
        picked = {k: data[k] for k in keys if k in data}
        return Immutable(picked) if isinstance(data, Immutable) else picked
    return _named(_pick, f"map_pick_map({', '.join(keys)})")

def map_keys_map(fn: Callable[[Any], Any]) -> Callable:
    """Trasforma le chiavi di un dict/Scheme tramite una funzione."""
    def _key_transform(data: dict) -> dict:
        return {fn(k): v for k, v in data.items()}
    return _named(_key_transform, f"map_keys_map({_fn_label(fn)})")

def map_items_tuple() -> Callable:
    """Converte gli elementi di una mappa in una tupla di coppie."""
    return _named(lambda data: tuple(data.items()), "map_items_tuple")

def map_select_key_tuple(key: Any, reverse: bool = False) -> Callable:
    """Seleziona una chiave dai map annidati e restituisce coppie in una tuple.

    Per esempio, dato ``{"name": {"github": "login"}}`` e ``key="github"``,
    restituisce ``(("name", "login"),)``. Con ``reverse=True`` restituisce
    ``(("login", "name"),)``. E' indipendente da provider e mapper, quindi
    riutilizzabile per qualunque map di configurazioni annidate.
    """
    def _select(data: dict) -> tuple:
        entries = []
        for outer_key, nested in data.items():
            if not isinstance(nested, dict) or key not in nested:
                continue
            pair = (outer_key, nested[key])
            entries.append(pair[::-1] if reverse else pair)
        return tuple(entries)

    return _named(_select, f"map_select_key_tuple({key}, reverse={reverse})")

# ==============================================================================
# 2. LIST / SEQUENZE (list_*) - Impatto su Liste e Collezioni
# ==============================================================================


def tuple_map_tuple(fn: Callable[[Any], Any]) -> Callable:
    """Applica 'fn' a ciascun elemento di una tupla/sequenza."""
    return _named(lambda data: tuple(fn(x) for x in data), f"tuple_map_tuple({_fn_label(fn)})")

def tuple_map_async_tuple(async_fn: Callable[[Any], Any], concurrency: int | None = None) -> Callable:
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
    return _named(_map_async, f"tuple_map_async_tuple({_fn_label(async_fn)})")

def tuple_filter_tuple(predicate: Callable[[Any], bool]) -> Callable:
    """Filtra gli elementi di una tupla in base al predicato."""
    return _named(lambda data: tuple(x for x in data if predicate(x)), f"tuple_filter_tuple({_fn_label(predicate)})")

def tuple_reduce_value(fn: Callable[[Any, Any], Any], initial: Any = "__no_initial__") -> Callable:
    """Aggrega gli elementi di una tupla in un singolo valore."""
    # FIX(3): sentinel dedicato invece di None, cosi' None e' un initial legittimo.
    _NO_INITIAL = object()
    _initial = _NO_INITIAL if initial == "__no_initial__" else initial
    return _named(
        lambda data: _reduce(fn, data) if _initial is _NO_INITIAL else _reduce(fn, data, _initial),
        f"tuple_reduce_value({_fn_label(fn)})"
    )

def tuple_flatten_tuple() -> Callable:
    """Appiattisce sequenze o liste annidate di un solo livello."""
    def _flatten(data: Iterable[Any]) -> tuple:
        flat = []
        for item in data:
            flat.extend(item) if isinstance(item, (list, tuple, set)) else flat.append(item)
        return tuple(flat)
    return _named(_flatten, "tuple_flatten_tuple")

def tuple_unique_tuple(key_fn: Callable[[Any], Any] = lambda x: x) -> Callable:
    """Rimuove i duplicati da una tupla mantenendo l'ordine originale.

    Nota: con key_fn di default (identita'), l'elemento deve essere hashable.
    Grazie al fix su Immutable._freeze, tuple di Success/Failure/Result/
    Immutable sono ora hashabili automaticamente. Per dati custom non
    hashabili, passa una key_fn che proietti su un valore hashable
    (es. key_fn=lambda x: x.id).
    """
    def _unique(data: Iterable[Any]) -> tuple:
        seen, res = set(), []
        for item in data:
            val = key_fn(item)
            if val not in seen:
                seen.add(val)
                res.append(item)
        return tuple(res)
    return _named(_unique, f"tuple_unique_tuple({_fn_label(key_fn)})")

def tuple_group_by_map(key_fn: Callable[[Any], Any]) -> Callable:
    """Raggruppa una tupla di elementi in un dizionario basandosi su key_fn."""
    def _group_by(data: Iterable[Any]) -> Dict[Any, tuple]:
        grouped: Dict[Any, List[Any]] = {}
        for item in data:
            grouped.setdefault(key_fn(item), []).append(item)
        return {k: tuple(v) for k, v in grouped.items()}  # Convert lists to tuples
    return _named(_group_by, f"tuple_group_by_map({_fn_label(key_fn)})")

def tuple_merge_map(skip_invalid: bool = False):
    """Unisce una tupla di dizionari in un singolo dizionario.

    FIX(6): per default solleva TypeError se un elemento non e' un dict,
    invece di ignorarlo in silenzio (un bug a monte diventava invisibile).
    Passa skip_invalid=True per il vecchio comportamento permissivo.
    """
    def _union(data: Iterable[dict]) -> dict:
        result = {}
        for d in data:
            if isinstance(d, dict):
                result.update(d)
            elif not skip_invalid:
                raise TypeError(
                    f"tuple_merge_map: atteso un dict, ricevuto {type(d).__name__}: {d!r}"
                )
        return result
    return _named(_union, "tuple_merge_map")

def tuple_validate_each_tuple(
    predicate: Callable[[Any], bool],
    error_message: Callable[[Any], str] | str = "Validazione fallita",
) -> Callable:
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
    def _step(data: Iterable[Any]) -> tuple:
        data = tuple(data)
        for item in data:
            if not predicate(item):
                msg = error_message(item) if callable(error_message) else error_message
                raise ValueError(msg)
        return data
    return _named(_step, f"tuple_validate_each_tuple({_fn_label(predicate)})")
    
def tuple_zip_tuple(iterable: Iterable[Any], strict: bool = False) -> Callable:
    """Accoppia gli elementi della lista corrente con un'altra lista/sequenza.

    FIX(7): l'iterable viene materializzato subito in una tupla, cosi' un
    generatore non si esaurisce silenziosamente se lo step viene riusato
    su piu' chiamate a pipe(). Con strict=True, solleva ValueError se le
    due sequenze hanno lunghezza diversa (zip() tronca silenziosamente
    di default).
    """
    fixed = tuple(iterable)

    def _zip(data: Iterable[Any]) -> tuple:
        data = tuple(data)
        if strict and len(data) != len(fixed):
            raise ValueError(
                f"tuple_zip_tuple: lunghezze diverse ({len(data)} vs {len(fixed)}) "
                f"con strict=True"
            )
        return tuple(zip(data, fixed))
    return _named(_zip, "tuple_zip_tuple")

def pipe_fork_async_tuple(*branches: Step) -> Callable:
    """Esegue piu' rami sullo stesso input e raccoglie i loro output."""
    async def _fork(data: Any) -> tuple:
        outputs = []
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
) -> Callable:
    """Valida il dato nel flusso; solleva un errore se la condizione fallisce."""
    def _ensure(data: Any) -> Any:
        if not predicate(data):
            message = error_message(data) if callable(error_message) else error_message
            raise ValueError(f"[{_ensure.__name__}] {message}")
        return transform(data)
    return _named(_ensure, f"flow_ensure_value({_fn_label(predicate)})")

def flow_branch_value(condition: Callable, if_true: Callable, if_false: Callable = lambda x: x) -> Callable:
    """Esegue una biforcazione condizionale del flusso (if-then-else)."""
    return _named(lambda data: if_true(data) if condition(data) else if_false(data), f"flow_branch_value({_fn_label(condition)})")

def flow_match_value(*cases: Tuple[Callable, Callable], default: Callable | None = None) -> Callable:
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

def pipe_tap_value(fn: Callable[[Any], None]) -> Callable:
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

def pipe_foreach_tuple(fn: Callable[[Any], None]) -> Callable:
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