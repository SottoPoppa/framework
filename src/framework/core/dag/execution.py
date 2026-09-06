import inspect
from .model import Literal, Ref, Call, ExecutionSpec
from .errors import ExecutionFailed
class Executor:
    def __init__(self, registry): self.registry = registry
    async def execute(self, spec, context): return await self._eval(spec.expression if isinstance(spec, ExecutionSpec) else spec, context)
    async def _eval(self, x, context):
        if isinstance(x, Literal): return x.value
        if isinstance(x, Ref): return context.get(x.path)
        if isinstance(x, Call):
            fn = self.registry.resolve(x.function)
            args = [await self._eval(v, context) for v in x.arguments]
            kwargs = {k: await self._eval(v, context) for k,v in x.keywords.items()}
            try:
                value = fn(*args, **kwargs)
                return await value if inspect.isawaitable(value) else value
            except Exception as exc: raise ExecutionFailed(f'{x.function}: {exc}') from exc
        if isinstance(x, list): return [await self._eval(v, context) for v in x]
        if isinstance(x, tuple): return tuple([await self._eval(v, context) for v in x])
        if isinstance(x, dict): return {k: await self._eval(v, context) for k,v in x.items()}
        return x
