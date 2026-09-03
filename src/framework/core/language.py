"""
DSL Language Interpreter — refactoring API pubblica
=====================================================

Cambiamenti principali
----------------------
1. **`execute()` standalone rimosso** — sostituito da `Interpreter.run_once()`,
   che gestisce internamente parse → add_file → session effimera → risultato.

2. **`add_file()` non resetta più stato globale** — ogni chiamata è idempotente;
   lo stato di build viene tenuto per file nel dict `_file_state[name]`.

3. **`invoke()` diventa `_invoke()` (privato)** — l'unico punto di entrata
    esterno per chiamare funzioni DSL diventa `call()`, che restituisce il Flow
    completo; il payload si ottiene da `result.output.value`.

4. **`create_session` + `run_session` → `open_session()` + `run()`** — nomi più
   chiari, firma coerente; `open_session` restituisce un `SessionHandle`
   che nasconde il sid e offre metodi contestuali.

5. **`start()` / `stop()` → `__aenter__` / `__aexit__`** — l'Interpreter si usa
   come async context manager; `start`/`stop` rimangono come alias espliciti
   per chi non usa il `async with`.

6. **`FlowNodeBuilder` unificato** — eliminata la duplicazione con
   `Interpreter._build_flow_nodes`; ora c'è un solo percorso.

7. **Nuova `parse_only()`** — API leggera per validare/ispezionare il DSL
   senza eseguirlo.

Invarianti mantenuti
--------------------
- Il protocollo interno visit_*/invoke rimane inalterato.
- `DagRunner` non viene esposto: tutte le interazioni passano per Interpreter.
- La compatibilità con il vecchio `execute(name, ast, functions, parser)` è
  preservata tramite `execute()` che delega a `run_once()`.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import operator
import random
import uuid
from collections import ChainMap
from collections.abc import Mapping, MutableMapping, Iterator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Stack di traceback isolato per task asyncio — ogni coroutine ha il proprio.
# Senza questo, sessioni concorrenti condividevano self._stack e si corrompevano
# a vicenda durante il traceback degli errori.
_visit_stack: contextvars.ContextVar[List[dict]] = contextvars.ContextVar(
    "_visit_stack", default=None
)

from lark import Lark, Token, Transformer, v_args

import framework.core.flow as flow
import framework.core.runner as runner
import framework.core.scheme as scheme

# ── Grammar (invariata) ───────────────────────────────────────────────────────

GRAMMAR = r"""
start: dictionary | [item (item)*] -> dictionary_node
dictionary: "{" [item (item)*] "}" -> dictionary_node
?item: declaration | entry | task
declaration: (entry|type_sequence) ":=" sequence ";"?
entry: (atom|sequence) ":" sequence ";"?
task: function_call "->" sequence ";"? -> task
?type_sequence: pair ("," pair)* ","? -> sequence
?sequence: expr ("," expr)* ","?
?expr: pipe
?pipe: logic
     | logic (PIPE (pair|logic))+ -> pipe_node
?logic: comparison
      | ("not" | "!") logic        -> not_op
      | logic ("and" | "&") logic  -> and_op
      | logic ("or"  | "|") logic  -> or_op
      | logic ("in" | "~") logic -> in_op
?comparison: sum
           | comparison COMPARISON_OP sum -> binary_op
?sum: term
    | sum ARITHMETIC_OP term -> binary_op
?term: power
     | term "*" power -> binary_op
     | term "/" power -> binary_op
     | term "%" power -> binary_op
?power: atom | atom "^" power -> power
?atom.7: value | identifier | tuple | list | dictionary | function_call | function_value
?tuple: "(" [sequence] ")" -> tuple_node | "(" [type_sequence] ")" -> tuple_node
pair.6: atom ":" expr
?list: "[" [sequence] "]" -> list_node
call_arg: expr | pair
call_arg_list: call_arg ("," call_arg)* ","? -> sequence
function_call: identifier "(" [call_arg_list] ")"
function_value.10: tuple dictionary tuple
identifier: CNAME -> identifier
| QUALIFIED_CNAME -> identifier
| "@" CNAME -> context_var
| "@" QUALIFIED_CNAME -> context_var
value: SIGNED_NUMBER -> number | STRING -> string | "true"i -> true | "false"i -> false | "none"i -> any_val
PIPE: "|>"
_ARROW: "->"
ASSIGN_OP: ":="
COLON_OP: ":"
COMPARISON_OP: "==" | "!=" | ">=" | "<=" | ">" | "<"
ARITHMETIC_OP: "+" | "-" | "*" | "/" | "%"
STRING: ESCAPED_STRING | SINGLE_QUOTED_STRING
SINGLE_QUOTED_STRING: /'[^']*'/
FILTER_PATTERN: "*[" CNAME "=" STRING "]"
QUALIFIED_CNAME: CNAME ("." (CNAME|INT|FILTER_PATTERN|"*"))+
INT : /[0-9]+/
%import common.SIGNED_NUMBER
%import common.ESCAPED_STRING
%import common.CNAME
%import common.WS
%ignore WS
COMMENT: /\/\/[^\n]*/ | /\/\*[\s\S]*?\*\//
%ignore COMMENT
"""

# ── Types / built-ins (invariati) ─────────────────────────────────────────────

TYPE_MAP = {
    'natural': int, 'integer': int, 'real': float, 'rational': float,
    'boolean': bool, 'complex': complex, 'matrix': list, 'vector': list, 'set': set,
    'int': int, 'i8': int, 'i16': int, 'i32': int, 'i64': int,
    'n8': int, 'n16': int, 'n32': int, 'n64': int,
    'f32': float, 'f64': float, 'str': str, 'bool': bool,
    'dict': dict, 'list': list, 'any': object, 'type': dict,
    'tuple': tuple, 'function': tuple,
}

DSL_FUNCTIONS: Dict[str, Any] = {
    'random':    random.randint,
    'transform': scheme.transform,
    'get':       scheme.get,
    'normalize': scheme.normalize,
    'put':       scheme.put,
    'convert':   scheme.convert,
    'keys':      lambda d: list(d.keys()) if isinstance(d, dict) else [],
    'values':    lambda d: list(d.values()) if isinstance(d, dict) else [],
    'union':     lambda a, b: {**a, **b},
    'print':     lambda *inputs: (print(*inputs), inputs)[1],
    'pass':      lambda *inputs: inputs,
    'exit':      lambda *inputs: exit(inputs),
} | TYPE_MAP | {'extension': 'py'}


def transform_record(record: Any, updates: Any = None, **fields) -> Any:
    """Return a record with generic field updates applied."""
    if not isinstance(record, Mapping):
        return record
    result = dict(record)
    if isinstance(updates, Mapping):
        result.update(updates)
    result.update(fields)
    return result


def bind_input(record: Any, value: Any) -> Any:
    """Bind the first value of a tuple stored in a record's inputs."""
    if not isinstance(record, Mapping):
        return record
    inputs = record.get("inputs")
    if not isinstance(inputs, tuple) or not inputs:
        return record
    return transform_record(record, inputs=(value, *inputs[1:]))


