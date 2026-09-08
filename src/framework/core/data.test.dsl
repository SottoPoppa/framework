imports: {
    'data': import("framework.core.data")
};

any:registry := imports.data.Registry({"answer": 42});
exports: {
    'register': registry.register;
    'register_dict': registry.register_dict;
    'resolve': registry.resolve;
    'has': registry.has
};

tuple:test_suite := (
    {
        "action": exports.has;
        "inputs": "answer";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Registry.has trova un elemento del contesto iniziale";
    },
    {
        "action": exports.resolve;
        "inputs": "answer";
        "outputs": 42;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Registry.resolve restituisce il valore registrato";
    },
    {
        "action": exports.register;
        "inputs": ("name", "OmniPort");
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Registry.register aggiunge un nuovo elemento"
    },
    {
        "action": exports.register_dict;
        "inputs": {"other": 7;};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Registry.register_dict aggiunge più elementi in una sola operazione"
    },
    {
        "action": exports.has;
        "inputs": "missing";
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Registry.has restituisce false per una chiave assente"
    }
);