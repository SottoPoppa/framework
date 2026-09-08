imports: {
    'flow': import("framework.core.flow");
    'operator': import("operator")
};

exports: {
    'pipe_sync': imports.flow.pipe_sync;
    'is_result': imports.flow.is_result;
    'success': imports.flow.success;
    'check': imports.flow.check;
    'unwrap': imports.flow.unwrap;
    'output': imports.flow.output;
    'configure_dev_logging': imports.flow.configure_dev_logging;
    'map_put_map': imports.flow.map_put_map("user.name", "Ada");
    'map_freeze_map': imports.flow.map_freeze_map();
    'map_construct_value': imports.flow.map_construct_value(str, "user.name");
    'map_pick_map': imports.flow.map_pick_map("a", "missing");
    'map_keys_map': imports.flow.map_keys_map(str);
    'map_items_tuple': imports.flow.map_items_tuple();
    'map_select_key_tuple': imports.flow.map_select_key_tuple("github", true);
    'tuple_map_tuple': imports.flow.tuple_map_tuple(str);
    'tuple_map_async_tuple': imports.flow.tuple_map_async_tuple(imports.flow.success);
    'tuple_filter_tuple': imports.flow.tuple_filter_tuple(bool);
    'tuple_reduce_value': imports.flow.tuple_reduce_value(imports.operator.add);
    'tuple_flatten_tuple': imports.flow.tuple_flatten_tuple();
    'tuple_unique_tuple': imports.flow.tuple_unique_tuple();
    'tuple_group_by_map': imports.flow.tuple_group_by_map(str);
    'tuple_merge_map': imports.flow.tuple_merge_map();
    'tuple_validate_each_tuple': imports.flow.tuple_validate_each_tuple(bool, "invalid");
    'tuple_zip_tuple': imports.flow.tuple_zip_tuple(("a", "b"), true);
    'pipe_fork_async_tuple': imports.flow.pipe_fork_async_tuple(str, int);
    'flow_ensure_value': imports.flow.flow_ensure_value(bool, "invalid", str);
    'flow_branch_value': imports.flow.flow_branch_value(bool, str, int);
    'pipe_tap_value': imports.flow.pipe_tap_value(str);
    'pipe_foreach_tuple': imports.flow.pipe_foreach_tuple(str)
};