def add_expected(record: Any, expected: Any) -> Any:
    """Add a declared expected value to a record when its key is present."""
    if not isinstance(record, Mapping) or not isinstance(expected, Mapping):
        return record
    key = record.get("id")
    if key not in expected:
        return record
    return transform_record(record, outputs=expected[key])


def map_records(records: Any, builder: Any, *args, **kwargs) -> list:
    """Apply a pure builder to every mapping in a sequence."""
    if not isinstance(records, (list, tuple)) or not callable(builder):
        return []
    return [builder(record, *args, **kwargs)
            for record in records if isinstance(record, Mapping)]


def variants(tags: Any) -> list:
    """Expand a mapping of collections into generic key/value records."""
    if not isinstance(tags, Mapping):
        return []
    records = []
    for key, values in tags.items():
        values = list(values.keys()) if isinstance(values, Mapping) else values
        if not isinstance(values, (list, tuple, set)):
            continue
        for value in values:
            records.append({
                "key": key,
                "value": value,
            })
    return records


def tag_variants(tags: Any) -> list:
    """Adapt presentation tag variants into renderer input records."""
    return [
        {
            "inputs": (
                None,
                record["key"],
                {} if record["value"] == record["key"] else {"type": record["value"]},
                ["fixture"],
            ),
            "note": f"Composizione {record['key']}:{record['value']}",
        }
        for record in variants(tags)
    ]


def flatten_records(value: Any) -> list:
    """Flatten nested sequences while preserving individual data records."""
    if not isinstance(value, (list, tuple)):
        return [value]
    flattened = []
    for item in value:
        flattened.extend(flatten_records(item))
    return flattened


DSL_FUNCTIONS.update({
    "transform_record": transform_record,
    "bind_input": bind_input,
    "add_expected": add_expected,
    "map_records": map_records,
    "variants": variants,
    "tag_variants": tag_variants,
})


def _flow_output(result: flow.Result) -> Any:
    """Estrae il valore di successo dal contratto Result di flow."""
    if isinstance(result.output, flow.Success):
        return result.output.value
    return result.output.error


def _flow_result(value: Any, *, action: str = "language") -> flow.Result:
    return flow.Result(
        input=value,
        output=flow.Success(value),
        action=action,
        component=__name__,
    )


def _flow_error(error: Any, *, action: str = "language") -> flow.Result:
    return flow.Result(
        input=None,
        output=flow.Failure(error),
        action=action,
        component=__name__,
    )


def _foreach(values, fn):
    return [fn(value) for value in values]


def _switch(value, cases, default=None):
    fn = cases.get(value, default) if isinstance(cases, Mapping) else default
    return fn(value) if callable(fn) else fn


def _branch(condition, when_true, when_false=None):
    selected = when_true if condition else when_false
    return selected() if callable(selected) else selected


def _reset(value=None):
    return value


DSL_FUNCTIONS.update({
    'foreach': _foreach,
    'switch': _switch,
    'branch': _branch,
    'reset': _reset,
})


OPS = {
    '+': operator.add,  '-': operator.sub,   '*': operator.mul,
    '/': operator.truediv, '%': operator.mod, '^': operator.pow,
    '==': operator.eq,  '!=': operator.ne,
    '>':  operator.gt,  '<':  operator.lt,
    '>=': operator.ge,  '<=': operator.le,
    'and': lambda a, b: a and b,
    'or':  lambda a, b: a or b,
    'in':  lambda a, b: a in b,
}

# ── Transformer (invariato) ───────────────────────────────────────────────────

