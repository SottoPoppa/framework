imports: {
    'runner': import("framework.core.runner");
    'model': import("framework.core.model");
    'session': import("framework.core.session");
    'context': import("framework.core.context")
};

any:runner_instance := imports.runner.DagRunner();
any:first_node := imports.model.NodeDefinition("first", imports.model.Literal(1));
any:second_node := imports.model.NodeDefinition("second", imports.model.Literal(2), ("first",), false);
any:definition := imports.model.DagDefinition.from_nodes("demo", (first_node, second_node));
any:session := imports.session.Session("demo", "test-session", imports.context.ExecutionContext());
exports: {
    'register': runner_instance.register;
    'create_session': runner_instance.create_session;
    'run': runner_instance.run;
    'close_session': runner_instance.close_session
};

tuple:test_suite := (
    {
        "action": exports.register;
        "inputs": definition;
        "outputs": "demo";
        "assert": @received.is_success == true & @received.output.value.name == @expected;
        "note": "DagRunner.register registra e restituisce il DAG"
    },
    {
        "action": exports.create_session;
        "inputs": "demo";
        "outputs": "demo";
        "assert": @received.is_success == true & @received.output.value.dag_name == @expected & @received.output.value.id != none;
        "note": "DagRunner.create_session crea una sessione associata al DAG"
    },
    {
        "action": exports.run;
        "inputs": "demo";
        "outputs": "success";
        "assert": @received.is_success == true & @received.output.value.states.first == @expected;
        "note": "DagRunner.run esegue il nodo di ingresso fino allo stato success"
    },
    {
        "action": exports.close_session;
        "inputs": session;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "DagRunner.close_session è idempotente per una sessione assente"
    }
);