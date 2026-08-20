imports: {
    'module': import("framework.manager.storekeeper");
    'persistence': import("infrastructure.persistence.mock");
    'factory': import("framework.service.factory");
    'orchestrator': import("framework.manager.orchestrator");
    'messenger_module': import("framework.manager.messenger");
    'defender_module': import("framework.manager.defender")
};

any:provider := imports.persistence.Adapter(name:"test");
any:preparation_provider := imports.persistence.Adapter(name:"test");
any:repository := imports.factory.Repository(location: {"test": ["items/{{id}}"]});
any:orchestrator := imports.orchestrator.Manager(none);
any:messenger_defender := imports.defender_module.Manager(none, []);
any:messenger := imports.messenger_module.Manager(messages: [], defender: messenger_defender);
any:preparation_manager := imports.module.Manager(
    providers: [preparation_provider],
    defender: none,
    orchestrator: orchestrator,
    messenger: messenger,
    maked: {"items": repository}
);
any:manager := imports.module.Manager(
    providers: [provider],
    defender: none,
    orchestrator: orchestrator,
    messenger: messenger,
    maked: {"items": repository}
);

exports: {
    'startup': manager.startup;
    'shutdown': manager.shutdown;
    'preparation': imports.module.Manager.preparation;
    'overview': manager.overview;
    'gather': manager.gather;
    'store': manager.store;
    'remove': manager.remove;
    'change': manager.change
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
any:preparation_input := {
    "repository": "items";
    "provider": "test";
    "operation": "create";
    "id": "1";
    "payload": {"name": "created"}
};

tuple:test_suite := (
    {
        "action": exports.startup;
        "inputs": [session];
        "outputs": none;
        "assert": @received == @expected;
        "note": "startup invia il messaggio di avvio senza richiedere provider start";
    },
    {
        "action": exports.shutdown;
        "inputs": [session];
        "outputs": none;
        "assert": @received == @expected;
        "note": "shutdown invia il messaggio di arresto";
    },
    {
        "action": exports.preparation;
        "inputs": {
            "args": [preparation_manager, session, preparation_input]
        };
        "outputs": true;
        "assert": @received.0 != none & @received.1 != none;
        "note": "preparation carica il repository in cache e prepara il task del provider";
    },
    {
        "action": exports.store;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": "created";
        "assert": @received.name == @expected;
        "note": "Storekeeper.store inoltra create al provider configurato";
    },
    {
        "action": exports.gather;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": "created";
        "assert": @received.name == @expected;
        "note": "Storekeeper.gather inoltra read al provider configurato";
    },
    {
        "action": exports.overview;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": "created";
        "assert": @received.name == @expected;
        "note": "Storekeeper.overview inoltra view al provider configurato";
    },
    {
        "action": exports.change;
        "inputs": {
            "args": [session];
            "kwargs": updated
        };
        "outputs": "updated";
        "assert": @received.name == @expected;
        "note": "Storekeeper.change inoltra update al provider configurato";
    },
    {
        "action": exports.remove;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": {};
        "assert": @received == @expected;
        "note": "Storekeeper.remove inoltra delete al provider configurato";
    }
);