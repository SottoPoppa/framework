"""Modello puro del programma DSL.

Tutto ciò che vive qui è dato: serializzabile, confrontabile, privo di binding
al runtime. Una espressione non ancora valutata è un ``Deferred``, non una
closure: può essere persistita e valutata in seguito da un altro interprete.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Source:
    """Posizione nel sorgente DSL, propagata fino agli errori di runtime."""

    file: str | None = None
    line: int | None = None
    column: int | None = None

    def __str__(self) -> str:
        location = self.file or "<dsl>"
        if self.line is not None:
            location += f":{self.line}"
            if self.column is not None:
                location += f":{self.column}"
        return location


@dataclass(frozen=True, slots=True)
class Literal:
    value: Any
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class Ref:
    """Lettura di un percorso dallo scope.

    Con ``deferrable=True`` (forma DSL ``@nome``) un percorso assente non è un
    errore: l'espressione che lo contiene diventa un ``Deferred``.
    """

    path: str
    deferrable: bool = False
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class Call:
    function: str
    arguments: tuple[Any, ...] = ()
    keywords: Mapping[str, Any] = field(default_factory=dict)
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class Deferred:
    """Espressione sospesa: dato puro, valutabile con `evaluate(deferred, scope)`.

    Sostituisce le closure runtime. Nasce dalla forma DSL ``@nome`` e dalle
    espressioni che dipendono da binding non ancora disponibili.
    """

    expression: Any
    parameters: tuple[str, ...] = ()
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    expression: Any


@dataclass(frozen=True, slots=True)
class TriggerDefinition:
    source: str
    target: str
    event: str = "success"


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    name: str
    action: ExecutionSpec | Any
    deps: tuple[str, ...] = ()
    entry: bool = True
    timeout: float | None = None
    retries: int = 0
    retry_delay: float = 0.0
    on_end: str | None = None
    outputs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class DagDefinition:
    name: str
    nodes: tuple[NodeDefinition, ...]
    context: Mapping[str, Any] = field(default_factory=dict)
    triggers: tuple[TriggerDefinition, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_nodes(cls, name, nodes, *, context=None, triggers=(), metadata=None):
        return cls(name, tuple(nodes), dict(context or {}), tuple(triggers), dict(metadata or {}))


def located(node: Any, source: Source | None) -> Any:
    """Associa una posizione sorgente a un nodo del modello, se ne è privo."""
    if source is None or not isinstance(node, (Literal, Ref, Call, Deferred, NodeDefinition)):
        return node
    if node.source is not None:
        return node
    return replace(node, source=source)


def expression_of(node: Any) -> Any:
    """Estrae l'espressione da uno spec o da un differito."""
    if isinstance(node, ExecutionSpec):
        return expression_of(node.expression)
    if isinstance(node, Deferred):
        return node.expression
    return node


# ── codec JSON ────────────────────────────────────────────────────────────────

TAG = "$dsl"

_KINDS = {
    Literal: "literal",
    Ref: "ref",
    Call: "call",
    Deferred: "deferred",
    ExecutionSpec: "spec",
}


def encode(node: Any, encode_value) -> Any:
    """Codifica un nodo del modello in una struttura JSON taggata.

    `encode_value` codifica i valori annidati non-modello, così il codec non
    dipende dal modulo di sessione.
    """
    kind = _KINDS.get(type(node))
    if kind is None:
        return None

    body: dict[str, Any] = {"kind": kind}
    source = getattr(node, "source", None)
    if source is not None:
        body["source"] = {"file": source.file, "line": source.line, "column": source.column}

    if isinstance(node, Literal):
        body["value"] = encode_value(node.value)
    elif isinstance(node, Ref):
        body["path"] = node.path
        body["deferrable"] = node.deferrable
    elif isinstance(node, Call):
        body["function"] = node.function
        body["arguments"] = [encode_value(item) for item in node.arguments]
        body["keywords"] = {str(k): encode_value(v) for k, v in node.keywords.items()}
    elif isinstance(node, Deferred):
        body["expression"] = encode_value(node.expression)
        body["parameters"] = list(node.parameters)
    elif isinstance(node, ExecutionSpec):
        body["expression"] = encode_value(node.expression)

    return {TAG: body}


def is_encoded(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and TAG in value


def decode(value: Any) -> Any:
    """Ricostruisce il modello da una struttura JSON taggata."""
    if isinstance(value, list):
        return [decode(item) for item in value]
    if not is_encoded(value):
        if isinstance(value, dict):
            return {key: decode(item) for key, item in value.items()}
        return value

    body = value[TAG]
    raw_source = body.get("source")
    source = Source(**raw_source) if raw_source else None
    kind = body.get("kind")

    if kind == "literal":
        return Literal(decode(body.get("value")), source)
    if kind == "ref":
        return Ref(body["path"], bool(body.get("deferrable")), source)
    if kind == "call":
        return Call(
            body["function"],
            tuple(decode(item) for item in body.get("arguments", ())),
            {str(k): decode(v) for k, v in (body.get("keywords") or {}).items()},
            source,
        )
    if kind == "deferred":
        return Deferred(
            decode(body.get("expression")),
            tuple(body.get("parameters") or ()),
            source,
        )
    if kind == "spec":
        return ExecutionSpec(decode(body.get("expression")))
    return value