tuple:test_suite := (
    {
        "action": exports.pipe_sync;
        "inputs": ({"a": {"b": 42;};}, imports.flow.map_get_value("a.b"));
        "outputs": 42;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "pipe_sync esegue una pipeline sincrona di step";
    },
    {
        "action": exports.is_result;
        "inputs": "payload";
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "is_result restituisce false per un valore che non è un flow.Result (il DSL spacchetta sempre il Result restituito da una chiamata)";
    },
    {
        "action": exports.success;
        "inputs": "payload";
        "outputs": "payload";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "success conserva il payload del risultato Flow";
    },
    {
        "action": exports.check;
        "inputs": {"args": [imports.flow.error("invalid credentials")]};
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "check riconosce un risultato Flow fallito";
    },
    {
        "action": exports.unwrap;
        "inputs": exports.success("payload");
        "outputs": "payload";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "unwrap restituisce il valore di un Result riuscito";
    },
    {
        "action": exports.output;
        "inputs": {"args": [imports.flow.error("invalid credentials")]};
        "outputs": "invalid credentials";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "output estrae l'errore da un Result fallito";
    },
    {
        "action": exports.configure_dev_logging;
        "inputs": false;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "configure_dev_logging disattiva il tracing senza produrre un payload";
    },
    {
        "action": exports.map_put_map;
        "inputs": {"user": {};};
        "outputs": {"user": {"name": "Ada";};};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "map_put_map crea i livelli mancanti senza mutare la mappa"
    },
    {
        "action": exports.map_freeze_map;
        "inputs": {"nested": {"value": 1;};};
        "outputs": {"nested": {"value": 1;};};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "map_freeze_map congela anche i dizionari annidati"
    },
    {
        "action": exports.map_construct_value;
        "inputs": {"user": {"name": "Ada";};};
        "outputs": "Ada";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "map_construct_value passa alla factory i valori estratti dai path"
    },
    {
        "action": exports.map_pick_map;
        "inputs": {"a": 1; "b": 2;};
        "outputs": {"a": 1;};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "map_pick_map ignora le chiavi assenti"
    },
    {
        "action": exports.map_keys_map;
        "inputs": {"a": 1; "b": 2;};
        "outputs": {"a": 1; "b": 2;};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "map_keys_map trasforma le chiavi mantenendo i valori"
    },
    {
        "action": exports.map_items_tuple;
        "inputs": {"a": 1; "b": 2;};
        "outputs": (("a", 1), ("b", 2));
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "map_items_tuple converte una mappa in coppie ordinate"
    },
    {
        "action": exports.map_select_key_tuple;
        "inputs": {"name": {"github": "login";};};
        "outputs": (("login", "name"),);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "map_select_key_tuple supporta la selezione inversa"
    },
    {
        "action": exports.tuple_map_tuple;
        "inputs": {"args": [(1, 2)]};
        "outputs": ("1", "2");
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_map_tuple trasforma ogni elemento"
    },
    {
        "action": exports.tuple_map_async_tuple;
        "inputs": {"args": [(1, 2)]};
        "outputs": (imports.flow.success(1), imports.flow.success(2));
        "assert": @received.is_success == true & @received.output.value.0.value == 1 & @received.output.value.1.value == 2;
        "note": "tuple_map_async_tuple attende callback asincrone o awaitable"
    },
    {
        "action": exports.tuple_filter_tuple;
        "inputs": {"args": [(0, 1, 2)]};
        "outputs": (1, 2);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_filter_tuple elimina gli elementi falsy"
    },
    {
        "action": exports.tuple_reduce_value;
        "inputs": {"args": [(1, 2, 3)]};
        "outputs": 6;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_reduce_value riduce una sequenza senza accumulatore esplicito"
    },
    {
        "action": exports.tuple_flatten_tuple;
        "inputs": {"args": [((1, 2), 3, [4, 5])]};
        "outputs": (1, 2, 3, 4, 5);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_flatten_tuple appiattisce un livello"
    },
    {
        "action": exports.tuple_unique_tuple;
        "inputs": {"args": [(1, 1, 2, 1)]};
        "outputs": (1, 2);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_unique_tuple rimuove duplicati mantenendo l'ordine"
    },
    {
        "action": exports.tuple_group_by_map;
        "inputs": {"args": [(1, 1, 2)]};
        "outputs": {"1": (1, 1); "2": (2,);};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_group_by_map raggruppa i valori per chiave"
    },
    {
        "action": exports.tuple_merge_map;
        "inputs": {"args": [({"a": 1;}, {"b": 2;})]};
        "outputs": {"a": 1; "b": 2;};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_merge_map unisce più dizionari"
    },
    {
        "action": exports.tuple_validate_each_tuple;
        "inputs": {"args": [(1, 2)]};
        "outputs": (1, 2);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_validate_each_tuple conserva una sequenza valida"
    },
    {
        "action": exports.tuple_zip_tuple;
        "inputs": {"args": [(1, 2)]};
        "outputs": ((1, "a"), (2, "b"));
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "tuple_zip_tuple esegue lo zip strict su sequenze della stessa lunghezza"
    },
    {
        "action": exports.pipe_fork_async_tuple;
        "inputs": 3;
        "outputs": ("3", 3);
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "pipe_fork_async_tuple raccoglie i risultati di più rami"
    },
    {
        "action": exports.flow_ensure_value;
        "inputs": "ok";
        "outputs": "ok";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "flow_ensure_value valida e trasforma il valore"
    },
    {
        "action": exports.flow_branch_value;
        "inputs": 1;
        "outputs": "1";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "flow_branch_value seleziona il ramo vero"
    },
    {
        "action": exports.pipe_tap_value;
        "inputs": "value";
        "outputs": "value";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "pipe_tap_value mantiene invariato il dato"
    },
    {
        "action": exports.pipe_foreach_tuple;
        "inputs": {"args": [("a", "b")]};
        "outputs": ("a", "b");
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "pipe_foreach_tuple mantiene la sequenza dopo il side effect"
    }
);