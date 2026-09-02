from abc import ABC, abstractmethod
import framework.core.flow as flow

class Port(ABC):
    """Contratto comune per gli adapter di persistenza.

    Le operazioni CRUD lavorano sulle risorse del provider concreto.
    ``query`` restituisce una raccolta piatta e filtrabile, mentre ``view``
    restituisce una rappresentazione strutturata della risorsa, includendo
    quando disponibile metadati e relazioni tra gli elementi.

    Per esempio, un adapter filesystem può usare ``query`` per restituire
    tutti i file come lista e ``view`` per costruire l'albero delle directory
    con i relativi metadati. Un adapter HTTP delega invece questa semantica
    all'endpoint remoto.
    """

    capabilities = {
        "encryption_at_rest": False,
        "audit": False,
        "soft_delete": False,
        "authentication": [],
    }

    _method_decorators = {
        "create":      flow.result(inputs=("session","storekeeper"), ),
        "read":      flow.result(inputs=("session","storekeeper"), ),
        "update":     flow.result(inputs=("session","storekeeper"), ),
        "delete":     flow.result(inputs=("session","storekeeper"),),
        "query": flow.result(inputs=("session","storekeeper"), ),
        "view": flow.result(inputs=("session","storekeeper"),),
    }

    _seeds = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        for method_name, decorator in Port._method_decorators.items():
            original = cls.__dict__.get(method_name)

            if original is not None:
                setattr(cls, method_name, decorator(original))

    @abstractmethod
    async def request(self, *services, **constants):
        """Esegue l'operazione primaria usando il provider concreto."""
        pass

    @abstractmethod
    async def create(self,*services,**constants):
        """Crea una nuova risorsa nel provider."""
        pass

    @abstractmethod
    async def read(self,*services,**constants):
        """Legge il contenuto di una risorsa esistente."""
        pass

    @abstractmethod
    async def update(self,*services,**constants):
        """Aggiorna una risorsa esistente nel provider."""
        pass

    @abstractmethod
    async def delete(self,*services,**constants):
        """Elimina una risorsa dal provider."""
        pass

    @abstractmethod
    async def query(self,*services,**constants):
        """Cerca risorse e restituisce una raccolta piatta filtrabile."""
        pass

    @abstractmethod
    async def view(self,*services,**constants):
        """Restituisce una vista strutturata con metadati della risorsa."""
        pass