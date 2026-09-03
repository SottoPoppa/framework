// Verifica il lifecycle dell'Authenticator sul container reale con il provider stub

exports: {
    "startup": test.managers.authenticator.startup;
    "activate": test.managers.authenticator.activate;
    "authenticate": test.managers.authenticator.authenticate;
    "regenerate": test.managers.authenticator.regenerate;
    "invalidate": test.managers.authenticator.invalidate;
    "shutdown": test.managers.authenticator.shutdown
};

any:session := {
    "id": "authenticator-integration";
    "providers": {};
    "user": {}
};

any:credentials := {
    "email": "integration@example.test";
    "password": "integration-password"
};

tuple:test_suite := (
    {
        "action": exports.startup;
        "inputs": {"args": [session]};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Authenticator avvia il lifecycle senza alterare la sessione";
    },
    {
        "action": exports.activate;
        "inputs": {"args": [session]; "kwargs": credentials};
        "outputs": "integration@example.test";
        "assert": @received.is_success == true & @received.output.value.user.email == @expected;
        "note": "Authenticator registra un utente tramite il provider stub";
    },
    {
        "action": exports.authenticate;
        "inputs": {"args": [session]; "kwargs": credentials};
        "outputs": "integration@example.test";
        "assert": @received.is_success == true & @received.output.value.user.email == @expected;
        "note": "Authenticator autentica credenziali valide e aggiorna la sessione";
    },
    {
        "action": exports.regenerate;
        "inputs": {"args": [session]; "kwargs": credentials};
        "outputs": "integration@example.test";
        "assert": @received.is_success == true & @received.output.value.user.email == @expected;
        "note": "Authenticator rigenera l'identita tramite sign_aid del provider";
    },
    {
        "action": exports.invalidate;
        "inputs": {"args": [session]};
        "outputs": session;
        "assert": @received.is_success == true & @received.output.value.session == @expected;
        "note": "Authenticator invalida la sessione e rimuove identità e provider";
    },
    {
        "action": exports.shutdown;
        "inputs": {"args": [session]};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Authenticator chiude il lifecycle senza errori";
    }
);
