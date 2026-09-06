from collections import defaultdict, deque
from .errors import DagDefinitionError, NodeNotFound
class Dag:
    def __init__(self, definition):
        self.definition = definition; self.nodes = {}; self.successors = defaultdict(set)
        for node in definition.nodes:
            if node.name in self.nodes: raise DagDefinitionError(f'Duplicate node: {node.name}')
            self.nodes[node.name] = node
        for node in definition.nodes:
            for dep in node.deps:
                if dep not in self.nodes: raise DagDefinitionError(f'{node.name} depends on unknown node {dep}')
                self.successors[dep].add(node.name)
        self._validate()
    @property
    def name(self): return self.definition.name
    def get(self, name):
        if name not in self.nodes: raise NodeNotFound(name)
        return self.nodes[name]
    def entries(self): return tuple(n.name for n in self.definition.nodes if n.entry and not n.deps)
    def _validate(self):
        indegree = {n: len(v.deps) for n,v in self.nodes.items()}; q=deque(n for n,d in indegree.items() if d==0); count=0
        while q:
            n=q.popleft(); count+=1
            for child in self.successors[n]:
                indegree[child]-=1
                if indegree[child]==0: q.append(child)
        if count != len(self.nodes): raise DagDefinitionError(f'DAG {self.name!r} contains a cycle')
