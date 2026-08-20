imports: {
    'flow': import("framework.service.flow");
};

exports: {
    'reset': imports.flow.reset;
    'switch': imports.flow.switch
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
    }
);