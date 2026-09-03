imports: {
    'module': import("framework.manager.messenger");
    'mock': import("infrastructure.message.mock");
};

any:provider := imports.mock.Adapter(name: "console");
any:messenger := imports.module.Manager(messages: (provider), defender: none);

exports: {
    'messenger': messenger
};

tuple:test_suite := (
    {
        "action": exports.messenger._split_domain;
        "inputs": "notifications.created";
        "outputs": (none, "notifications.created");
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "_split_domain conserva un dominio senza controller";
    },
    {
        "action": exports.messenger._split_domain;
        "inputs": "email:notifications.created";
        "outputs": ("email", "notifications.created");
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "_split_domain separa controller e dominio usando il primo separatore";
    },
    {
        "action": exports.messenger._split_domain;
        "inputs": "email:notifications:created";
        "outputs": ("email", "notifications:created");
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "_split_domain conserva i separatori successivi nel dominio";
    },
    {
        "action": exports.messenger._split_domain;
        "inputs": "console:info";
        "outputs": ("console", "info");
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "_split_domain prepara correttamente il routing usato dallo shutdown";
    },
    {
        "action": exports.messenger._split_domain;
        "inputs": none;
        "outputs": (none, none);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "_split_domain gestisce un dominio nullo senza crashare";
    },
    {
        "action": exports.messenger.send;
        "inputs": {
            "args": (none);
            "kwargs": {
                "message": "pong";
                "domain": "console:info"
            }
        };
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "send inoltra un messaggio al provider mock con il dominio normalizzato";
    },
    {
        "action": exports.messenger.receive;
        "inputs": {
            "args": (none);
            "kwargs": {
                "domain": "console:info"
            }
        };
        "outputs": {
            "message": "pong";
            "domain": "info"
        };
        "assert": @received.is_success == true & @received.output.value.message == @expected.message & @received.output.value.domain == @expected.domain;
        "note": "receive legge dal provider mock il messaggio inviato da send";
    }
);
