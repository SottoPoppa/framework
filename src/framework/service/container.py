from collections import defaultdict
from typing import Any

class Container:
    """Singleton manager, istanze multiple adapter, porte collegate agli adapter."""

    def __init__(self) -> None:
        self._instances: dict[type[Any], list[Any]] = {}
        self._ports: defaultdict[type[Any] | str, list[Any]] = defaultdict(list)

    def _match(
        self, target: type[Any] | str, candidate_cls: type[Any] | str
    ) -> bool:
        """Verifica se una chiave o classe corrisponde a un target (classe o stringa parziale)."""
        if isinstance(target, str):
            search_str = target.lower()
            class_name = getattr(candidate_cls, '__name__', str(candidate_cls)).lower()
            module_name = getattr(candidate_cls, '__module__', '').lower()
            full_path = f"{module_name}.{class_name}"
            return search_str in class_name or search_str in full_path
        return candidate_cls is target or target == candidate_cls

    def put(self, cls: type[Any], obj: Any, singleton: bool = True) -> None:
        if singleton:
            self._instances[cls] = [obj]
        else:
            self._instances.setdefault(cls, []).append(obj)

    def get(self, cls: type[Any] | str) -> Any | None:
        # 1. Cerca per corrispondenza (classe o stringa) tra le istanze registrate
        for k, val in self._instances.items():
            if self._match(cls, k) and val:
                return val[-1]

        # 2. Fallback sul nome del modulo se cls è una classe
        mod_name = getattr(cls, '__module__', None) if not isinstance(cls, str) else None
        if mod_name:
            for k, val in self._instances.items():
                if getattr(k, '__module__', None) == mod_name and val:
                    return val[-1]
        return None

    def clear_port(self, iface: type[Any] | str) -> None:
        for k in list(self._ports.keys()):
            if self._match(iface, k):
                self._ports[k].clear()

    def remove(self, cls: type[Any] | str) -> None:
        keys_to_pop = [
            k for k in self._instances 
            if self._match(cls, k) or (not isinstance(cls, str) and getattr(cls, '__module__', None) == getattr(k, '__module__', None))
        ]
        for k in keys_to_pop:
            self._instances.pop(k, None)

        mod_name = getattr(cls, '__module__', None) if not isinstance(cls, str) else None
        for iface, objs in list(self._ports.items()):
            self._ports[iface] = [
                o for o in objs 
                if not (self._match(cls, o.__class__) or (mod_name and getattr(o.__class__, '__module__', None) == mod_name))
            ]

    def add_port(self, iface: type[Any] | str, obj: Any) -> None:
        self._ports[iface].append(obj)

    def get_port(self, iface: type[Any] | str) -> list[Any]:
        results: list[Any] = []
        
        # Se passi una stringa (es. "persistence", "network", ecc.)
        if isinstance(iface, str):
            for k, objs in self._ports.items():
                # Se la chiave è una stringa diretta o una classe/oggetto
                if isinstance(k, str):
                    if iface.lower() in k.lower():
                        results.extend(objs)
                else:
                    if self._match(iface, k):
                        results.extend(objs)
            return results
        
        # Altrimenti se passi la classe direttamente
        
        return self._ports[iface]