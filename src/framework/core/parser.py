from lark import Lark, Token, Transformer, v_args

from .ast import (
    AnyVal,
    ASTNode,
    BinaryOp,
    BoolLiteral,
    ContextVar,
    Declaration,
    DictNode,
    FunctionCall,
    FunctionDef,
    ListNode,
    NodeMeta,
    NotOp,
    NumberLiteral,
    Pair,
    PipeNode,
    Program,
    SequenceNode,
    StringLiteral,
    Task,
    TupleNode,
    Var,
)

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
?pipe: logic | logic (PIPE (pair|logic))+ -> pipe_node

?logic: comparison
      | ("not" | "!") logic        -> not_op
      | logic ("and" | "&") logic  -> and_op
      | logic ("or"  | "|") logic  -> or_op
      | logic ("in" | "~") logic   -> in_op

?comparison: sum
           | comparison COMPARISON_OP sum -> binary_op

?sum: term
    | sum ADD_OP term -> binary_op

?term: power
     | term MUL_OP power -> binary_op

?power: atom | atom "^" power -> power_op

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
ADD_OP: "+" | "-"
MUL_OP: "*" | "/" | "%"

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


@v_args(meta=True)
class DSLTransformer(Transformer):

    def _meta(self, meta) -> NodeMeta:
        if hasattr(meta, "line"):
            return NodeMeta(
                line=meta.line,
                column=meta.column,
                end_line=meta.end_line,
                end_column=meta.end_column,
            )
        return NodeMeta()

    def task(self, meta, items):
        items = [i for i in items if i is not None]
        return Task(trigger=items[0], action=items[1], meta=self._meta(meta))

    def number(self, meta, n):
        v = str(n[0])
        val = float(v) if "." in v else int(v)
        return NumberLiteral(value=val, meta=self._meta(meta))

    def string(self, meta, s):
        return StringLiteral(value=str(s[0])[1:-1], meta=self._meta(meta))

    def true(self, meta, _):
        return BoolLiteral(value=True, meta=self._meta(meta))

    def false(self, meta, _):
        return BoolLiteral(value=False, meta=self._meta(meta))

    def any_val(self, meta, _):
        return AnyVal(meta=self._meta(meta))

    def identifier(self, meta, s):
        return Var(name=str(s[0]), meta=self._meta(meta))

    def context_var(self, meta, s):
        return ContextVar(name=str(s[0]), meta=self._meta(meta))

    def function_value(self, meta, a):
        return FunctionDef(
            params=a[0], body=a[1], return_type=a[2], meta=self._meta(meta)
        )

    def sequence(self, meta, items):
        clean_items = tuple(i for i in items if i is not None)
        return SequenceNode(items=clean_items, meta=self._meta(meta))

    def call_arg(self, meta, items):
        return items[0]

    def _unwrap_items(self, items) -> tuple:
        clean = [i for i in items if i is not None]
        if len(clean) == 1 and isinstance(clean[0], SequenceNode):
            return clean[0].items
        return tuple(clean)

    def tuple_node(self, meta, items):
        return TupleNode(items=self._unwrap_items(items), meta=self._meta(meta))

    def list_node(self, meta, items):
        return ListNode(items=self._unwrap_items(items), meta=self._meta(meta))

    def dictionary_node(self, meta, items):
        clean_items = tuple(i for i in items if i is not None)
        return DictNode(items=clean_items, meta=self._meta(meta))

    def pair(self, meta, a):
        return Pair(key=a[0], value=a[1], meta=self._meta(meta))

    def entry(self, meta, a):
        return Pair(key=a[0], value=a[1], meta=self._meta(meta))

    def _extract_targets(self, node: ASTNode) -> tuple:
        if isinstance(node, Pair):
            t = node.key.name if isinstance(node.key, (Var, ContextVar)) else None
            v = node.value
            n = None
            if isinstance(v, (Var, ContextVar)):
                n = v.name
            elif isinstance(v, (StringLiteral, NumberLiteral)):
                n = str(v.value)
            return ((t, n),)

        if isinstance(node, SequenceNode):
            res = []
            for item in node.items:
                res.extend(self._extract_targets(item))
            return tuple(res)

        if isinstance(node, (Var, ContextVar)):
            return ((None, node.name),)

        return ()

    def declaration(self, meta, tree):
        target = tree[0]
        return Declaration(
            target=target,
            targets=self._extract_targets(target),
            value=tree[1],
            meta=self._meta(meta),
        )

    def function_call(self, meta, tree):
        fn = tree[0]
        lazy = isinstance(fn, ContextVar)
        raw_inputs = tree[1] if len(tree) > 1 else None

        inputs = []
        if isinstance(raw_inputs, SequenceNode):
            inputs = list(raw_inputs.items)
        elif raw_inputs is not None:
            inputs = [raw_inputs]

        args = []
        kwargs = {}
        for inp in inputs:
            if isinstance(inp, Pair):
                key_name = inp.key.name if isinstance(inp.key, (Var, ContextVar)) else str(inp.key)
                kwargs[key_name] = inp.value
            else:
                args.append(inp)

        fn_name = fn.name if isinstance(fn, (Var, ContextVar)) else None
        return FunctionCall(
            name=fn_name,
            args=tuple(args),
            kwargs=kwargs,
            lazy=lazy,
            meta=self._meta(meta),
        )

    def binary_op(self, meta, a):
        return BinaryOp(
            op=str(a[1]), left=a[0], right=a[2], meta=self._meta(meta)
        )

    def power_op(self, meta, a):
        if len(a) == 1:
            return a[0]
        return BinaryOp(op="^", left=a[0], right=a[1], meta=self._meta(meta))

    def not_op(self, meta, a):
        return NotOp(value=a[0], meta=self._meta(meta))

    def and_op(self, meta, a):
        return BinaryOp(op="and", left=a[0], right=a[1], meta=self._meta(meta))

    def or_op(self, meta, a):
        return BinaryOp(op="or", left=a[0], right=a[1], meta=self._meta(meta))

    def in_op(self, meta, a):
        return BinaryOp(op="in", left=a[0], right=a[1], meta=self._meta(meta))

    def pipe_node(self, meta, items):
        clean_items = tuple(
            i for i in items if not isinstance(i, Token) and i is not None
        )
        return PipeNode(steps=clean_items, meta=self._meta(meta))

    def start(self, meta, items):
        return items[0]


class Parser:

    def __init__(self, parser=None):
        if parser is not None:
            self.parser = parser
        else:
            self._lark = Lark(GRAMMAR, start="start", parser="lalr", propagate_positions=True)
            self._transformer = DSLTransformer()
            self.parser = None

    def parse(self, source: str) -> Program:
        if self.parser is not None:
            return self.parser.parse(source)

        tree = self._lark.parse(source)
        res = self._transformer.transform(tree)

        if isinstance(res, Program):
            return res
        if isinstance(res, (list, tuple)):
            return Program(statements=tuple(res))

        return Program(statements=(res,))
