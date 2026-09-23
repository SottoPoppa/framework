imports: {
    'interpreter': import("framework.core.interpreter");
    'flow': import("framework.core.flow");
    'library': import("framework.core.library");
    'session': import("framework.core.session")
};

any:interpreter_instance := imports.interpreter.Interpreter();
any:record_getter := imports.flow.map_get_value("a");
any:path_match := imports.library.prefix_match("relative_path", "src/");
exports: {
    'call': interpreter_instance.call;
    'load_file': interpreter_instance.load_file;
    'map_records': imports.library.map_records;
    'variants': imports.library.variants;
    'flatten_records': imports.library.flatten_records;
    'path_match': path_match;
    'tuple_filter_tuple': imports.library.tuple_filter_tuple
};

tuple:test_suite := (
    {
        "action": exports.call;
        "inputs": (42,);
        "outputs": 42;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Interpreter.call avvolge un valore semplice in un risultato riuscito"
    },
    {
        "action": exports.load_file;
        "inputs": ("demo", 'path:value := "{% raw %}{{filter.eq.filename}}{% endraw %}";');
        "outputs": "demo";
        "assert": @received.is_success == true & @received.output.value.name == @expected;
        "note": "Interpreter.load_file conserva i placeholder runtime del DSL"
    },
    {
        "action": exports.map_records;
        "inputs": ([{"a": 1;}, 2], record_getter);
        "outputs": [1];
        "assert": @received.is_success == true & imports.session.pure_value(@received.output.value) == imports.session.pure_value(@expected);
        "note": "map_records applica il builder solo ai record mappa"
    },
    {
        "action": exports.variants;
        "inputs": {"kind": ["a", "b"]};
        "outputs": [{"key": "kind"; "value": "a";}, {"key": "kind"; "value": "b";}];
        "assert": @received.is_success == true & imports.session.pure_value(@received.output.value) == imports.session.pure_value(@expected);
        "note": "variants espande i valori di ciascun tag"
    },
    {
        "action": exports.flatten_records;
        "inputs": {"args": [[{"id": 1;}, [{"id": 2;}]]]};
        "outputs": [{"id": 1;}, {"id": 2;}];
        "assert": @received.is_success == true & imports.session.pure_value(@received.output.value) == imports.session.pure_value(@expected);
        "note": "flatten_records appiattisce ricorsivamente record annidati"
    },
    {
        "action": exports.path_match;
        "inputs": "src/main.py";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "prefix_match riconosce un percorso con il prefisso richiesto"
    },
    {
        "action": exports.tuple_filter_tuple;
        "inputs": ((0, 1, 2), bool);
        "outputs": (1, 2);
        "assert": @received.is_success == true & imports.session.pure_value(@received.output.value) == imports.session.pure_value(@expected);
        "note": "tuple_filter_tuple dell'interpreter elimina gli elementi falsy"
    }
);