from dataclasses import dataclass
from typing import Any

from .ast import ASTNode, Declaration, Task

# Import dei moduli AST e Model
from .ast import (
    BinaryOp,
    BoolLiteral,
    AnyVal,
    ContextVar,  # Mantenuto se il parser lo emette ancora, altrimenti usa solo Var
    DictNode,
    FunctionCall,
    ListNode,
    NotOp,
    NumberLiteral,
    Pair,
    PipeNode,
    Program,
    SequenceNode,
    StringLiteral,
    TupleNode,
    Var,
)
from .model import Call, DagDefinition, ExecutionSpec, Literal, NodeDefinition, Ref, TriggerDefinition


@dataclass
class Compiler:

    def compile(self, program: Program, *, name: str = "main") -> DagDefinition:
        context: dict[str, Any] = {}
        custom_types: set[str] = set()
        typed_declarations: list[tuple[str, str]] = []
        nodes: list[NodeDefinition] = []
        triggers: list[TriggerDefinition] = []

        for st in program.statements:
            if isinstance(st, Declaration):
                typed_declarations.extend(self._typed_declarations(st))
                for var_name, value in self._declaration_entries(st):
                    context[var_name] = value
                for target_kind, var_name in st.targets:
                    if target_kind == "type" and var_name:
                        custom_types.add(var_name)

            elif isinstance(st, DictNode):
                typed_declarations.extend(self._typed_declarations(st))
                for item in st.items:
                    if isinstance(item, Pair):
                        key_name = self._extract_key_name(item.key)
                        if key_name:
                            context[key_name] = self._expr(item.value)

                    elif isinstance(item, Declaration):
                        for var_name, value in self._declaration_entries(item):
                            context[var_name] = value
                        for target_kind, var_name in item.targets:
                            if target_kind == "type" and var_name:
                                custom_types.add(var_name)

                    elif isinstance(item, Task):
                        expr = self._expr(item.action)
                        task_name = (
                            self._extract_key_name(item.trigger)
                            or "unnamed_task"
                        )
                        deps = tuple(sorted(self._refs(expr) - {task_name}))

                        nodes.append(
                            NodeDefinition(
                                name=task_name,
                                action=ExecutionSpec(expr),
                                deps=deps,
                                entry=True,
                            )
                        )

            elif isinstance(st, Task):
                expr = self._expr(st.action)
                task_name = self._extract_key_name(st.trigger) or "unnamed_task"
                
                # I Ref con lazy=True verranno ignorati da _refs, evitando dipendenze bloccanti
                deps = tuple(sorted(self._refs(expr) - {task_name}))

                nodes.append(
                    NodeDefinition(
                        name=task_name,
                        action=ExecutionSpec(expr),
                        deps=deps,
                        entry=True,
                    )
                )

        return DagDefinition.from_nodes(
            name,
            nodes,
            context=context,
            triggers=triggers,
            metadata={
                "custom_types": tuple(sorted(custom_types)),
                "typed_declarations": typed_declarations,
            },
        )

    def _typed_declarations(self, node: Any, path: tuple[str, ...] = ()) -> list[tuple[str, str]]:
        """Raccoglie le dichiarazioni `type:name` con il loro percorso DSL."""
        declarations = []
        if isinstance(node, Declaration):
            for type_name, value_name in node.targets:
                if type_name and type_name != "type" and value_name:
                    declarations.append((".".join((*path, value_name)), type_name))
            return declarations

        if isinstance(node, Pair):
            key = self._extract_key_name(node.key)
            return self._typed_declarations(node.value, (*path, key) if key else path)

        if isinstance(node, DictNode):
            for item in node.items:
                declarations.extend(self._typed_declarations(item, path))
        return declarations

    def _declaration_entries(self, decl: Declaration) -> list[tuple[str, Any]]:
        value = self._expr(decl.value)
        entries: list[tuple[str, Any]] = []
        for target_pair in decl.targets:
            var_name = target_pair[1] or target_pair[0]
            if var_name:
                entries.append((var_name, value))
        return entries

    def _extract_key_name(self, node: ASTNode) -> str | None:
        if isinstance(node, (Var, ContextVar)):
            return node.name
        if isinstance(node, StringLiteral):
            return node.value
        if isinstance(node, FunctionCall):
            return node.name
        return None

    def _expr(self, v: Any) -> Any:
        """Converte un nodo AST in una struttura dati esecutiva (Ref, Call, Literal, dict, list).
        Mantiene intatte le espressioni sospese (@lazy) senza valutarle.
        """
        # 1. Riferimenti a Variabili (Eager vs Lazy)
        if isinstance(v, ContextVar):
            return Ref(v.name, lazy=True)

        if isinstance(v, Var):
            return Ref(v.name, lazy=False)

        # 2. Valori Letterali
        if isinstance(v, (StringLiteral, NumberLiteral, BoolLiteral)):
            return Literal(v.value)

        if isinstance(v, AnyVal):
            return Literal(None)

        # 3. Operatori Binari (+, -, *, ==, &, in, ecc.)
        if isinstance(v, BinaryOp):
            return Call(
                function=v.op,
                arguments=(self._expr(v.left), self._expr(v.right)),
                keywords={}
            )

        # 4. Operatore Unario Not
        if isinstance(v, NotOp):
            return Call(
                function="not",
                arguments=(self._expr(v.value),),
                keywords={}
            )

        # 5. Gestione Pipe (|>)
        if isinstance(v, PipeNode):
            steps = getattr(v, "steps", [])
            if not steps:
                return Literal(None)

            current_expr = self._expr(steps[0])

            for step in steps[1:]:
                fn_name = None
                if isinstance(step, (Var, ContextVar)):
                    fn_name = step.name
                elif isinstance(step, FunctionCall):
                    fn_name = step.name
                elif isinstance(step, str):
                    fn_name = step
                else:
                    fn_name = self._extract_key_name(step) or str(step)

                if isinstance(step, FunctionCall):
                    existing_args = tuple(self._expr(x) for x in step.args)
                    args = (current_expr,) + existing_args
                    kwargs = {k: self._expr(val) for k, val in step.kwargs.items()}
                else:
                    args = (current_expr,)
                    kwargs = {}

                current_expr = Call(function=fn_name, arguments=args, keywords=kwargs)

            return current_expr

        # 6. Chiamate di Funzione
        if isinstance(v, FunctionCall):
            fn_name = v.name or ""
            args = tuple(self._expr(x) for x in v.args)
            kwargs = {k: self._expr(val) for k, val in v.kwargs.items()}
            return Call(fn_name, args, kwargs)

        # 7. Oggetti Dict / Mappe
        if isinstance(v, DictNode):
            res = {}
            for item in v.items:
                if isinstance(item, Pair):
                    key_str = self._extract_key_name(item.key)
                    if key_str:
                        res[key_str] = self._expr(item.value)
                elif isinstance(item, Declaration):
                    for var_name, value in self._declaration_entries(item):
                        res[var_name] = value
            return res

        # 8. Liste
        if isinstance(v, ListNode):
            return [self._expr(x) for x in v.items]

        # 9. Tuple e Sequenze (Collassa elemento singolo per le parentesi di raggruppamento)
        if isinstance(v, (SequenceNode, TupleNode)):
            items = [self._expr(x) for x in v.items]
            if len(items) == 1:
                return items[0]
            return items

        # 10. Coppie Chiave-Valore
        if isinstance(v, Pair):
            return {self._extract_key_name(v.key): self._expr(v.value)}

        # Fallback per nodi con attributo .value o valori nativi
        if hasattr(v, "value"):
            return Literal(v.value)

        return Literal(v)

    def _refs(self, x: Any) -> set[str]:
        """Trova ricorsivamente tutti i nomi di variabili/node usati nei Ref.
        Ignora i Ref con lazy=True per non creare dipendenze d'esecuzione rigide nel DAG.
        """
        # --- MODIFICA 2: Filtra i Ref Lazy ---
        if isinstance(x, Ref):
            if x.lazy:
                return set()  # Le variabili @ non bloccano l'esecuzione del nodo!
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