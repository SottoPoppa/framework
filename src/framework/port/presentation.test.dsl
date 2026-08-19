imports: {
    'module': import("framework.port.presentation")
};

exports: {
    'port': imports.module.Port
};

tuple:test_suite := (
    {
        "action": exports.port.initialize;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port inizializza lo stato base senza restituire un valore";
    },
    {
        "action": exports.port.mount_view;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port espone mount_view come hook astratto";
    },
    {
        "action": exports.port.mount_route;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port espone mount_route come hook astratto";
    },
    {
        "action": exports.port.mount_css;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port espone mount_css come hook astratto";
    },
    {
        "action": exports.port.node_create;
        "inputs": (imports.module.Port, none, none);
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port espone node_create come hook astratto";
    },
    {
        "action": exports.port.node_update;
        "inputs": (imports.module.Port, none, none);
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port espone node_update come hook astratto";
    },
    {
        "action": exports.port.node_union;
        "inputs": (imports.module.Port, {"attrs": {"id": "counter"}; "inner": ["old"]}, {"attrs": {"class": "value"}; "inner": ["new"]});
        "outputs": {"attrs": {"id": "counter"; "class": "value"}; "inner": ["new"]};
        "assert": @received == @expected;
        "note": "Presentation Port unisce attributi e contenuto del descrittore DSL";
    },
    {
        "action": exports.port.node_get;
        "inputs": (imports.module.Port, "missing");
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port ritorna none per un nodo DOM assente";
    },
    {
        "action": exports.port.rebuild;
        "inputs": (imports.module.Port, "missing");
        "outputs": none;
        "assert": @received == @expected;
        "note": "Presentation Port espone rebuild come hook astratto";
    },
    {
        "action": exports.port.normalize_route_path;
        "inputs": "/users/{$id}";
        "outputs": "/users/{id}";
        "assert": @received == @expected;
        "note": "Presentation Port normalizza i placeholder delle route";
    },
    {
        "action": exports.port.parse_reactive_event;
        "inputs": {"type": "event"; "name": "counter:increment"};
        "outputs": {"alias": "counter"; "name": "increment"; "file": "src/application/controller/counter.dsl"};
        "assert": @received == @expected;
        "note": "Presentation Port interpreta gli eventi reactive senza dipendere dal trasporto";
    }
);