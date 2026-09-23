imports: {
    'module': import("infrastructure.message.agent.copilot")
};

any:adapter := imports.module.Adapter(name: "copilot", test_mode: true);
session:session := test.session;

exports: {
    'can': adapter.can;
    'read': adapter.read
};

tuple:test_suite := (
    {
        "action": exports.can;
        "inputs": {"identity": "terminal"; "action": "read"};
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Copilot adapter espone la ricezione dei messaggi";
    },
    {
        "action": exports.can;
        "inputs": {"identity": "terminal"; "action": "post"};
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Copilot adapter non abilita la rete senza client configurato";
    },
    {
        "action": exports.read;
        "inputs": {
            "args": [session];
            "kwargs": {"domain": "*"}
        };
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Copilot adapter non blocca il test quando la coda e vuota";
    }
);