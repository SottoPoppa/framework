imports: {
    'evaluation': import("framework.core.evaluation");
    'model': import("framework.core.model");
    'scope': import("framework.core.scope");
    'data': import("framework.core.data")
};

any:registry := imports.data.Registry({"double": int});
any:evaluator := imports.evaluation.Evaluator(registry);
any:bound := imports.scope.Scope({"action": "subscribe"});
any:empty := imports.scope.Scope();
any:condition := imports.model.Call("==", (imports.model.Ref("action", true), imports.model.Literal("subscribe")), {});

exports: {
    'evaluate': evaluator.evaluate;
    'resume': evaluator.resume
};

tuple:test_suite := (
    {
        "action": exports.evaluate;
        "inputs": (imports.model.Literal(7), empty);
        "outputs": 7;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Evaluator.evaluate restituisce il valore di un Literal"
    },
    {
        "action": exports.evaluate;
        "inputs": (condition, bound);
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Un percorso differibile gia legato viene valutato subito"
    },
    {
        "action": exports.evaluate;
        "inputs": (condition, empty);
        "outputs": "action";
        "assert": @received.is_success == true & @received.output.value.parameters == ("action",);
        "note": "Un percorso non legato produce un Deferred puro, non una closure"
    },
    {
        "action": exports.evaluate;
        "inputs": (imports.model.Ref("assente"), empty);
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Un Ref non differibile e assente vale none"
    }
);
