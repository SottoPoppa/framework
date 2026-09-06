from lark import Lark, Transformer, v_args
from .ast import Program, Assignment, Task
from .grammar import GRAMMAR

class DSLTransformer(Transformer):
    def number(self, n):
        val = n[0].value
        return float(val) if "." in val else int(val)

    def string(self, s):
        val = s[0].value
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            return val[1:-1]
        return val

    def true(self, _):
        return True

    def false(self, _):
        return False

    def any_val(self, _):
        return None

    def identifier(self, s):
        return str(s[0])

    def context_var(self, s):
        return ("ref", str(s[0]))

    def dictionary_node(self, items):
        res = {}
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                res[item[0]] = item[1]
            elif isinstance(item, Assignment):
                res[item.name] = item.value
        return res

    def list_node(self, items):
        return list(items) if items else []

    def tuple_node(self, items):
        return tuple(items) if items else ()

    def pair(self, items):
        return (items[0], items[1])

    def declaration_target(self, items):
        return str(items[0])

    def declaration(self, items):
        target = items[0]
        val = items[-1]
        name = target if isinstance(target, str) else (target.name if hasattr(target, 'name') else str(target))
        return Assignment(name, val)

    def entry(self, items):
        key = items[0]
        val = items[1]
        key_str = key if isinstance(key, str) else (key.name if hasattr(key, 'name') else str(key))
        return Assignment(key_str, val)

    def function_call(self, items):
        fn_name = items[0]
        args = items[1] if len(items) > 1 else ()
        positional = []
        kw = {}
        if isinstance(args, (list, tuple)):
            for a in args:
                if isinstance(a, tuple) and len(a) == 2 and isinstance(a[0], str):
                    kw[a[0]] = a[1]
                else:
                    positional.append(a)
        return ("call", fn_name, tuple(positional), kw)

    def call_arg_list(self, items):
        return items

    def task(self, items):
        call_spec = items[0]
        target = items[1]
        fn_name = call_spec[1] if isinstance(call_spec, tuple) else str(call_spec)
        return Task(name=fn_name, action=call_spec, on_end=target)

    def sequence(self, items):
        if len(items) == 1:
            return items[0]
        return items

class Parser:
    def __init__(self, parser=None):
        if parser is not None:
            self.parser = parser
        else:
            self._lark = Lark(GRAMMAR, start="start", parser="earley")
            self._transformer = DSLTransformer()
            self.parser = None

    def parse(self, source: str) -> Program:
        if self.parser is not None:
            return self.parser.parse(source)
        tree = self._lark.parse(source)
        res = self._transformer.transform(tree)
        if isinstance(res, Program):
            return res
        if isinstance(res, list):
            return Program(tuple(res))
        if isinstance(res, dict):
            statements = tuple(Assignment(k, v) for k, v in res.items())
            return Program(statements)
        return Program((res,))
