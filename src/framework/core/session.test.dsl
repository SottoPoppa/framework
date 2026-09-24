imports: {
    'session': import("framework.core.session");
    'scope': import("framework.core.scope")
};

any:session_instance := imports.session.Session("demo", "sid", imports.scope.Scope());
any:session_data := imports.session.SessionData({
    "id": "sid";
    "context": {};
    "authentication": {};
    "results": {}
});
any:published_session := session_data.publish_result(
    "terminal",
    "selected",
    "src/application/controller/kanban.dsl"
);
exports: {
    'mark': session_instance.mark;
    'publish_result': session_data.publish_result;
    'get_result': published_session.get_result;
    'to_dict': published_session.to_dict;
    'to_json': published_session.to_json
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
        "outputs": {"id": "sid"; "context": {}; "authentication": {}; "results": {"terminal": {"selected": "src/application/controller/kanban.dsl"}}};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "SessionData.publish_result restituisce uno snapshot con il risultato"
    },
    {
        "action": exports.get_result;
        "inputs": ("terminal", "selected");
        "outputs": "src/application/controller/kanban.dsl";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "SessionData.get_result recupera un risultato pubblicato"
    },
    {
        "action": exports.to_dict;
        "inputs": ();
        "outputs": {"id": "sid"; "context": {}; "authentication": {}; "results": {"terminal": {"selected": "src/application/controller/kanban.dsl"}}};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "SessionData.to_dict espone solo dati JSON-safe e non il runtime DAG"
    },
    {
        "action": exports.to_json;
        "inputs": ();
        "outputs": '{"authentication": {}, "context": {}, "id": "sid", "results": {"terminal": {"selected": "src/application/controller/kanban.dsl"}}}';
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "SessionData.to_json serializza lo snapshot della sessione"
    }
);