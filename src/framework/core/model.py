from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True, slots=True)
class Literal:
    value: Any

@dataclass(frozen=True, slots=True)
class Ref:
    path: str
    lazy: bool = False

@dataclass(frozen=True, slots=True)
class Call:
    function: str
    arguments: tuple[Any, ...] = ()
    keywords: Mapping[str, Any] = field(default_factory=dict)

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
    metadata: Mapping[str, Any] = field(default_factory=dict)

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
