import inspect
import operator
from typing import Any

from .model import Call, ExecutionSpec, Literal, Ref


class ExecutionFailed(Exception):
    """Sollevata quando l'esecuzione di una funzione/task fallisce."""
    pass


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
        # 1. Valori Letterali
        if isinstance(x, Literal):
            return x.value

        # 2. Riferimenti a Variabili o Nodi (Ref)
        if isinstance(x, Ref):
            val = self._get_from_context(context, x.path)
            # Se il valore nel contesto è un'espressione non ancora valutata, valutala e salvala
            if isinstance(val, (Call, Ref, Literal)):
                val = await self._eval(val, context)
                self._set_in_context(context, x.path, val)
            return val

        # 3. Chiamate di Funzione / Operatori (Call)
        if isinstance(x, Call):
            func_name = str(x.function)

            # Controllo se è un operatore nativo (+, -, ==, ecc.)
            if func_name in self.OPERATORS:
                fn = self.OPERATORS[func_name]
            else:
                # Altrimenti risolvi la funzione nel registry o nel contesto
                fn = self._resolve_function(func_name, context)

            args = [await self._eval(v, context) for v in x.arguments]
            kwargs = {k: await self._eval(v, context) for k, v in x.keywords.items()}

            try:
                value = fn(*args, **kwargs)
                return await value if inspect.isawaitable(value) else value
            except Exception as exc:
                raise ExecutionFailed(f'Execution of {func_name!r} failed: {exc}') from exc

        # 4. Collezioni Dati (Dict, List, Tuple)
        if isinstance(x, list):
            return [await self._eval(v, context) for v in x]
        if isinstance(x, tuple):
            return tuple([await self._eval(v, context) for v in x])
        if isinstance(x, dict):
            return {k: await self._eval(v, context) for k, v in x.items()}

        # 5. Valori nativi già valutati
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
            return context.get(key)
        if hasattr(context, 'get'):
            return context.get(key)
        return getattr(context, key, None)

    def _set_in_context(self, context: Any, key: str, value: Any) -> None:
        """Helper per salvare valori valutati nel contesto."""
        if isinstance(context, dict):
            context[key] = value
        elif hasattr(context, 'set'):
            context.set(key, value)
        elif hasattr(context, key):
            setattr(context, key, value)