'''class Port(ABC):
    capabilities = {
        "sandboxed": True,
        "memory_isolation": True,
        "host_imports": [],
    }

    @abstractmethod
    async def load(self, module_bytes, **constants): pass

    @abstractmethod
    async def execute(self, function, inputs, allowed_capabilities, **constants): pass

    @abstractmethod
    async def terminate(self, **constants): pass'''