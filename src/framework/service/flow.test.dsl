imports: {
    'flow': import("framework.service.flow");
};

exports: {
    'reset': imports.flow.reset;
    'switch': imports.flow.switch;
    'success': imports.flow.success;
    'transactions': imports.flow.transactions
};

tuple:test_suite := (
    {
        "action": exports.reset;
        "inputs": (1, 2);
        "outputs": 2;
        "assert": @received == @expected;
        "note": "reset sostituisce il valore precedente";
    },
    {
        "action": exports.switch;
        "inputs": ({true: "fallback";}, {true: "selected";});
        "outputs": "selected";
        "assert": @received == @expected;
        "note": "switch usa il ramo true come fallback";
    },
    {
        "action": exports.success;
        "inputs": "payload";
        "outputs": "payload";
        "assert": @received == @expected;
        "note": "success conserva il payload del risultato Flow";
    },
    {
        "action": exports.transactions;
        "inputs": exports.success("payload");
        "outputs": [];
        "assert": @received == @expected;
        "note": "transactions espone dal DSL il registro interno di un Flow";
    }
);