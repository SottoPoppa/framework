imports: {
    'model': import("framework.core.model")
};

exports: {
    'literal': imports.model.Literal;
    'ref': imports.model.Ref;
    'call': imports.model.Call
};

tuple:test_suite := (
    {
        "action": exports.literal;
        "inputs": "value";
        "outputs": "value";
        "assert": @received.is_success == true & @received.output.value.value == @expected;
        "note": "Literal conserva il valore dell'espressione";
    },
    {
        "action": exports.ref;
        "inputs": "user.name";
        "outputs": "user.name";
        "assert": @received.is_success == true & @received.output.value.path == @expected & @received.output.value.lazy == false;
        "note": "Ref conserva il percorso e il flag lazy predefinito";
    },
    {
        "action": exports.call;
        "inputs": ("str", (1,), {});
        "outputs": "str";
        "assert": @received.is_success == true & @received.output.value.function == @expected & @received.output.value.arguments == (1,);
        "note": "Call descrive funzione, argomenti e keyword"
    }
);