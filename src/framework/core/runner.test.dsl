imports: {
    'runner': import("framework.core.runner");
    'model': import("framework.core.model");
    'session': import("framework.core.session");
    'scope': import("framework.core.scope");
    'registry': import("framework.core.data");
    'mock': import("unittest.mock");
    'asyncio': import("asyncio")
};

any:runner_instance := imports.runner.DagRunner();
any:first_node := imports.model.NodeDefinition("first", imports.model.Literal(1));
any:second_node := imports.model.NodeDefinition("second", imports.model.Literal(2), ("first",), false);
any:definition := imports.model.DagDefinition.from_nodes("demo", (first_node, second_node));
any:dag_session := imports.session.Session("demo", "test-session", imports.scope.Scope());
any:join_operation := imports.mock.AsyncMock(side_effect: imports.asyncio.sleep);
any:registry := imports.registry.Registry({"join": join_operation});
any:diamond_runner := imports.runner.DagRunner(registry, concurrency: 1);
any:diamond_first := imports.model.NodeDefinition("first", imports.model.Literal(1));
any:diamond_second := imports.model.NodeDefinition("second", imports.model.Literal(2));
any:diamond_join := imports.model.NodeDefinition(
    "join",
    imports.model.Call(
        "join",
        (imports.model.Literal(0.02), imports.model.Literal(none)),
        {}
    ),
    ("first", "second"),
    false
);
any:diamond_definition := imports.model.DagDefinition.from_nodes(
    "diamond",
    (diamond_first, diamond_second, diamond_join)
);
any:registered_diamond := diamond_runner.register(diamond_definition);
exports: {
    'register': runner_instance.register;
    'create_session': runner_instance.create_session;
    'run': runner_instance.run;
    'close_session': runner_instance.close_session;
    'run_diamond': diamond_runner.run
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
        "inputs": dag_session;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "DagRunner.close_session è idempotente per una sessione assente"
    },
    {
        "action": exports.run_diamond;
        "inputs": "diamond";
        "outputs": 1;
        "assert": @received.is_success == true & @received.output.value.states.join == "success" & join_operation.await_count == @expected;
        "note": "un nodo con predecessori multipli viene eseguito una sola volta"
    }
);