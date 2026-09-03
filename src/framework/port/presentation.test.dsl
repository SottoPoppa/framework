imports: {
    'module': import("framework.port.presentation")
};

exports: {
    'initialize': imports.module.Port.initialize;
    'mount_view': imports.module.Port.mount_view;
    'mount_route': imports.module.Port.mount_route;
    'mount_css': imports.module.Port.mount_css;
    'node_create': imports.module.Port.node_create;
    'node_update': imports.module.Port.node_update;
    'node_union': imports.module.Port.node_union;
    'node_get': imports.module.Port.node_get;
    'rebuild': imports.module.Port.rebuild;
    'normalize_route_path': imports.module.Port.normalize_route_path;
    'parse_reactive_event': imports.module.Port.parse_reactive_event;
    'resolve_controller_file': imports.module.Port.resolve_controller_file;
    'shutdown': imports.module.Port.shutdown;
};

tuple:test_suite := (
    {
        "action": exports.initialize;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port inizializza lo stato base senza restituire un valore";
    },
    {
        "action": exports.mount_view;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port espone mount_view come hook astratto";
    },
    {
        "action": exports.mount_route;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port espone mount_route come hook astratto";
    },
    {
        "action": exports.mount_css;
        "inputs": imports.module.Port;
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port espone mount_css come hook astratto";
    },
    {
        "action": exports.node_create;
        "inputs": (imports.module.Port, none, none);
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port espone node_create come hook astratto";
    },
    {
        "action": exports.node_update;
        "inputs": (imports.module.Port, none, none);
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port espone node_update come hook astratto";
    },
    {
        "action": exports.node_union;
        "inputs": (imports.module.Port, {"attrs": {"id": "counter"}; "inner": ["old"]}, {"attrs": {"class": "value"}; "inner": ["new"]});
        "outputs": {"attrs": {"id": "counter"; "class": "value"}; "inner": ["new"]};
        "assert": @received.output.value == @expected;
        "note": "Presentation Port unisce attributi e contenuto del descrittore DSL";
    },
    {
        "action": exports.node_union;
        "inputs": (imports.module.Port, none, {"attrs": {"class": "value"}});
        "outputs": {"attrs": {"class": "value"}; "inner": []};
        "assert": @received.output.value == @expected;
        "note": "Presentation Port gestisce un nodo assente durante una union";
    },
    {
        "action": exports.node_get;
        "inputs": (imports.module.Port, "missing");
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port ritorna none per un nodo DOM assente";
    },
    {
        "action": exports.rebuild;
        "inputs": (imports.module.Port, "missing");
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port espone rebuild come hook astratto";
    },
    {
        "action": exports.normalize_route_path;
        "inputs": "/users/{$id}";
        "outputs": "/users/{id}";
        "assert": @received.output.value == @expected;
        "note": "Presentation Port normalizza i placeholder delle route";
    },
    {
        "action": exports.parse_reactive_event;
        "inputs": {"type": "event"; "name": "counter:increment"};
        "outputs": {"alias": "counter"; "name": "increment"; "file": "src/application/controller/counter.dsl"};
        "assert": @received.output.value == @expected;
        "note": "Presentation Port interpreta gli eventi reactive senza dipendere dal trasporto";
    },
    {
        "action": exports.resolve_controller_file;
        "inputs": " counter ";
        "outputs": "src/application/controller/counter.dsl";
        "assert": @received.output.value == @expected;
        "note": "Presentation Port normalizza gli alias dei controller";
    },
    {
        "action": exports.shutdown;
        "inputs": ();
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Presentation Port espone un lifecycle di chiusura comune";
    }
);