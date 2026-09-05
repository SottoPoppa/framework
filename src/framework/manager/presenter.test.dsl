imports: {
    'module': import("framework.manager.presenter");
    'stub': import("infrastructure.presentation.stub")
};

any:provider := imports.stub.Adapter(name: "stub");
any:presenter := imports.module.Manager(presentations: (provider), loader: none);

exports: {
    'rebuild': presenter.rebuild
};

tuple:test_suite := (
    {
        "action": exports.rebuild;
        "inputs": (none, "editors", "session-id", {});
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "rebuild inoltra node_id, session_id e context al presentation stub";
    }
);
