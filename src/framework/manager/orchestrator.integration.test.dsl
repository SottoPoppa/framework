// Integration test: Orchestrator combinators on the local runtime

exports: {
    "first_completed": test.managers.orchestrator.first_completed;
    "all_completed": test.managers.orchestrator.all_completed;
    "chain_completed": test.managers.orchestrator.chain_completed;
    "together_completed": test.managers.orchestrator.together_completed
};

session:session := test.session;

tuple:test_suite := (
    {
        "action": exports.first_completed;
        "inputs": {"args": [session]; "kwargs": {"operations": []}};
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "first_completed gestisce una coda vuota senza operazioni"
    },
    {
        "action": exports.all_completed;
        "inputs": {"args": [session]; "kwargs": {"tasks": []}};
        "outputs": {};
        "assert": @received.outputs.results != none;
        "note": "all_completed conclude correttamente senza task"
    },
    {
        "action": exports.chain_completed;
        "inputs": {"args": [session]; "kwargs": {"tasks": []}};
        "outputs": true;
        "assert": @received.outputs.state == @expected;
        "note": "chain_completed conclude correttamente senza task"
    },
    {
        "action": exports.together_completed;
        "inputs": {"args": [session]; "kwargs": {"tasks": []}};
        "outputs": true;
        "assert": @received.outputs.state == @expected;
        "note": "together_completed avvia una coda vuota senza errori"
    }
);
