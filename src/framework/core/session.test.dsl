imports: {
    'session': import("framework.core.session");
    'context': import("framework.core.context")
};

any:session_instance := imports.session.Session("demo", "sid", imports.context.ExecutionContext());
any:user_session := imports.session.UserSession("sid", imports.context.ExecutionContext());
exports: {
    'mark': session_instance.mark;
    'publish_result': user_session.publish_result;
    'get_result': user_session.get_result
};

tuple:test_suite := (
    {
        "action": exports.mark;
        "inputs": ("node", imports.session.NodeState.SUCCESS);
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Session.mark registra lo stato completato di un nodo"
    },
    {
        "action": exports.publish_result;
        "inputs": ("terminal", "selected", "src/application/controller/kanban.dsl");
        "outputs": "src/application/controller/kanban.dsl";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "UserSession.publish_result pubblica un risultato nel namespace del DAG"
    },
    {
        "action": exports.get_result;
        "inputs": ("terminal", "selected");
        "outputs": "src/application/controller/kanban.dsl";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "UserSession.get_result recupera un risultato pubblicato tramite dot-notation"
    }
);