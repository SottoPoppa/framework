imports: {
    'module': import("framework.manager.presenter");
    'stub': import("infrastructure.presentation.stub");
    'session_module': import("framework.core.session");
    'framework_module': import("framework.core.framework")
};

any:provider := imports.stub.Adapter(name: "stub");
any:framework := imports.framework_module.Framework();
any:presenter := imports.module.Manager(presentations: [provider], loader: none, framework: framework);
any:runtime_session := test.session;
any:execution_session := imports.session_module.Session(
    "kanban",
    "presenter-test",
    runtime_session: runtime_session
);

exports: {
    'rebuild': presenter.rebuild
};

tuple:test_suite := (
    {
        "action": exports.rebuild;
        "inputs": {"args": [execution_session, "kanban-board", {}]};
        "outputs": {"rebuilt": true; "session_id": runtime_session.sid};
        "assert": @received.is_success == true & @received.output.value.rebuilt == @expected.rebuilt & @received.output.value.session_id != none & @received.output.value.session_id == @expected.session_id;
        "note": "rebuild inoltra al driver la SessionHandle applicativa contenuta nella Session DAG";
    }
);
