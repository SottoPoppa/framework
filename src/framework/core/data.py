from typing import Any, Callable, Dict

class Registry:
    """Registry dinamico che accetta un contesto iniziale di funzioni, 
    dati calcolati, oggetti o moduli.
    """
    def __init__(self, initial_context: Dict[str, Any] = None):
        self._items: Dict[str, Any] = {}
        
        # Se viene passato un contesto iniziale (dizionario), lo carica
        if initial_context:
            self.register_dict(initial_context)

    def register(self, name: str, item: Any) -> None:
        """Registra un singolo elemento (funzione, dato, istanza, ecc.)."""
        self._items[name] = item

    def register_dict(self, items: Dict[str, Any]) -> None:
        """Registra un intero dizionario di elementi nel registry."""
        for name, item in items.items():
            self.register(name, item)

    def resolve(self, name: str) -> Any:
        """Restituisce l'elemento cercato se presente nel registry."""
        if name in self._items:
            return self._items[name]
        raise ValueError(f"Funzione o dato '{name}' non trovato nel Registry.")

    def has(self, name: str) -> bool:
        """Verifica se un elemento è registrato."""
        return name in self._items