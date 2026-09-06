from collections import defaultdict, deque


class DagDefinitionError(Exception):
    """Sollevata quando la struttura del DAG non è valida (cicli, dipendenze mancanti, nodi duplicati)."""
    pass


class NodeNotFound(Exception):
    """Sollevata quando si tenta di accedere a un nodo inesistente."""
    pass


class Dag:
    def __init__(self, definition):
        self.definition = definition
        self.nodes = {}
        self.successors = defaultdict(set)

        # 1. Indicizzazione e controllo duplicati
        for node in definition.nodes:
            if node.name in self.nodes:
                raise DagDefinitionError(f'Duplicate node: {node.name!r}')
            self.nodes[node.name] = node

        # 2. Risoluzione dipendenze e costruzione adiacenze
        # Una dipendenza è valida se è un altro task oppure è definita nel contesto
        context_keys = getattr(definition, 'context', {})

        for node in definition.nodes:
            for dep in node.dependencies:
                if dep not in self.nodes and dep not in context_keys:
                    raise DagDefinitionError(
                        f'Node {node.name!r} depends on unknown node/context variable {dep!r}'
                    )
                # Costruiamo il grafo dei successori solo tra i nodi di esecuzione (task)
                if dep in self.nodes:
                    self.successors[dep].add(node.name)

        self._validate()

    @property
    def name(self) -> str:
        return self.definition.name

    def get(self, name: str):
        if name not in self.nodes:
            raise NodeNotFound(f'Node {name!r} not found in DAG {self.name!r}')
        return self.nodes[name]

    def entries(self) -> tuple[str, ...]:
        """Ritorna i nomi dei nodi di ingresso (is_entry=True e nessuna dipendenza da altri task)."""
        return tuple(
            n.name for n in self.definition.nodes
            if n.is_entry and not any(dep in self.nodes for dep in n.dependencies)
        )

    def _validate(self):
        """Verifica l'assenza di cicli nel DAG tramite ordinamento topologico (Algoritmo di Kahn)."""
        # Consideriamo il grado di ingresso basato solo sulle dipendenze da altri task
        indegree = {
            n: sum(1 for dep in v.dependencies if dep in self.nodes)
            for n, v in self.nodes.items()
        }
        
        q = deque(n for n, d in indegree.items() if d == 0)
        count = 0

        while q:
            n = q.popleft()
            count += 1
            for child in self.successors[n]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    q.append(child)

        if count != len(self.nodes):
            raise DagDefinitionError(f'DAG {self.name!r} contains a cycle')