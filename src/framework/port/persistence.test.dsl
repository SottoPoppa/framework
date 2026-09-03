imports: {
    'module': import("framework.port.persistence");
    'mock_module': import("infrastructure.persistence.mock")
};

any:mock := imports.mock_module.Adapter(name:"mock");

exports: {
    'create': imports.module.Port.create;
    'read': imports.module.Port.read;
    'update': imports.module.Port.update;
    'delete': imports.module.Port.delete;
    'query': imports.module.Port.query;
    'view': imports.module.Port.view;
    'mock': mock;
};

session:session := {"id": "persistence-test"};
any:record := {"location": "/items/1"; "payload": {"name": "item"}};

tuple:test_suite := (
    {
        "action": exports.create;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Persistence Port espone create come hook astratto";
    },
    {
        "action": exports.read;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Persistence Port espone read come hook astratto";
    },
    {
        "action": exports.update;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Persistence Port espone update come hook astratto";
    },
    {
        "action": exports.delete;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Persistence Port espone delete come hook astratto";
    },
    {
        "action": exports.query;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Persistence Port espone query come hook astratto";
    },
    {
        "action": exports.view;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Persistence Port espone view come hook astratto";
    },
    {
        "action": exports.mock.create;
        "inputs": {"session": session; "storekeeper": record};
        "outputs": "item";
        "assert": @received.is_success == true & @received.output.value.name == @expected;
        "note": "L'adapter mock crea una risorsa in memoria";
    },
    {
        "action": exports.mock.read;
        "inputs": {"session": session; "storekeeper": {"location": "/items/1"}};
        "outputs": "item";
        "assert": @received.is_success == true & @received.output.value.name == @expected;
        "note": "L'adapter mock legge una risorsa esistente";
    },
    {
        "action": exports.mock.update;
        "inputs": {"session": session; "storekeeper": {"location": "/items/1"; "payload": {"name": "updated"}}};
        "outputs": "updated";
        "assert": @received.is_success == true & @received.output.value.name == @expected;
        "note": "L'adapter mock aggiorna una risorsa in memoria";
    },
    {
        "action": exports.mock.delete;
        "inputs": {"session": session; "storekeeper": {"location": "/items/1"}};
        "outputs": {};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "L'adapter mock elimina una risorsa in memoria";
    }
);
