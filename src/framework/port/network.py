from typing import Protocol, Any, Dict, AsyncGenerator, runtime_checkable
from abc import abstractmethod
import framework.core.flow as flow


@runtime_checkable
class Port(Protocol):
    """Porta topologica unificata per Reti Server/SD-WAN, Reti Neurali (RNN/LLM)

    e Architetture a Grafi.
    """

    capabilities: Dict[str, Any] = {
        "network_type": "generic",  # 'infrastructure', 'recurrent_neural_network', 'graph'
        "topological": True,
        "real_time_stream": False,
    }

    # Decoratori automatici applicati alle sottoclassi
    _method_decorators = {
        "provision": flow.result(inputs=("intent",), outputs=("deployment",)),
        "monitor": flow.result(outputs=("status",)),
        "status": flow.result(outputs=("status",)),
        "route": flow.result(inputs=("payload", "requirements"), outputs=("route",)),
    }

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method_name, decorator in cls._method_decorators.items():
            if method_name in cls.__dict__:
                original = cls.__dict__[method_name]
                setattr(cls, method_name, decorator(original))

    # ------------------------------------------------------------------
    # 1. Operazioni di Topologia (Nodi, Connessioni e Layer)
    # ------------------------------------------------------------------

    @abstractmethod
    async def add_node(self, node_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Aggiunge un nodo alla rete (es. Server/Router OPPURE Modello/Agente/Neurone)."""
        ...

    @abstractmethod
    async def remove_node(self, node_id: str) -> Dict[str, Any]:
        """Rimuove un nodo esistente dalla topologia."""
        ...

    @abstractmethod
    async def connect_nodes(
        self, src_node_id: str, dst_node_id: str, connection_spec: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """Crea un arco o canale tra due nodi (es. Tunnel VPN OPPURE Matrice di Pesi/Synapse)."""
        ...

    @abstractmethod
    async def disconnect_nodes(self, src_node_id: str, dst_node_id: str) -> Dict[str, Any]:
        """Rimuove l'arco/connessione tra due nodi."""
        ...

    @abstractmethod
    async def add_layer(self, layer_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Aggiunge un livello alla rete (es. Subnet/VLAN OPPURE Neural/Transformer Layer)."""
        ...

    @abstractmethod
    async def get_topology(self) -> Dict[str, Any]:
        """Restituisce il grafo della topologia attuale: { "nodes": [...], "edges": [...] }."""
        ...

    # ------------------------------------------------------------------
    # 2. Lifecycle & Management (Deploy, Scale, Migrate)
    # ------------------------------------------------------------------

    @abstractmethod
    async def deploy(self, deploy_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Deploya la rete o carica l'architettura (es. Container Cloud OPPURE Pesi LLM)."""
        ...

    @abstractmethod
    async def scale(self, scale_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Scala la capacità della rete (es. Aumenta Replica Pod OPPURE Quantizzazione VRAM/RAM)."""
        ...

    @abstractmethod
    async def migrate(self, migrate_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Migra nodi/carichi (es. Failover DataCenter OPPURE Device Offloading CPU->GPU)."""
        ...

    # ------------------------------------------------------------------
    # 3. Flusso Dati & Invocazione (Route, Provision, Compute, Monitor)
    # ------------------------------------------------------------------

    @abstractmethod
    async def provision(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def route(self, payload: Dict[str, Any], requirements: Dict[str, Any] | None = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def compute(self, *args, **kwargs) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def monitor(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def status(self) -> Dict[str, Any]:
        ...