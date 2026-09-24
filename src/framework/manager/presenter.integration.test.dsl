// Integration test: Presenter -> presentation stub

imports: {
    "presentation_adapter": import("infrastructure.presentation.adapter")
};

exports: {
    "get_view": test.managers.presenter.get_view;
    "get_attribute": test.managers.presenter.get_attribute;
    "selector": test.managers.presenter.selector;
    "render": test.managers.presenter.render;
    "navigate": test.managers.presenter.navigate;
    "split_text_and_children": imports.presentation_adapter.split_text_and_children
};

session:user_session := test.session;

tuple:test_suite := (
    {
        "action": exports.get_view;
        "inputs": {"args": [user_session, "src/application/controller/kanban.dsl"]};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value != none;
        "note": "get_view legge una risorsa tramite il Loader"
    },
    {
        "action": exports.get_attribute;
        "inputs": {"args": [user_session]; "kwargs": {"widget": "missing"; "field": "value"}};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "get_attribute interroga il presentation stub"
    },
    {
        "action": exports.selector;
        "inputs": {"args": [user_session]; "kwargs": {"selector": "#target"}};
        "outputs": "#target";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "selector delega al presentation stub"
    },
    {
        "action": exports.render;
        "inputs": {"args": [user_session, "target", {}]};
        "outputs": {"rebuilt": true};
        "assert": @received.is_success == true & @received.output.value.rebuilt == @expected.rebuilt;
        "note": "render delega il rebuild al presentation stub"
    },
    {
        "action": exports.navigate;
        "inputs": {"args": [user_session]; "kwargs": {"url": "/integration"}};
        "outputs": {"url": "/integration"};
        "assert": @received.is_success == true & @received.output.value.url == @expected.url;
        "note": "navigate aggiorna la rotta del presentation stub"
    },
    {
        "action": exports.split_text_and_children;
        "inputs": [["hello", {"id": "child"}, " world"]];
        "outputs": ["hello world", [{"id": "child"}]];
        "assert": @received.is_success == true & @received.output.value.0 == "hello world" & @received.output.value.1 != none;
        "note": "split_text_and_children separa testo e figli"
    }
);