@v_args(meta=True)
class DSLTransformer(Transformer):

    def task(self, meta, items):
        items = [i for i in items if i is not None]
        trigger = items[0]
        action  = items[1]
        return self._m({"type": "task", "trigger": trigger, "action": action}, meta)

    def _m(self, node, meta):
        node["meta"] = {"line": meta.line, "column": meta.column,
                        "end_line": meta.end_line, "end_column": meta.end_column} \
                       if hasattr(meta, "line") else \
                       {"line": None, "column": None, "end_line": None, "end_column": None}
        return node

    def number(self, meta, n):
        v = str(n[0]); return self._m({"type": "number", "value": float(v) if "." in v else int(v)}, meta)

    def string(self, meta, s):   return self._m({"type": "string",  "value": str(s[0])[1:-1]},  meta)
    def true(self, meta, _):     return self._m({"type": "bool",    "value": True},               meta)
    def false(self, meta, _):    return self._m({"type": "bool",    "value": False},              meta)
    def any_val(self, meta, _):  return self._m({"type": "any"},                                  meta)

    def identifier(self, meta, s):
        return self._m({"type": "var",         "name": str(s[0])}, meta)

    def context_var(self, meta, s):
        return self._m({"type": "context_var", "name": str(s[0])}, meta)

    def function_value(self, meta, a):
        return self._m({"type": "function_def", "params": a[0], "body": a[1], "return_type": a[2]}, meta)

    def sequence(self, meta, items):
        return self._m({"type": "sequence", "items": [i for i in items if i is not None]}, meta)

    def call_arg(self, meta, items):
        return items[0]

    def _unwrap(self, meta, items, typ):
        items = [i for i in items if i is not None]
        if len(items) == 1 and isinstance(items[0], dict) and items[0].get("type") == "sequence":
            items = items[0]["items"]
        return self._m({"type": typ, "items": items}, meta)

    def tuple_node(self, meta, items): return self._unwrap(meta, items, "tuple")
    def list_node(self, meta, items):  return self._unwrap(meta, items, "list")

    def dictionary_node(self, meta, items):
        return self._m({"type": "dict", "items": [i for i in items if i is not None]}, meta)

    def pair(self, meta, a):
        return self._m({"type": "pair", "key": a[0], "value": a[1]}, meta)

    def entry(self, meta, a):
        return self._m({"type": "pair", "key": a[0], "value": a[1]}, meta)

    def _extract_targets(self, node):
        if node["type"] == "pair":
            t = node["key"].get("name")
            v = node["value"]
            n = v.get("name") or v.get("value")
            return [(t, n)]
        if node["type"] == "sequence":
            res = []
            for item in node["items"]: res.extend(self._extract_targets(item))
            return res
        if node["type"] == "var":
            return [(None, node["name"])]
        return []

    def declaration(self, meta, tree):
        target = tree[0]
        return self._m({"type": "declaration", "target": target,
                        "targets": self._extract_targets(target), "value": tree[1]}, meta)

    def function_call(self, meta, tree):
        fn   = tree[0]
        lazy = fn.get("type") == "context_var"
        inputs = tree[1].get("items", []) if isinstance(tree[1], dict) and tree[1]["type"] == "sequence" else [tree[1]]
        inputs = [i for i in inputs if i is not None]
        args, kwargs = [], {}
        for inp in inputs:
            if isinstance(inp, dict) and inp.get("type") == "pair":
                kwargs[inp["key"]["name"]] = inp["value"]
            else:
                args.append(inp)
        node = {"type": "call", "name": fn.get("name"), "args": args, "kwargs": kwargs}
        if lazy: node["lazy"] = True
        return self._m(node, meta)

    def binary_op(self, meta, a):
        if len(a) == 2:
            return self._m({"type": "binop", "op": "*",      "left": a[0], "right": a[1]}, meta)
        return     self._m({"type": "binop", "op": str(a[1]),"left": a[0], "right": a[2]}, meta)

    def power(self, meta, a):
        return self._m({"type": "binop", "op": "^", "left": a[0], "right": a[1]}, meta)

    def not_op(self, meta, a): return self._m({"type": "not",   "value": a[0]},                        meta)
    def and_op(self, meta, a): return self._m({"type": "binop", "op": "and", "left": a[0], "right": a[1]}, meta)
    def or_op(self, meta, a):  return self._m({"type": "binop", "op": "or",  "left": a[0], "right": a[1]}, meta)
    def in_op(self, meta, a):  return self._m({"type": "binop", "op": "in",  "left": a[0], "right": a[1]}, meta)

    def pipe_node(self, meta, items):
        items = [i for i in items if not isinstance(i, Token) and i is not None]
        return self._m({"type": "pipe", "steps": items}, meta)

    def start(self, meta, items): return items[0]


# ── Parse helpers ─────────────────────────────────────────────────────────────

def create_parser() -> Lark:
    return Lark(GRAMMAR, parser='lalr', propagate_positions=True)


def parse(source: str, parser: Lark) -> dict:
    """Parsa il sorgente DSL e restituisce l'AST. Solleva lark.UnexpectedInput in caso di errore."""
    return DSLTransformer().transform(parser.parse(source))


# ── Eccezione pubblica ────────────────────────────────────────────────────────

class DSLRuntimeError(Exception):
    def __init__(self, message: str, meta: Optional[dict] = None):
        if meta:
            sl, sc, el, ec = meta.get("line"), meta.get("column"), meta.get("end_line"), meta.get("end_column")
            if sl is not None:
                loc = f"line {sl}:{sc} - {el}:{ec}" if el else f"line {sl}, col {sc}"
                message += f" ({loc})"
        super().__init__(message)


# ── Runtime helpers (invariati) ───────────────────────────────────────────────

@dataclass(frozen=True)
class LazyBinOp:
    fn: callable = field(repr=False, compare=False)
    description: str
    def __call__(self, *a, **kw): return self.fn(*a, **kw)
    def __repr__(self):           return self.description

@dataclass(frozen=True)
class ContextVar:
    name: str
    def __call__(self, *_, **ctx): return flow.map_get_value(self.name)(ctx)
    def __repr__(self):            return self.name

