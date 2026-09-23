imports: {
    'module': import("framework.manager.authenticator");
    'defender_module': import("framework.manager.defender")
};

any:defender := imports.defender_module.Manager(none, none, ());
any:authenticator := imports.module.Manager(none, defender, ());
session:session := {
    "id": "authenticator-test";
    "providers": {};
    "user": {}
};

exports: {
    'startup': authenticator.startup;
    'shutdown': authenticator.shutdown;
    'invalidate': authenticator.invalidate;
    'regenerate': authenticator.regenerate;
    'authenticate': authenticator.authenticate;
    'activate': authenticator.activate
};

tuple:test_suite := (
    {
        "action": exports.startup;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "startup avvia il lifecycle dell'Authenticator senza modificare la sessione"
    },
    {
        "action": exports.shutdown;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "shutdown chiude il lifecycle dell'Authenticator senza errori"
    },
    {
        "action": exports.invalidate;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "invalidate rifiuta una policy authentication non caricata"
    },
    {
        "action": exports.regenerate;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "regenerate rifiuta una policy authentication non caricata"
    },
    {
        "action": exports.authenticate;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "authenticate rifiuta una policy authentication non caricata"
    },
    {
        "action": exports.activate;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "activate rifiuta una policy authentication non caricata"
    }
);
