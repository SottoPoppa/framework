// Integration test: Defender -> policy e sessioni DSL

exports: {
    "session_create": test.managers.defender.session_create;
    "session_get": test.managers.defender.session_get;
    "get_policy": test.managers.defender.get_policy;
    "authorized": test.managers.defender.authorized;
    "get_configuration": test.managers.defender.get_configuration
};

tuple:test_suite := (
    {
        "action": exports.session_create;
        "inputs": {"kwargs": {"id": "defender-integration"}};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value != none;
        "note": "session_create registra una sessione nel runtime DSL"
    },
    {
        "action": exports.session_get;
        "inputs": "defender-integration";
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value != none;
        "note": "session_get recupera una sessione DSL registrata"
    },
    {
        "action": exports.get_policy;
        "inputs": "message";
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value != none;
        "note": "get_policy restituisce una policy caricata dal config"
    },
    {
        "action": exports.authorized;
        "inputs": {
            "args": ["message"];
            "kwargs": {
                "action": "publish";
                "request": {"provider": "console"; "receiver": "console"}
            }
        };
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "authorized applica la policy message caricata"
    },
    {
        "action": exports.get_configuration;
        "inputs": "message";
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value != none;
        "note": "get_configuration restituisce la configurazione validata della Port"
    },
    {
        "action": exports.authorized;
        "inputs": {"args": ["missing"]};
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "authorized nega una policy inesistente senza provider esterno"
    }
);
