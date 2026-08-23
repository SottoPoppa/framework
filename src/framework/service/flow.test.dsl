imports: {
    'flow': import("framework.service.flow");
};

exports: {
    'reset': imports.flow.reset;
    'switch': imports.flow.switch;
    'success': imports.flow.success;
    'transactions': imports.flow.transactions;
    'pipeline': imports.flow.pipeline
};

tuple:test_suite := (
    {
        "action": exports.reset;
        "inputs": (1, 2);
        "outputs": 2;
        "assert": @received.outputs == @expected;
        "note": "reset sostituisce il valore precedente";
    },
    {
        "action": exports.switch;
        "inputs": ({true: "fallback";}, {true: "selected";});
        "outputs": "selected";
        "assert": @received.outputs == @expected;
        "note": "switch usa il ramo true come fallback";
    },
    {
        "action": exports.success;
        "inputs": "payload";
        "outputs": "payload";
        "assert": @received.outputs == @expected;
        "note": "success conserva il payload del risultato Flow";
    },
    {
        "action": exports.transactions;
        "inputs": exports.success("payload");
        "outputs": [];
        "assert": @received.outputs == @expected;
        "note": "transactions espone dal DSL il registro interno di un Flow";
    },
    {
        "action": exports.pipeline;
        "inputs": ("payload", exports.success);
        "outputs": "payload";
        "assert": @received.outputs == @expected;
        "note": "pipeline conserva il payload dopo una chiamata interna Flow";
    }
);