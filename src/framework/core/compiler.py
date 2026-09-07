from dataclasses import dataclass
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
        nodes: list[NodeDefinition] = []
        triggers: list[TriggerDefinition] = []

        for st in program.statements:
            # Gestione Dichiarazioni / Assegnamenti
            if isinstance(st, Declaration):
                for var_name, value in self._declaration_entries(st):
                    context[var_name] = value

            # Gestione Mappe / DictNode generici a livello root
            elif isinstance(st, DictNode):
                for item in st.items:
                    # 1. Se l'elemento è un assegnamento tipo "chiave: valore"
                    if isinstance(item, Pair):
                        key_name = self._extract_key_name(item.key)
                        if key_name:
                            context[key_name] = self._expr(item.value)

                    # 1bis. Se l'elemento è una dichiarazione "tipo:nome := valore"
                    # annidata direttamente in un blocco {...} di primo livello
                    # (es. "type:route := {...}" nel file principale).
                    elif isinstance(item, Declaration):
                        for var_name, value in self._declaration_entries(item):
                            context[var_name] = value

                    # 2. AGGIUNGI QUESTO: Se l'elemento dentro il blocco è un Task ("trigger() -> action")
                    elif isinstance(item, Task):
                        expr = self._expr(item.action)
                        task_name = (
                            self._extract_key_name(item.trigger)
                            or "unnamed_task"
                        )
                        deps = tuple(sorted(self._refs(expr)))

                        nodes.append(
                            NodeDefinition(
                                name=task_name,
                                action=ExecutionSpec(expr),
                                deps=deps,
                                entry=True,
                            )
                        )

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
                        action=ExecutionSpec(expr),
                        deps=deps,
                        entry=True,
                    )
                )

        return DagDefinition.from_nodes(
            name, nodes, context=context, triggers=triggers
        )

    def _declaration_entries(self, decl: Declaration) -> list[tuple[str, Any]]:
        """Risolve una Declaration ('prefisso:nome := valore') in coppie
        (nome_variabile, valore_risolto). Il prefisso prima dei ':' (es.
        'type', 'any', 'presentation', 'role', 'route', 'policy') è solo
        un'annotazione nel linguaggio sorgente: qui viene usato come nome
        soltanto se non è stato dichiarato un nome più specifico dopo di esso
        (stesso comportamento già usato per le Declaration di primo livello)."""
        value = self._expr(decl.value)
        entries: list[tuple[str, Any]] = []
        for target_pair in decl.targets:
            var_name = target_pair[1] or target_pair[0]
            if var_name:
                entries.append((var_name, value))
        return entries

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

        # Gestione Operatori Binari (+, -, *, ==, and, etc.)
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

        # ---> GESTIONE PIPE (|>) <---
        # Trasforma `a |> print_info` oppure `a |> f |> g` in oggetti Call ricorsivi
        if isinstance(v, PipeNode):
            steps = getattr(v, "steps", [])
            if not steps:
                return Literal(None)

            # Il primo elemento è l'argomento/dato iniziale
            current_expr = self._expr(steps[0])

            # Ogni step successivo avvolge la corrente espressione come suo primo argomento
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

                # Se lo step era già una FunctionCall (es. `f(x)`), uniamo gli argomenti esistenti
                if isinstance(step, FunctionCall):
                    existing_args = tuple(self._expr(x) for x in step.args)
                    args = (current_expr,) + existing_args
                    kwargs = {k: self._expr(val) for k, val in step.kwargs.items()}
                else:
                    args = (current_expr,)
                    kwargs = {}

                current_expr = Call(function=fn_name, arguments=args, keywords=kwargs)

            return current_expr

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
                elif isinstance(item, Declaration):
                    # Es. dentro "roles: { role:admin := {...}; role:user := {...}; }"
                    # ogni "role:X := {...}" è una Declaration, non una Pair.
                    for var_name, value in self._declaration_entries(item):
                        res[var_name] = value
            return res

        # NB: "[...]" è sempre e solo una lista letterale nella grammatica, quindi
        # va sempre risolta in una list Python, anche con un solo elemento
        # (es. resources: ["all"] deve restare una lista, non collassare nello
        # scalare "all"). "(...)" invece è ambiguo tra raggruppamento e tupla
        # (la grammatica non li distingue: "(x)" e "(x,)" producono lo stesso
        # albero), quindi per le TupleNode/SequenceNode manteniamo il
        # comportamento originale che collassa un singolo elemento, altrimenti
        # espressioni come "(@resource in ...) & (@action == ...)" si
        # romperebbero (il "(...)" qui è un raggruppamento, non un 1-tupla).
        if isinstance(v, ListNode):
            return [self._expr(x) for x in v.items]

        if isinstance(v, (SequenceNode, TupleNode)):
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