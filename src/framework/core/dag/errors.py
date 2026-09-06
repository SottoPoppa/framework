class DagError(Exception): pass
class DagDefinitionError(DagError): pass
class NodeNotFound(DagError): pass
class FunctionNotFound(DagError): pass
class DependencyFailed(DagError): pass
class ExecutionFailed(DagError): pass
