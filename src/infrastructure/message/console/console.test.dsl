imports: {
    'module': import("infrastructure.message.console.console");
    'infrastructure': import("framework.core.infrastructure");
    'session': import("framework.core.session")
};

any:adapter := imports.module.Adapter(none, imports.infrastructure.Infrastructure());

exports: {
    'can': adapter.can;
    'post': adapter.post;
    'read': adapter.read
};

tuple:test_suite := (
    {
        "action": exports.can;
        "inputs": {"name": "log"};
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Console message adapter accetta il processo log";
    },
    {
        "action": exports.can;
        "inputs": {"name": "unknown"};
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Console message adapter rifiuta un processo non supportato";
    },
    {
        "action": exports.post;
        "inputs": {"message": "audit event"; "domain": "authentication"; "action": "LOGIN"};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Console message adapter pubblica un evento audit senza persistenza";
    },
    {
        "action": exports.read;
        "inputs": {"domain": "*"};
        "outputs": [];
        "assert": @received.is_success == true & imports.session.pure_value(@received.output.value) == imports.session.pure_value(@expected);
        "note": "Console message adapter restituisce una coda vuota senza history attiva"
    }
);
