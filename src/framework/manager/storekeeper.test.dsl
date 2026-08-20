imports: {
    'module': import("framework.manager.storekeeper");
    'persistence': import("infrastructure.persistence.mock");
    'factory': import("framework.service.factory");
    'orchestrator': import("framework.manager.orchestrator")
};

any:provider := imports.persistence.Adapter(name:"test");
any:repository := imports.factory.Repository(location: {"test": ["items/{{id}}"]});
any:orchestrator := imports.orchestrator.Manager(none);
any:manager := imports.module.Manager(
    providers: [provider],
    defender: none,
    orchestrator: orchestrator,
    messenger: none,
    maked: {"items": repository}
);

exports: {
    'manager': manager
};

session:session := {"id": "storekeeper-test"};
any:base := {
    "repository": "items";
    "provider": "test";
    "id": "1";
    "payload": {"name": "created"}
};
any:updated := {
    "repository": "items";
    "provider": "test";
    "id": "1";
    "payload": {"name": "updated"}
};

tuple:test_suite := (
    {
        "action": exports.manager.store;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": "created";
        "assert": @received.name == @expected;
        "note": "Storekeeper.store inoltra create al provider configurato";
    },
    {
        "action": exports.manager.gather;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": "created";
        "assert": @received.name == @expected;
        "note": "Storekeeper.gather inoltra read al provider configurato";
    },
    {
        "action": exports.manager.overview;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": "created";
        "assert": @received.name == @expected;
        "note": "Storekeeper.overview inoltra view al provider configurato";
    },
    {
        "action": exports.manager.change;
        "inputs": {
            "args": [session];
            "kwargs": updated
        };
        "outputs": "updated";
        "assert": @received.name == @expected;
        "note": "Storekeeper.change inoltra update al provider configurato";
    },
    {
        "action": exports.manager.remove;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": {};
        "assert": @received == @expected;
        "note": "Storekeeper.remove inoltra delete al provider configurato";
    }
);