@dataclass(frozen=True)
class LazyCall:
    interpreter: object = field(repr=False, compare=False)
    name: str
    call_node: dict  = field(repr=False, compare=False)
    env: dict        = field(repr=False, compare=False)
    def __call__(self, env, *args, **kwargs):
        tt = {**self.call_node, "lazy": False}
        return self.interpreter.visit_call(tt, self.env | env, *args, **kwargs)
    def __repr__(self): return f"@{self.name}(...)"


# ── SessionHandle ─────────────────────────────────────────────────────────────
# Oggetto restituito da Interpreter.open_session(); nasconde il sid e
# offre un'interfaccia contestuale per run/emit/update_state/close.

class SessionHandle(MutableMapping):
    """
    Handle contestuale a una sessione DSL.

    Uso tipico::

        async with interp.open_session(env={"user": "alice"}) as session:
            result = await session.run("my_file")
            session.update("config.debug", True)
            await session.emit("my_file", "reload")
    """

    def __init__(self, interpreter: "Interpreter", session: dict | str):
        self._interp = interpreter
        if isinstance(session, str):
            self._sid = session
            self.session = interpreter._session_data.setdefault(session, {"id": session})
        else:
            self.session = session
            self._sid = self.session.get('id')
            if not self._sid:
                raise ValueError("Una sessione deve contenere un id.")
            interpreter._session_data[self._sid] = self.session

    # The persisted session is the canonical public representation.  The DAG
    # runtime remains an implementation detail behind this mapping facade.
    def __getitem__(self, key: str) -> Any:
        return self.session[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.session[key] = value

    def __delitem__(self, key: str) -> None:
        del self.session[key]

    def __iter__(self) -> Iterator:
        return iter(self.session)

    def __len__(self) -> int:
        return len(self.session)

    # ── metodi pubblici ───────────────────────────────────────────────────────

    @flow.result()
    async def run(self, file: str, env: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Esegue un file caricato sulla sessione e restituisce i risultati.

        :param file: nome del file (deve essere già caricato con `load_file`)
        :param env:  variabili aggiuntive per questa esecuzione (opzionale)
        :returns:    risultato Flow con la mappa ``{node_name: result}`` in
                 ``outputs``
        """
        return await self._interp._run_session(self._sid, file, env or {})

    _MISSING = object()

    def update(self, path_or_values=None, value: Any = _MISSING, **kwargs) -> None:
        """Aggiorna la sessione persistente o il contesto DSL."""
        if value is self._MISSING and (
            path_or_values is None or isinstance(path_or_values, Mapping)
        ):
            if path_or_values is not None:
                self.session.update(path_or_values)
            self.session.update(kwargs)
            return
        if value is self._MISSING and kwargs:
            self.session.update(path_or_values, **kwargs)
            return
        if isinstance(path_or_values, str) and "." not in path_or_values:
            self.session[path_or_values] = value
            return
        self._interp._runner.update_state(self._sid, "", path_or_values, value)
        #def update(self, file: str, path: str, value: Any) -> None:
        #self._interp._runner.update_state(self._sid, file, path, value)

    async def emit(self, file: str, node: str, value: Any = None) -> None:
        """Triggera manualmente un nodo specifico."""
        self._interp._runner.emit(self._sid, file, node, value)

    async def wait(self, file: str, node: str) -> None:
        """Attende il completamento di un nodo specifico."""
        await self._interp._runner.wait_node(self._sid, file, node)

    def context(self, file: str | None = None) -> Dict:
        """
        Restituisce il contesto della sessione.

        Se viene specificato un file, restituisce solo il contesto relativo
        a quel file.
        """
        if file is None:
            return self._interp._runner.context(self._sid)

        return self._interp._runner.get_file_context(self._sid, file)

    async def close(self) -> None:
        """Chiude la sessione e rilascia le risorse."""
        await self._interp._runner.close_session(self._sid)

    # ── async context manager ─────────────────────────────────────────────────

    async def __aenter__(self) -> "SessionHandle":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()


# ── Interpreter ───────────────────────────────────────────────────────────────

class Interpreter:
    """
    Interprete del DSL.  Ciclo di vita::

        interp = Interpreter()
        await interp.start()            # oppure: async with Interpreter() as interp:

        await interp.load_file("app", source_code)

        async with interp.open_session(env={...}) as session:
            results = await session.run("app")

        await interp.stop()

    Per esecuzioni una-tantum::

        result = await interp.run_once("app", source_code, env={...})
    """

    def __init__(self, custom_types: Optional[Dict] = None):
        self._runner:       runner.DagRunner  = runner.DagRunner()
        self._parser:       Lark              = create_parser()
        self._ast_cache:    Dict[str, dict]   = {}
        self._file_tasks:   Dict[str, List]   = {}
        self._session_data: Dict[str, dict]  = {}
        self.custom_types:  Dict[str, Any]    = custom_types or {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> "Interpreter":
        """Avvia il motore DAG sottostante. Ritorna self per chaining."""
        await self._runner.start()
        return self

    async def stop(self) -> None:
        """Ferma il motore e annulla tutti i task schedulati."""
        await self._runner.stop()

    async def __aenter__(self) -> "Interpreter":
        return await self.start()

    async def __aexit__(self, *_) -> None:
        await self.stop()

    # ── file management ───────────────────────────────────────────────────────

    async def load_file(self, name: str, source: str) -> None:
        """
        Parsa e registra un file DSL nel motore.

        Idempotente: chiamare più volte con lo stesso `name` aggiorna il file.
        Non altera lo stato di altri file o delle sessioni esistenti.

        :param name:   identificatore univoco del file
        :param source: sorgente DSL (stringa)
        :raises lark.UnexpectedInput: se il sorgente non è sintatticamente valido
        :raises ValueError:           se il DAG del file contiene cicli
        """
        ast = parse(source, self._parser)
        self._ast_cache[name] = ast

        # Build dei flow nodes isolato per questo file
        tasks: List[dict] = []
        builder = _FlowNodeBuilder(self, task_sink=tasks)
        await builder.build(ast, env=DSL_FUNCTIONS)
        self._file_tasks[name] = tasks

        flow_nodes = await self._build_flow_nodes_from(tasks)
        await self._runner.add_file(name, flow_nodes)

    def parse_only(self, source: str) -> dict:
        """
        Parsa il sorgente e restituisce l'AST senza eseguirlo.

        Utile per validazione, ispezione o tooling.

        :param source: sorgente DSL
        :returns:      AST come dict
        :raises lark.UnexpectedInput: se il sorgente non è valido
        """
        return parse(source, self._parser)

    async def unload_file(self, name: str) -> None:
        """Rimuove un file dal motore. Le sessioni attive non vengono interrotte."""
        self._ast_cache.pop(name, None)
        self._file_tasks.pop(name, None)
        await self._runner.delete_file(name)

    # ── session management ────────────────────────────────────────────────────

    def session_create(self, sid: str | dict, env: dict = {}) -> None:
        """Inizializza la struttura interna. Chiamato solo dal Defender."""
        if isinstance(sid, Mapping):
            session = sid
            sid = session.get("id")
            if not sid:
                raise ValueError("Una sessione deve contenere un id.")
            self._session_data[sid] = session
        self._runner.create_session(sid, DSL_FUNCTIONS | env)

    def session_exists(self, sid: str) -> bool:
        return sid in self._runner.sessions 

    def open_session(
        self,
        env: Optional[Dict[str, Any]] = None,
        sid: Optional[str] = None,
    ) -> SessionHandle:
        """Apre o riusa una sessione contestuale."""
        session_id = sid or str(uuid.uuid4())
        self.session_create(session_id, env or {})
        return SessionHandle(self, session_id)

    async def run_once(
        self,
        name: str,
        source: str,
        env: Optional[Dict[str, Any]] = None,
    ) -> flow.Result:
        """Carica ed esegue un file in una sessione effimera."""
        await self.load_file(name, source)
        session = self.open_session(env=env)
        try:
            return await session.run(name)
        finally:
            await session.close()

    async def run_session(
        self,
        session: str | dict,
        file: str,
        env: Optional[Dict[str, Any]] = None,
    ) -> flow.Result:
        """Alias compatibile per eseguire un file su una sessione esistente."""
        sid = session if isinstance(session, str) else session.get("id")
        if not sid:
            raise ValueError("Una sessione deve contenere un id.")
        if sid not in self._runner.sessions:
            self.session_create(session, env or {})
        handle = SessionHandle(self, sid)
        return await handle.run(file, env)

    # ── direct function call ──────────────────────────────────────────────────

    async def call(
        self,
        fn: Any,
        args: tuple = (),
        kwargs: Optional[Dict] = None,
    ) -> Any:
        """
        Invoca una funzione (Python callable, DSL tuple, o LazyCall) e
        restituisce il ``flow.Result`` completo.

        Per ottenere il payload usare ``result.output.value``. Il risultato
        conserva anche ``transactions`` e la traccia delle chiamate interne.

        Solleva ``DSLRuntimeError`` in caso di errore.

        :param fn:     funzione da invocare
        :param args:   argomenti posizionali
        :param kwargs: argomenti keyword
        :returns:      risultato Flow della funzione
        """
        res = await self._invoke(fn, args, kwargs or {})
        if not res.is_success:
            raise DSLRuntimeError(f"Errore in call: {res.output.error}")
        return res

    # ── internals ─────────────────────────────────────────────────────────────
    # Tutto ciò che segue è API privata (prefisso _).
    # Non fare affidamento su questi metodi dall'esterno.
    
    async def _run_session(self, sid: str, file: str, env: Dict) -> Dict[str, Any]:
        if file not in self._ast_cache:
            raise DSLRuntimeError(f"File '{file}' non caricato. Usa load_file() prima.")

        ctx = self._runner.context(sid) | env
        ast_result, _ = await self.visit(self._ast_cache[file], ctx, path="")
        
        # Esegui il motore per i nodi reattivi/task
        dag_results = await self._runner.run_file(sid, file, ast_result)
        dag_outputs = {
            name: _flow_output(result)
            for name, result in dag_results.items()
        }
        
        # Il contratto Result resta nel runtime; il DSL riceve solo i payload.
        return flow.Result(
            input=ast_result,
            output=flow.Success(ast_result | dag_outputs),
            action=f"{file}.run",
            component=__name__,
            transactions=tuple(dag_results.values()),
        )

    async def _invoke(self, fn: Any, args: tuple, kwargs: Dict, path: str = "") -> Dict:
        """Esegue fn e restituisce sempre un flow.Result."""
        if isinstance(fn, LazyCall):
            merged = ChainMap(kwargs, fn.env)
            res, _ = await self.visit_call(fn.call_node, merged, path=path)
            return _flow_result(res, action=path or "language.lazy_call")
        if callable(fn):
            async def step(_):
                out = fn(*args, **kwargs)
                if inspect.isawaitable(out):
                    out = await out
                return out
            step.__name__ = getattr(fn, "__name__", "language.invoke")
            value = None
        elif isinstance(fn, tuple) and len(fn) in (3, 4):
            step = self._call_dsl_fn
            value = (fn, args, kwargs, path)
        else:
            raise DSLRuntimeError(f"Valore non invocabile: {fn!r}")

        result = await flow.pipe(
            value,
            step,
            action=path or getattr(step, "__name__", "language.invoke"),
            component=__name__,
        )
        if not result.is_success:
            return _flow_error(result.output.error, action=result.action)
        return _flow_result(_flow_output(result), action=result.action)

    # ── visita generica ───────────────────────────────────────────────────────

    async def visit(self, node, env, path=""):
        t = node.get("type")
        method = getattr(self, f"visit_{t}", None)
        if not method:
            raise DSLRuntimeError(f"Tipo AST sconosciuto: '{t}'", node.get("meta"))

        # Ogni task asyncio (= ogni sessione concorrente) ha il proprio stack.
        # Se questo è il primo visit della coroutine corrente, inizializziamo
        # la lista; token ci permette di ripristinare lo stato precedente.
        stack = _visit_stack.get()
        if stack is None:
            stack = []
            token = _visit_stack.set(stack)
        else:
            token = None

        stack.append(node)
        try:
            return await method(node, env, path)
        except DSLRuntimeError as e:
            trace = " -> ".join(
                f"{n['type']}({n.get('meta',{}).get('line','?')}:{n.get('meta',{}).get('column','?')})"
                for n in stack)
            e.args = (f"{e.args[0]} | Stack: {trace}",); raise
        finally:
            stack.pop()
            if token is not None:
                _visit_stack.reset(token)

    # ── scope resolution ─────────────────────────────────────────────────────
    #
    # Versione originale: O(n²) — per ogni candidato iterava su tutti gli
    # `available` con sorted() + endswith(). Su file con molti task annidati
    # (es. 50+) questo diventava un collo di bottiglia in _build_flow_nodes_from.
    #
    # Versione nuova: costruiamo una volta sola un indice
    #   suffix_index: suffisso -> [path completo, ...]
    # La lookup diventa O(1) per il caso esatto e O(k) per le ambiguità,
    # dove k è il numero di path con lo stesso suffisso (raramente > 2).
    # L'indice viene invalidato solo quando `available` cambia (nuovo load_file).

    @staticmethod
    def _build_scope_index(available: frozenset) -> Dict[str, List[str]]:
        """Costruisce l'indice suffisso -> [path] usato da _resolve_scope."""
        index: Dict[str, List[str]] = {}
        for path in available:
            parts = path.split(".")
            # Registra tutti i suffissi: "a.b.c", "b.c", "c"
            for i in range(len(parts)):
                suffix = ".".join(parts[i:])
                index.setdefault(suffix, []).append(path)
        return index

    def _resolve_scope(self, path: str, name: str, available: frozenset) -> str:
        # Cache dell'indice: ricalcolato solo se `available` cambia.
        cache_key = available if isinstance(available, frozenset) else frozenset(available)
        if not hasattr(self, "_scope_cache") or self._scope_cache[0] != cache_key:
            self._scope_cache = (cache_key, self._build_scope_index(cache_key))
        index = self._scope_cache[1]

        path_parts = path.split(".") if path else []

        # Strategia: prova i suffissi di `name` dal più lungo al più corto.
        # Per ciascun suffisso candidato, risale lo scope locale (path) prima
        # di cadere sul match globale — preserva la semantica originale.
        name_parts = name.split(".")
        for i in range(len(name_parts)):
            candidate = ".".join(name_parts[i:])
            candidates = index.get(candidate)
            if not candidates:
                continue

            # Risalita scope locale: prova path.candidate, parent.candidate, ...
            for j in range(len(path_parts), -1, -1):
                prefix = ".".join(path_parts[:j])
                full = f"{prefix}.{candidate}" if prefix else candidate
                if full in cache_key:
                    return full

            # Fallback globale: il path più lungo che finisce con il suffisso
            # (più specifico = più lungo, coerente con l'originale)
            return max(candidates, key=len)

        return name

    def _find_vars(self, node, _seen=None):
        if _seen is None: _seen = set()
        if isinstance(node, dict):
            t = node.get("type")
            if t == "pair" and isinstance(node.get("key"), dict) and node["key"].get("type") == "var":
                return self._find_vars(node["value"], _seen)
            if t in ("var", "context_var"):
                return {node["name"]}
            if t == "function_def":
                return set()
            return {
                v for key, child in node.items()
                if key != "meta"
                for v in self._find_vars(child, _seen)
            }
        if isinstance(node, (list, tuple)):
            return {v for child in node for v in self._find_vars(child, _seen)}
        return set()

    # ── primitivi ─────────────────────────────────────────────────────────────

    async def visit_number(self, n, e, path=""):      return n["value"], e
    async def visit_string(self, n, e, path=""):      return n["value"], e
    async def visit_bool(self, n, e, path=""):         return n["value"], e
    async def visit_any(self, n, e, path=""):         return None, e
    async def visit_identifier(self, n, e, path=""):  return n["name"], e
    async def visit_var(self, n, e, path=""):
        result = await scheme.get(e, n["name"], n["name"])
        return _flow_output(result), e
    async def visit_context_var(self, n, e, path=""): return ContextVar(n["name"]), e

    async def visit_function_def(self, n, e, path=""):
        p = n["params"].get("items", [n["params"]])
        r = n["return_type"].get("items", [n["return_type"]])
        return (p, n["body"], r, path), e

    # ── strutture ─────────────────────────────────────────────────────────────

    async def visit_task(self, node, env, path=""):
        # Durante load_file i task vengono raccolti da _FlowNodeBuilder.
        # visit_task viene chiamato solo a runtime (via visit_dict) e restituisce
        # la coppia (nome, action) senza side-effect sullo stato del file.
        task_name = node['trigger']['name']
        task_path = f"{path}.{task_name}" if path else task_name
        kwargs = {}
        for k, v in node['trigger'].get("kwargs", {}).items():
            val, env = await self.visit(v, env, path=task_path + "." + k)
            kwargs[k] = val
        return (task_name, node['action']), env

    async def _collect(self, node, env, cast, path=""):
        items = []
        for i, item in enumerate(node["items"]):
            item_path = f"{path}[{i}]" if path else f"[{i}]"
            val, env = await self.visit(item, env, path=item_path)
            items.append(val)
        return cast(items), env

    async def visit_tuple(self, n, e, path=""):    return await self._collect(n, e, tuple, path=path)
    async def visit_sequence(self, n, e, path=""): return await self._collect(n, e, tuple, path=path)
    async def visit_list(self, n, e, path=""):     return await self._collect(n, e, list,  path=path)

    async def visit_pair(self, node, env, path=""):
        if node["key"]["type"] == "var":
            key = node["key"]["name"]
        else:
            key, _ = await self.visit(node["key"], env, path=path + ".key")
            key = key[0] if isinstance(key, tuple) else key
        val_path = f"{path}.{key}" if path else str(key)
        value, _ = await self.visit(node["value"], env, path=val_path)
        return (key, value), env

    async def visit_declaration(self, node, env, path=""):
        items = node.get("targets", [])
        target_name = items[0][1] if items else None
        val_path = f"{path}.{target_name}" if path and target_name else (target_name or path)
        val, _ = await self.visit(node["value"], env, path=val_path)
        meta = node.get("meta")
        if len(items) == 1:
            tipo, name = items[0]
            if tipo == "type": self.custom_types[name] = val; return (name, val), env
            return (name, await self._check(val, tipo, meta, name, path=val_path)), env
        keys, values = [], []
        for i, (tipo, name) in enumerate(items):
            if tipo == "type": self.custom_types[name] = val
            keys.append(name)
            item_val_path = f"{val_path}[{i}]" if val_path else f"[{i}]"
            values.append(await self._check(val[i] if isinstance(val, (tuple, list)) else val, tipo, meta, name, path=item_val_path))
        return (tuple(keys), tuple(values)), env

    async def visit_dict(self, node, env, path=""):
        # Valutazione sequenziale: ogni item vede i valori definiti prima di lui
        # tramite `env | result`. L'ordine di dichiarazione è l'ordine di
        # valutazione — comportamento intenzionale del framework, coerente con
        # il fatto che le dipendenze tra dichiarazioni `:=` sono già risolte
        # dall'ordine di scrittura nel sorgente DSL.
        # Le dipendenze tra *task* `->` sono invece gestite dal DagRunner.
        result = {}
        for it in node["items"]:
            (key, val), _ = await self.visit(it, env | result, path=path)
            if isinstance(key, tuple):
                result.update(dict(zip(key, val)))
            else:
                result[key] = val
        return result, env

    async def visit_pipe(self, node, env, path=""):
        steps = node["steps"]
        val, env = await self.visit(steps[0], env, path)
        pipe_vars = {"_": val}
        for i, step in enumerate(steps[1:]):
            name = i
            if step.get("type") == "pair":
                name = step["key"].get("name", i)
                step = step["value"]
            pipe_vars["_"] = val
            local_env = env | pipe_vars
            val, _ = await self.visit_call(step, local_env, path, args=[val])
            pipe_vars[name] = val
        return val, env

    async def visit_binop(self, node, env, path=""):
        left,  env = await self.visit(node["left"],  env, path=path + ".left")
        right, env = await self.visit(node["right"], env, path=path + ".right")
        op = node["op"]
        if isinstance(left,  tuple): left  = left[0]
        if isinstance(right, tuple): right = right[0]
        if callable(left) or callable(right):
            fn_op = OPS[op]
            def lazy(*_, **ctx):
                l = left(**ctx)  if callable(left)  else left
                r = right(**ctx) if callable(right) else right
                return fn_op(l, r)
            return LazyBinOp(lazy, f"{left!r} {op} {right!r}"), env
        try:
            return OPS[op](left, right), env
        except Exception as e:
            raise DSLRuntimeError(f"Errore '{op}': {e} at {path}", node.get("meta"))

    async def visit_not(self, node, env, path=""):
        val, env = await self.visit(node["value"], env, path=path + ".not")
        if callable(val):
            def lazy(*_, **ctx): return not val(**ctx)
            return LazyBinOp(lazy, f"not {val!r}"), env
        return not val, env

    # ── chiamate a funzione ───────────────────────────────────────────────────

    async def visit_call(self, node, env, path="", args=(), kwargs={}):
        name, meta = node.get("name"), node.get("meta")
        if node.get("lazy"):
            return LazyCall(self, name, node, env), env
        call_path  = f"{path}.{name}" if path else str(name)
        ast_args   = [(await self.visit(a, env, path=f"{call_path}[{i}]"))[0] for i, a in enumerate(node.get("args", []))]
        ast_kwargs = {k: (await self.visit(v, env, path=f"{call_path}.{k}"))[0] for k, v in node.get("kwargs", {}).items()}
        all_args   = list(args) + ast_args
        all_kwargs = {**kwargs, **ast_kwargs}
        fn_result = await scheme.get(env, str(name))
        fn = _flow_output(fn_result)
        res = await self._invoke(fn, all_args, all_kwargs, path=call_path)
        if not res.is_success:
            return res, env
        return _flow_output(res), env

    async def _call_dsl_fn(self, fn_triple, args, kwargs, path=""):
        params_ast, body_ast, return_ast = fn_triple[:3]
        local_env = {}
        for i, (p, a) in enumerate(zip(params_ast, args)):
            name = p["value"]["name"]
            arg_path = f"{path}[{i}]" if path else name
            local_env[name] = await self._check(a, p["key"]["name"], p.get("meta"), name, path=arg_path)
        for p in params_ast[len(args):]:
            name = p["value"]["name"]
            if name in kwargs:
                arg_path = f"{path}.{name}" if path else name
                local_env[name] = await self._check(kwargs[name], p["key"]["name"], p.get("meta"), name, path=arg_path)
        result, _ = await self.visit(body_ast, local_env, path=path + "->body")
        out = []
        for i, ty in enumerate(return_ast):
            (tipo, name), _ = await self.visit(ty, local_env, path=path + f"->out[{i}]")
            if name in result:
                out_path = f"{path}->out.{name}"
                out.append(await self._check(result[name], tipo, ty.get("meta"), name, path=out_path))
        return out[0] if len(out) == 1 else out

    async def _check(self, value, expected, meta, name, path=""):
        if expected in self.custom_types:
            ddd = scheme.normalize(value, self.custom_types[expected])
            ddd = flow.output(ddd)
            if ddd.get("errors"):
                raise DSLRuntimeError(f"Tipo errato '{path}': atteso {expected}, ottenuto {type(value).__name__}", meta)
            return ddd.get("data", ddd)
        py = TYPE_MAP.get(expected)
        if py and not (isinstance(value, py) and not (py is int and isinstance(value, bool))):
            display_name = path if path else name
            raise DSLRuntimeError(
                f"Tipo errato '{display_name}': atteso {expected}, ottenuto {type(value).__name__}", meta)
        return value

    async def _build_flow_nodes_from(self, tasks: List[dict]) -> List[dict]:
        """Costruisce la lista di runner.Node a partire dai task raccolti."""
        flow_nodes = []
        available = frozenset(t["path"] for t in tasks)  # frozenset: hashable per _scope_cache

        for task in tasks:
            name     = task["name"]
            t_path   = task.get("path", name)
            action   = task["action"]
            kw       = dict(task.get("kwargs", {}))

            raw_deps = self._find_vars(action) | self._find_vars(kw)
            deps = {
                resolved
                for d in raw_deps
                for resolved in [self._resolve_scope(t_path, d, available)]
                if resolved in available and resolved != t_path
            }

            kw["deps"] = [] if kw.get("deps") is False else list(deps) + kw.get("deps", [])
            flow_nodes.append(
                runner.Node(name=t_path, fn=self._make_task_fn(action, t_path), path=t_path, **kw)
            )

        return flow_nodes

    def _make_task_fn(self, ast: dict, t_path: str):
        """Factory per la funzione di nodo; evita la closure-in-loop."""
        async def task_fn(**env_dict):
            try:
                t = ast.get("type")
                if t == "pipe":
                    val, _ = await self.visit(ast, env_dict, path=t_path)
                    return val
                if t == "call":
                    call_result = await scheme.get(env_dict, ast["name"])
                    call = _flow_output(call_result)
                    args   = [(await self.visit(a, env_dict, path=f"{t_path}.args[{i}]"))[0]
                               for i, a in enumerate(ast.get("args", []))]
                    kwargs = {k: (await self.visit(v, env_dict, path=f"{t_path}.{k}"))[0]
                               for k, v in ast.get("kwargs", {}).items()}
                    res    = await self._invoke(call, args, kwargs, path=t_path)
                    return _flow_output(res)
                val, _ = await self.visit(ast, env_dict, path=t_path)
                if callable(val):
                    res = await self._invoke(val, [], {}, path=t_path)
                    return _flow_output(res)
                return val
            except Exception as e:
                return _flow_error(str(e), action=t_path)
        return task_fn


# ── FlowNodeBuilder (privato, usato solo da load_file) ────────────────────────

class _FlowNodeBuilder:
    """Raccoglie i task dall'AST senza valutare espressioni non necessarie."""

    def __init__(self, interpreter: Interpreter, task_sink: List[dict]):
        self._interp = interpreter
        self._tasks  = task_sink   # lista condivisa — i task vengono appesi qui

    async def build(self, ast: dict, env: Dict) -> None:
        await self._collect(ast, path="", env=env)

    async def _collect(self, node: Any, path: str, env: Dict) -> None:
        if not isinstance(node, dict):
            if isinstance(node, (list, tuple)):
                for item in node:
                    await self._collect(item, path, env)
            return

        t = node.get("type")

        if t == "task":
            task_name = node["trigger"]["name"]
            task_path = f"{path}.{task_name}" if path else task_name
            kwargs: Dict[str, Any] = {}
            for k, v in node["trigger"].get("kwargs", {}).items():
                try:
                    val, _ = await self._interp.visit(v, env)
                    kwargs[k] = val
                except Exception:
                    kwargs[k] = None

            self._tasks.append({
                "name":   task_name,
                "action": node["action"],
                "kwargs": kwargs,
                "path":   task_path,
            })
            return   # non scendere dentro l'action del task (scope separato)

        if t == "pair":
            key_node = node.get("key")
            key = key_node.get("name") if isinstance(key_node, dict) and "name" in key_node else str(key_node)
            await self._collect(node.get("value"), f"{path}.{key}" if path else key, env)
            return

        if t == "dict":
            for item in node.get("items", []):
                await self._collect(item, path, env)
            return

        for k, v in node.items():
            if k not in ("meta", "type"):
                await self._collect(v, path, env)