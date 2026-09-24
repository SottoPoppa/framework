"""Valutazione delle espressioni del modello DSL.

Contratto unico: ``evaluate(expression, scope)`` restituisce **sempre un
valore**. Quando un percorso differibile (``@nome``) non è ancora legato,
il valore restituito è un ``Deferred`` — che è un dato puro, non una closure:
può essere serializzato e valutato più tardi, anche da un altro interprete,
fornendo i binding mancanti.
"""

from __future__ import annotations

import inspect
import operator
from typing import Any

from .data import MISSING as REGISTRY_MISSING, Registry
from .model import Call, Deferred, ExecutionSpec, Literal, Ref, Source
from .scope import MISSING, Scope


class EvaluationError(Exception):
    """Errore di valutazione con la posizione nel sorgente DSL."""

    def __init__(self, message: str, source: Source | None = None, cause: BaseException | None = None):
        self.source = source
        self.reason = message
        location = f"{source} — " if source is not None else ""
        super().__init__(f"{location}{message}")
        if cause is not None:
            self.__cause__ = cause


OPERATORS = {
    '+': operator.add,
    '-': operator.sub,
    '*': operator.mul,
    '/': operator.truediv,
    '%': operator.mod,
    '^': operator.pow,
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


def _deferred_paths(value: Any) -> tuple[str, ...]:
    """Percorsi ancora non legati dentro un valore già valutato."""
    if isinstance(value, Deferred):
        return value.parameters
    if isinstance(value, (list, tuple)):
        return tuple(path for item in value for path in _deferred_paths(item))
    if isinstance(value, dict):
        return tuple(path for item in value.values() for path in _deferred_paths(item))
    return ()


def _as_scope(context: Any) -> Scope:
    """Accetta Scope, mappe o oggetti compatibili e restituisce uno Scope."""
    if isinstance(context, Scope):
        return context
    if context is None:
        return Scope()
    if isinstance(context, dict):
        return Scope(context)
    data = getattr(context, "data", None)
    return Scope(data if isinstance(data, dict) else {})


class Evaluator:
    """Valuta il modello DSL contro uno scope, senza catturare il runtime."""

    def __init__(self, registry: Registry | None = None):
        self.registry = registry or Registry()

    async def evaluate(self, expression: Any, scope: Any, *, session: Any = None) -> Any:
        """Punto di ingresso unico: valuta un'espressione o uno spec."""
        if isinstance(expression, ExecutionSpec):
            expression = expression.expression
        return await self._eval(expression, _as_scope(scope), session)

    async def resume(self, deferred: Deferred, bindings: Any = None, *, session: Any = None) -> Any:
        """Riprende un'espressione sospesa fornendo i binding mancanti."""
        scope = _as_scope(bindings)
        return await self._eval(deferred.expression, scope, session)

    def _registry_for(self, session: Any) -> Registry:
        return getattr(session, "registry", None) or self.registry

    # ── valutazione ──────────────────────────────────────────────────────────

    async def _eval(self, node: Any, scope: Scope, session: Any) -> Any:
        if isinstance(node, Literal):
            return node.value

        if isinstance(node, Deferred):
            return node

        if isinstance(node, Ref):
            return await self._eval_ref(node, scope, session)

        if isinstance(node, Call):
            return await self._eval_call(node, scope, session)

        if isinstance(node, ExecutionSpec):
            return await self._eval(node.expression, scope, session)

        if isinstance(node, list):
            return [await self._eval(item, scope, session) for item in node]

        if isinstance(node, tuple):
            return tuple([await self._eval(item, scope, session) for item in node])

        if isinstance(node, dict):
            return {key: await self._eval(item, scope, session) for key, item in node.items()}

        return node

    async def _eval_ref(self, node: Ref, scope: Scope, session: Any) -> Any:
        value = scope.lookup(node.path)
        if value is not MISSING:
            if isinstance(value, (Call, ExecutionSpec, Literal, Ref)):
                # Il contesto può contenere espressioni non ancora risolte.
                value = await self._eval(value, scope, session)
                if "." not in node.path:
                    scope.set(node.path, value)
            return value

        registered = self._registry_for(session).lookup(node.path)
        if registered is not REGISTRY_MISSING:
            return registered

        if node.deferrable:
            # Percorso non ancora legato: sospendi come dato, non come closure.
            return Deferred(node, (node.path,), node.source)
        return None

    async def _eval_call(self, node: Call, scope: Scope, session: Any) -> Any:
        if node.function in {"and", "or"} and len(node.arguments) == 2 and not node.keywords:
            left = await self._eval(node.arguments[0], scope, session)
            pending = _deferred_paths(left)
            if pending:
                return Deferred(node, pending, node.source)
            if node.function == "and" and not left:
                return False
            if node.function == "or" and left:
                return True
            arguments = [left, await self._eval(node.arguments[1], scope, session)]
            keywords = {}
        else:
            arguments = [await self._eval(item, scope, session) for item in node.arguments]
            keywords = {
                key: await self._eval(item, scope, session)
                for key, item in node.keywords.items()
            }

        pending = _deferred_paths(arguments) + _deferred_paths(tuple(keywords.values()))
        if pending:
            # Un operando è sospeso: sospendi l'intera chiamata, restando dato.
            return Deferred(node, pending, node.source)

        function = self._resolve(node, scope, session)
        try:
            value = function(*arguments, **keywords)
            return await value if inspect.isawaitable(value) else value
        except EvaluationError:
            raise
        except Exception as exc:
            raise EvaluationError(
                f"la chiamata a {node.function!r} è fallita: {exc}", node.source, exc
            ) from exc

    def _resolve(self, node: Call, scope: Scope, session: Any) -> Any:
        name = str(node.function)
        if name in OPERATORS:
            return OPERATORS[name]

        function = self._registry_for(session).lookup(name)
        if function is not REGISTRY_MISSING and callable(function):
            return function

        candidate = scope.lookup(name)
        if candidate is not MISSING and callable(candidate):
            return candidate

        raise EvaluationError(f"funzione {name!r} non trovata", node.source)
