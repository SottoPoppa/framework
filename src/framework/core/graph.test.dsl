imports: {
    'graph': import("framework.core.graph");
    'model': import("framework.core.model")
};

any:first_node := imports.model.NodeDefinition("first", imports.model.Literal(1));
any:second_node := imports.model.NodeDefinition("second", imports.model.Literal(2), ("first",), false);
any:definition := imports.model.DagDefinition.from_nodes("demo", (first_node, second_node));
any:dag := imports.graph.Dag(definition);
exports: {
    'get': dag.get;
    'entries': dag.entries
};

tuple:test_suite := (
    {
        "action": exports.get;
        "inputs": "first";
        "outputs": "first";
        "assert": @received.is_success == true & @received.output.value.name == @expected;
        "note": "Dag.get recupera un nodo indicizzato"
    },
    {
        "action": exports.entries;
        "inputs": ();
        "outputs": ("first",);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Dag.entries restituisce il nodo di ingresso"
    }
);