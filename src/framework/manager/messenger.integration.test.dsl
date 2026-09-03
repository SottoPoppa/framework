// Integration test: Messenger -> message stub

exports: {
    "send": test.managers.messenger.send;
    "receive": test.managers.messenger.receive
};

session:session := test.session;

 tuple:test_suite := (
    {
        "action": exports.send;
        "inputs": {
            "args": [session];
            "kwargs": {
                "message": "integration-ping";
                "domain": "console:info"
            }
        };
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "Messenger.send deposita il messaggio nel message stub";
    },
    {
        "action": exports.receive;
        "inputs": {
            "args": [session];
            "kwargs": {
                "domain": "console:info"
            }
        };
        "outputs": {
            "message": "integration-ping";
            "domain": "info"
        };
        "assert": @received.output.value.message == @expected.message & @received.output.value.domain == @expected.domain;
        "note": "Messenger.receive recupera il messaggio dal message stub";
    }
);
