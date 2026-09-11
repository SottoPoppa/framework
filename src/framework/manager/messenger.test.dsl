imports: {
    'module': import("framework.manager.messenger");
    'mock': import("infrastructure.message.mock");
};

any:provider := imports.mock.Adapter(name: "console");
any:messenger := imports.module.Manager(messages: (provider), defender: none);
session:session := test.session;

exports: {
    'messenger': messenger
};

tuple:test_suite := (
    {
        "action": exports.messenger.send;
        "inputs": {
            "args": (session);
            "kwargs": {
                "message": "pong";
                "adapter": "mock";
                "receiver": "console";
                "domain": "info"
            }
        };
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "send inoltra un messaggio al provider mock con il dominio normalizzato";
    },
    {
        "action": exports.messenger.receive;
        "inputs": {
            "args": (session);
            "kwargs": {
                "receiver": "console";
                "adapter": "mock";
                "domain": "info"
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
