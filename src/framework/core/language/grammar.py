"""Grammar del DSL."""

GRAMMAR = r"""
start: dictionary | [item (item)*] -> dictionary_node
dictionary: "{" [item (item)*] "}" -> dictionary_node
?item: declaration | entry | task
declaration: declaration_target ("," declaration_target)* ASSIGN_OP sequence ";"?
           | identifier ASSIGN_OP sequence ";"?
declaration_target: DECL_TARGET
entry.10: (atom|sequence) ":" sequence ";"?
task: function_call "->" sequence ";"? -> task
?sequence: expr ("," expr)* ","?
?expr: pipe
?pipe: logic
     | logic (PIPE (pair|logic))+ -> pipe_node
?logic: comparison
      | ("not" | "!") logic -> not_op
      | logic ("and" | "&") logic -> and_op
      | logic ("or" | "|") logic -> or_op
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
?atom.7: value | identifier | tuple | list | dictionary | function_call
?tuple: "(" [sequence] ")" -> tuple_node
pair.6: atom ":" expr
?list: "[" [sequence] "]" -> list_node
call_arg: expr | pair
call_arg_list: call_arg ("," call_arg)* ","? -> sequence
function_call: identifier "(" [call_arg_list] ")"
identifier: CNAME -> identifier
          | QUALIFIED_CNAME -> identifier
          | "@" CNAME -> context_var
          | "@" QUALIFIED_CNAME -> context_var
value: SIGNED_NUMBER -> number
     | STRING -> string
     | "true"i -> true
     | "false"i -> false
     | "none"i -> any_val
PIPE: "|>"
ASSIGN_OP: ":="
DECL_TARGET.2: /[A-Za-z_][A-Za-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*/
COLON_OP: ":"
COMPARISON_OP: "==" | "!=" | ">=" | "<=" | ">" | "<"
ARITHMETIC_OP: "+" | "-" | "*" | "/" | "%"
STRING: ESCAPED_STRING | SINGLE_QUOTED_STRING
SINGLE_QUOTED_STRING: /'[^']*'/
QUALIFIED_CNAME: CNAME ("." (CNAME|INT))+
INT : /[0-9]+/
%import common.SIGNED_NUMBER
%import common.ESCAPED_STRING
%import common.CNAME
%import common.WS
%ignore WS
COMMENT: /\/\/[^\n]*/ | /\/\*[\s\S]*?\*\//
%ignore COMMENT
"""
