from infrastructure.persistence.mock import Adapter as MemoryAdapter


class Adapter(MemoryAdapter):
    """Provider persistence deterministico per le integrazioni locali."""

    adapter = "stub"
