imports: {
    'session': import("framework.core.session");
    'context': import("framework.core.context")
};

any:session_instance := imports.session.Session("demo", "sid", imports.context.ExecutionContext());
exports: {
    'mark': session_instance.mark
};

tuple:test_suite := (
    {
        "action": exports.mark;
        "inputs": ("node", imports.session.NodeState.SUCCESS);
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Session.mark registra lo stato completato di un nodo"
    }
);