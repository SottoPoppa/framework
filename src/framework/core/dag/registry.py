from .errors import FunctionNotFound
class FunctionRegistry:
    def __init__(self, functions=None): self._functions = dict(functions or {})
    def register(self, name, fn): self._functions[name] = fn; return fn
    def register_object(self, prefix, obj):
        for name in dir(obj):
            if not name.startswith('_'):
                value = getattr(obj, name)
                if callable(value): self.register(f'{prefix}.{name}', value)
    def resolve(self, name):
        try: return self._functions[name]
        except KeyError as exc: raise FunctionNotFound(name) from exc
