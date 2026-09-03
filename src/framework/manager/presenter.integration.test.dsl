// Integration test: Presenter -> presentation stub

exports: {
    "get_view": test.managers.presenter.get_view;
    "get_attribute": test.managers.presenter.get_attribute;
    "selector": test.managers.presenter.selector;
    "render": test.managers.presenter.render;
    "navigate": test.managers.presenter.navigate;
    "sono_stessa_risorsa": test.managers.presenter.sono_stessa_risorsa;
    "split_text_and_children": test.managers.presenter.split_text_and_children;
    "estrai_attributi_tag": test.managers.presenter.estrai_attributi_tag;
    "estrai_da_xml_string": test.managers.presenter.estrai_da_xml_string
};

session:session := test.session;
any:xml := "<root><item id='target' value='ok' /></root>";

tuple:test_suite := (
    {
        "action": exports.get_view;
        "inputs": {"args": [session, "src/application/dsl.md"]};
        "outputs": none;
        "assert": @received.output.value != none;
        "note": "get_view legge una risorsa tramite il Loader"
    },
    {
        "action": exports.get_attribute;
        "inputs": {"args": [session]; "kwargs": {"widget": "missing"; "field": "value"}};
        "outputs": none;
        "assert": @received.output.value == @expected;
        "note": "get_attribute interroga il presentation stub"
    },
    {
        "action": exports.selector;
        "inputs": {"args": [session]; "kwargs": {"selector": "#target"}};
        "outputs": "#target";
        "assert": @received.output.value == @expected;
        "note": "selector delega al presentation stub"
    },
    {
        "action": exports.render;
        "inputs": {"args": [session, "target", {}]};
        "outputs": {"rebuilt": true};
        "assert": @received.output.value.rebuilt == @expected.rebuilt;
        "note": "render delega il rebuild al presentation stub"
    },
    {
        "action": exports.navigate;
        "inputs": {"args": [session]; "kwargs": {"url": "/integration"}};
        "outputs": {"url": "/integration"};
        "assert": @received.output.value.url == @expected.url;
        "note": "navigate aggiorna la rotta del presentation stub"
    },
    {
        "action": exports.sono_stessa_risorsa;
        "inputs": ["views/user.dsl", "src/views/user.dsl"];
        "outputs": true;
        "assert": @received.output.value == @expected;
        "note": "sono_stessa_risorsa confronta la coda dei percorsi"
    },
    {
        "action": exports.split_text_and_children;
        "inputs": [["hello", {"id": "child"}, " world"]];
        "outputs": ["hello world", [{"id": "child"}]];
        "assert": @received.output.value.0 == "hello world" & @received.output.value.1 != none;
        "note": "split_text_and_children separa testo e figli"
    },
    {
        "action": exports.estrai_attributi_tag;
        "inputs": "<item id='target' value='ok'>";
        "outputs": {"id": "target"; "value": "ok"};
        "assert": @received.output.value == @expected;
        "note": "estrai_attributi_tag legge gli attributi del tag"
    },
    {
        "action": exports.estrai_da_xml_string;
        "inputs": [xml, "target"];
        "outputs": true;
        "assert": @received.output.value != none;
        "note": "estrai_da_xml_string trova il nodo richiesto"
    }
);
