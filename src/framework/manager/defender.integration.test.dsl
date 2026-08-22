// Integration test: Defender -> authentication stub

exports: {
    "new_session": test.managers.defender.new_session;
    "activate": test.managers.defender.activate;
    "authenticate": test.managers.defender.authenticate;
    "reinstate": test.managers.defender.reinstate;
    "terminate": test.managers.defender.terminate;
    "get_policy": test.managers.defender.get_policy;
    "authorized": test.managers.defender.authorized;
    "resolve_route": test.managers.defender.resolve_route
};

session:session := test.session;
any:routes := {};

tuple:test_suite := (
    {
        "action": exports.new_session;
        "inputs": {"args": [session]};
        "outputs": none;
        "assert": @received != none;
        "note": "new_session restituisce la sessione corrente"
    },
    {
        "action": exports.activate;
        "inputs": {"args": [session]; "kwargs": {"email": "integration@example.test"; "password": "secret"}};
        "outputs": none;
        "assert": @received.user.email == @expected.user.email;
        "note": "activate registra l'utente tramite authentication stub"
    },
    {
        "action": exports.authenticate;
        "inputs": {"args": [session]; "kwargs": {"email": "integration@example.test"; "password": "secret"}};
        "outputs": none;
        "assert": @received.user.email == @expected.user.email;
        "note": "authenticate aggiorna la sessione usando authentication stub"
    },
    {
        "action": exports.reinstate;
        "inputs": {"args": [session]; "kwargs": {"email": "integration@example.test"; "password": "secret"}};
        "outputs": none;
        "assert": @received.user.email == @expected.user.email;
        "note": "reinstate ripristina l'identita dal provider stub"
    },
    {
        "action": exports.terminate;
        "inputs": {"args": [session]};
        "outputs": {};
        "assert": @received == @expected;
        "note": "terminate chiude la sessione tramite authentication stub"
    },
    {
        "action": exports.get_policy;
        "inputs": "missing";
        "outputs": none;
        "assert": @received == @expected;
        "note": "get_policy segnala una policy non caricata"
    },
    {
        "action": exports.authorized;
        "inputs": {"args": ["missing"]};
        "outputs": false;
        "assert": @received == @expected;
        "note": "authorized nega una policy inesistente senza provider esterno"
    },
    {
        "action": exports.resolve_route;
        "inputs": {"args": [routes, "/missing", "GET"]};
        "outputs": none;
        "assert": @received == @expected;
        "note": "resolve_route restituisce none per una rotta non registrata"
    }
);
