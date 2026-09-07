from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class NodeMeta:
    line: Optional[int] = None
    column: Optional[int] = None
    end_line: Optional[int] = None
    end_column: Optional[int] = None


class ASTNode:
    meta: NodeMeta


@dataclass(frozen=True)
class Program(ASTNode):
    statements: tuple[ASTNode, ...]
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class Var(ASTNode):
    name: str
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class ContextVar(ASTNode):
    name: str
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class NumberLiteral(ASTNode):
    value: int | float
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class StringLiteral(ASTNode):
    value: str
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class BoolLiteral(ASTNode):
    value: bool
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class AnyVal(ASTNode):
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class Pair(ASTNode):
    key: ASTNode
    value: ASTNode
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class SequenceNode(ASTNode):
    items: tuple[ASTNode, ...]
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class TupleNode(ASTNode):
    items: tuple[ASTNode, ...]
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class ListNode(ASTNode):
    items: tuple[ASTNode, ...]
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class DictNode(ASTNode):
    items: tuple[ASTNode, ...]
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class Declaration(ASTNode):
    target: ASTNode
    targets: tuple[tuple[Optional[str], Optional[str]], ...]
    value: ASTNode
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class FunctionCall(ASTNode):
    name: Optional[str]
    args: tuple[ASTNode, ...]
    kwargs: dict[str, ASTNode]
    lazy: bool = False
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class FunctionDef(ASTNode):
    params: ASTNode
    body: ASTNode
    return_type: ASTNode
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class Task(ASTNode):
    trigger: ASTNode
    action: ASTNode
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class BinaryOp(ASTNode):
    op: str
    left: ASTNode
    right: ASTNode
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class NotOp(ASTNode):
    value: ASTNode
    meta: NodeMeta = field(default_factory=NodeMeta)


@dataclass(frozen=True)
class PipeNode(ASTNode):
    steps: tuple[ASTNode, ...]
    meta: NodeMeta = field(default_factory=NodeMeta)
