from dataclasses import dataclass
from typing import Any

from typing import Any

from .ast import ASTNode, Declaration, Task

# Import dei moduli AST e Model
from .ast import (
    BinaryOp,
    BoolLiteral,
    ContextVar,
    DictNode,
    FunctionCall,
    ListNode,
    NotOp,
    NumberLiteral,
    Pair,
    Program,
    SequenceNode,
    StringLiteral,
    TupleNode,
    Var,
)
from ..dag.model import Call, DagDefinition, ExecutionSpec, Literal, NodeDefinition, Ref, TriggerDefinition


@dataclass
class Compiler:

    def compile(self, program: Program, *, name: str = "main") -> DagDefinition:
        context: dict[str, Any] = {}
        nodes: list[NodeDefinition] = []
        triggers: list[TriggerDefinition] = []

        for st in program.statements:
            # Gestione Dichiarazioni / Assegnamenti
            if isinstance(st, Declaration):
                for target_pair in st.targets:
                    # target_pair è una tupla (chiave, nome_variabile)
                    var_name = target_pair[1] or target_pair[0]
                    if var_name:
                        context[var_name] = self._expr(st.value)

            # Gestione Mappe / DictNode generici a livello root
            elif isinstance(st, DictNode):
                for item in st.items:
                    if isinstance(item, Pair):
                        key_name = self._extract_key_name(item.key)
                        if key_name:
                            context[key_name] = self._expr(item.value)

            # Gestione Task
            elif isinstance(st, Task):
                expr = self._expr(st.action)
                # Estrazione del nome del task dal trigger
                task_name = self._extract_key_name(st.trigger) or "unnamed_task"

                # Calcolo dipendenze automatico dai riferimenti (Ref)
                deps = tuple(sorted(self._refs(expr)))

                nodes.append(
                    NodeDefinition(
                        name=task_name,
                        spec=ExecutionSpec(expr),
                        dependencies=deps,
                        is_entry=True,
                    )
                )

        return DagDefinition.from_nodes(
            name, nodes, context=context, triggers=triggers
        )

    def _extract_key_name(self, node: ASTNode) -> str | None:
        """Estrae la chiave in formato stringa da un nodo Var, StringLiteral o FunctionCall."""
        if isinstance(node, (Var, ContextVar)):
            return node.name
        if isinstance(node, StringLiteral):
            return node.value
        if isinstance(node, FunctionCall):
            return node.name
        return None

    def _expr(self, v: Any) -> Any:
        """Converte un nodo AST in una struttura dati esecutiva (Ref, Call, Literal, dict, list)."""
        if isinstance(v, (Var, ContextVar)):
            return Ref(v.name)

        if isinstance(v, (StringLiteral, NumberLiteral, BoolLiteral)):
            return Literal(v.value)

        # ---> AGGIUNGI QUESTO BLOCCO PER GLI OPERATORI BINARI (+, -, *, ==, and, etc.) <---
        if isinstance(v, BinaryOp):
            return Call(
                function=v.op,
                arguments=(self._expr(v.left), self._expr(v.right)),
                keywords={}
            )

        if isinstance(v, NotOp):
            return Call(
                function="not",
                arguments=(self._expr(v.value),),
                keywords={}
            )

        if isinstance(v, FunctionCall):
            fn_name = v.name or ""
            args = tuple(self._expr(x) for x in v.args)
            kwargs = {k: self._expr(val) for k, val in v.kwargs.items()}
            return Call(fn_name, args, kwargs)

        if isinstance(v, DictNode):
            res = {}
            for item in v.items:
                if isinstance(item, Pair):
                    key_str = self._extract_key_name(item.key)
                    if key_str:
                        res[key_str] = self._expr(item.value)
            return res

        if isinstance(v, (SequenceNode, ListNode, TupleNode)):
            items = [self._expr(x) for x in v.items]
            if len(items) == 1:
                return items[0]
            return items

        if isinstance(v, Pair):
            return {self._extract_key_name(v.key): self._expr(v.value)}

        if hasattr(v, "value"):
            return Literal(v.value)

        return Literal(v)

    def _refs(self, x: Any) -> set[str]:
        """Trova ricorsivamente tutti i nomi di variabili/node usati nei Ref."""
        if isinstance(x, Ref):
            return {x.path.split(".")[0]}

        if isinstance(x, Call):
            refs = set()
            for a in x.arguments:
                refs.update(self._refs(a))
            for v in x.keywords.values():
                refs.update(self._refs(v))
            return refs

        if isinstance(x, (list, tuple)):
            refs = set()
            for item in x:
                refs.update(self._refs(item))
            return refs

        if isinstance(x, dict):
            refs = set()
            for v in x.values():
                refs.update(self._refs(v))
            return refs

        return set()