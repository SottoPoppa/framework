imports: {
    'flow': import("framework.core.flow");
};

exports: {
    'pipe_sync': imports.flow.pipe_sync;
    'is_result': imports.flow.is_result;
    'success': imports.flow.success;
    'check': imports.flow.check;
    'unwrap': imports.flow.unwrap;
    'output': imports.flow.output
};

tuple:test_suite := (
    {
        "action": exports.pipe_sync;
        "inputs": ({"a": {"b": 42;};}, imports.flow.map_get_value("a.b"));
        "outputs": 42;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "pipe_sync esegue una pipeline sincrona di step";
    },
    {
        "action": exports.is_result;
        "inputs": "payload";
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "is_result restituisce false per un valore che non è un flow.Result (il DSL spacchetta sempre il Result restituito da una chiamata)";
    },
    {
        "action": exports.success;
        "inputs": "payload";
        "outputs": "payload";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "success conserva il payload del risultato Flow";
    },
    {
        "action": exports.check;
        "inputs": {"args": [imports.flow.error("invalid credentials")]};
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "check riconosce un risultato Flow fallito";
    },
    {
        "action": exports.unwrap;
        "inputs": exports.success("payload");
        "outputs": "payload";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "unwrap restituisce il valore di un Result riuscito";
    },
    {
        "action": exports.output;
        "inputs": {"args": [imports.flow.error("invalid credentials")]};
        "outputs": "invalid credentials";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "output estrae l'errore da un Result fallito";
    }
);