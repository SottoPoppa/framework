import inspect
import operator
from typing import Any

from .context import ExecutionContext
from .model import Call, ExecutionSpec, Literal, Ref


class ExecutionFailed(Exception):
    """Sollevata quando l'esecuzione di una funzione/task fallisce."""
    pass

class LazyValue:

    def __init__(self, expr: Any, context: Any, executor: "Executor"):
        self.expr = expr
        self.context = context
        self.executor = executor

    async def __call__(self, **override_vars: Any) -> Any:
        """Permette di chiamare direttamente l'istanza come se fosse una funzione:

        await lazy_val(action="GET")
        """
        return await self.force(**override_vars)

    async def force(self, **override_vars: Any) -> Any:
        eval_ctx = self._build_context(override_vars)
        return await self.executor._eval(self.expr, eval_ctx)

    def _build_context(self, override_vars: dict[str, Any]) -> Any:
        if not override_vars:
            return self.context

        if isinstance(self.context, dict):
            new_ctx = self.context.copy()
            new_ctx.update(override_vars)
            return new_ctx

        if isinstance(self.context, ExecutionContext):
            new_ctx = ExecutionContext(self.context.data)
        elif hasattr(self.context, "copy"):
            new_ctx = self.context.copy()
        else:
            new_ctx = dict(self.context)

        for k, v in override_vars.items():
            if hasattr(new_ctx, "set"):
                new_ctx.set(k, v)
            else:
                setattr(new_ctx, k, v)
        return new_ctx

class Executor:
    # Mappatura degli operatori binari e logici gestiti come chiamate di funzione
    OPERATORS = {
        '+': operator.add,
        '-': operator.sub,
        '*': operator.mul,
        '/': operator.truediv,
        '==': operator.eq,
        '!=': operator.ne,
        '>': operator.gt,
        '<': operator.lt,
        '>=': operator.ge,
        '<=': operator.le,
        'and': lambda a, b: bool(a and b),
        'or': lambda a, b: bool(a or b),
        'not': lambda a: not bool(a),
        'in': lambda a, b: a in b if b is not None else False,
    }

    def __init__(self, registry):
        self.registry = registry

    async def execute(self, spec: Any, context: Any) -> Any:
        expr = spec.expression if isinstance(spec, ExecutionSpec) else spec
        return await self._eval(expr, context)

    async def _eval(self, x: Any, context: Any) -> Any:
        """Valuta ricorsivamente l'AST. 
        Se un'espressione coinvolge un Ref(lazy=True) non ancora presente nel contesto,
        restituisce un LazyValue preservando l'albero per l'esecuzione dinamica.
        """
        # 0. Se è già un Thunk/LazyValue, restituiscilo o forzalo se necessario
        if isinstance(x, LazyValue):
            return x

        # 1. Valori Letterali
        if isinstance(x, Literal):
            return x.value

        # 2. Riferimenti a Variabili (Ref)
        if isinstance(x, Ref):
            if x.lazy:
                # Cerca nel contesto. Se la variabile @ non esiste ancora (es. @action o @resource),
                # restituisce un LazyValue anziché fallire o restituire None/False
                raw_val = self._get_from_context(context, x.path)
                if raw_val is None:
                    return LazyValue(x, context, self)
                
                # Se la variabile @ punta a un'espressione AST, restituisci il thunk
                if isinstance(raw_val, (Call, Ref)):
                    return LazyValue(raw_val, context, self)
                return raw_val

            # Modalità Eager (Variabile standard)
            val = self._get_from_context(context, x.path)
            if isinstance(val, (Call, Ref)):
                val = await self._eval(val, context)
                self._set_in_context(context, x.path, val)
            return val

        # 3. Chiamate di Funzione ed Operatori (Call)
        if isinstance(x, Call):
            func_name = str(x.function)

            # Valuta ricorsivamente gli argomenti
            args = [await self._eval(a, context) for a in x.arguments]
            kwargs = {k: await self._eval(v, context) for k, v in x.keywords.items()}

            # BLOCCO CHIAVE: Se almeno uno degli argomenti è un LazyValue o un Ref(lazy=True),
            # l'intera operazione non può essere calcolata ora. Viene impacchettata in un LazyValue!
            if any(isinstance(a, (LazyValue, Ref)) for a in args) or \
            any(isinstance(v, (LazyValue, Ref)) for v in kwargs.values()):
                return LazyValue(x, context, self)

            # Se tutti gli argomenti sono pronti, risolve l'operatore o la funzione
            if func_name in self.OPERATORS:
                fn = self.OPERATORS[func_name]
            else:
                fn = self._resolve_function(func_name, context)

            try:
                value = fn(*args, **kwargs)
                return await value if inspect.isawaitable(value) else value
            except Exception as exc:
                raise ExecutionFailed(f"Execution of {func_name!r} failed: {exc}") from exc

        # 4. Strutture Dati (List, Tuple, Dict)
        if isinstance(x, list):
            return [await self._eval(v, context) for v in x]
        
        if isinstance(x, tuple):
            return tuple([await self._eval(v, context) for v in x])
        
        if isinstance(x, dict):
            return {k: await self._eval(v, context) for k, v in x.items()}

        # 5. Valori nativi Python
        return x

    def _resolve_function(self, func_name: str, context: Any) -> Any:
        """Risolve una funzione cercando prima nel registry e poi nel contesto."""
        try:
            return self.registry.resolve(func_name)
        except Exception:
            fn = self._get_from_context(context, func_name)
            if callable(fn):
                return fn
            raise ExecutionFailed(f'Function or callable {func_name!r} not found in registry or context')

    def _get_from_context(self, context: Any, key: str) -> Any:
        """Helper per accedere al contesto sia che sia un dict sia un oggetto con .get()."""
        if isinstance(context, dict):
            value = context.get(key)
        elif hasattr(context, 'get'):
            value = context.get(key)
        else:
            value = getattr(context, key, None)
        if value is not None:
            return value
        try:
            return self.registry.resolve(key)
        except Exception:
            return None

    def _set_in_context(self, context: Any, key: str, value: Any) -> None:
        """Helper per salvare valori valutati nel contesto."""
        if isinstance(context, dict):
            context[key] = value
        elif hasattr(context, 'set'):
            context.set(key, value)
        elif hasattr(context, key):
            setattr(context, key, value)