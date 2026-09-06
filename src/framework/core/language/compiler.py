from dataclasses import dataclass
from ..dag.model import DagDefinition, NodeDefinition, ExecutionSpec, Literal, Ref, Call, TriggerDefinition
from .ast import Assignment, Task
@dataclass
class Compiler:
    def compile(self, program, *, name='main'):
        context={}; nodes=[]; triggers=[]
        for st in program.statements:
            if isinstance(st,Assignment): context[st.name]=self._expr(st.value)
            elif isinstance(st,Task):
                expr=self._expr(st.action); deps=tuple(sorted(self._refs(expr))) if st.deps else ()
                nodes.append(NodeDefinition(st.name,ExecutionSpec(expr),deps,st.entry))
                if st.on_end: triggers.append(TriggerDefinition(st.name,st.on_end))
        return DagDefinition.from_nodes(name,nodes,context=context,triggers=triggers)
    def _expr(self,v):
        if isinstance(v,tuple):
            if v and v[0]=='ref': return Ref(v[1])
            if v and v[0]=='call':
                _,fn,args,kw=v; return Call(fn,tuple(self._expr(x) for x in args),{k:self._expr(x) for k,x in kw.items()})
        if isinstance(v,list): return [self._expr(x) for x in v]
        if isinstance(v,dict): return {k:self._expr(x) for k,x in v.items()}
        return Literal(v)
    def _refs(self,x):
        if isinstance(x,Ref): return {x.path.split('.')[0]}
        if isinstance(x,Call): return set().union(*(self._refs(a) for a in x.arguments),*(self._refs(v) for v in x.keywords.values()))
        if isinstance(x,(list,tuple)): return set().union(*(self._refs(v) for v in x)) if x else set()
        if isinstance(x,dict): return set().union(*(self._refs(v) for v in x.values())) if x else set()
        return set()
