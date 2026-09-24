imports: {
    'module': import("framework.manager.presenter");
    'stub': import("infrastructure.presentation.stub");
    'framework_module': import("framework.core.framework")
};

any:provider := imports.stub.Adapter(name: "stub");
any:framework := imports.framework_module.Framework();
any:runtime_session := test.managers.defender.interpreter.open_session(sid: "presenter-test");
any:user_session := runtime_session.user_session;
any:presenter := imports.module.Manager(presentations: [provider], loader: test.managers.loader, framework: framework);

exports: {
    'rebuild': presenter.rebuild
};

tuple:test_suite := (
    {
        "action": exports.rebuild;
        "inputs": {"args": [user_session, "kanban-board", {}]};
        "outputs": {"rebuilt": true; "session_id": runtime_session.sid};
        "assert": @received.is_success == true & @received.output.value.rebuilt == @expected.rebuilt & @received.output.value.session_id != none & @received.output.value.session_id == @expected.session_id;
        "note": "rebuild risolve tramite Defender la SessionHandle associata alla UserSession";
    }
);
