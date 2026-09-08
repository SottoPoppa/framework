imports: {
    'context': import("framework.core.context")
};

any:execution_context := imports.context.ExecutionContext({"user": {"name": "Ada"}; "items": ["zero", "one"]});
exports: {
    'schema_definition': imports.context.schema_definition;
    'field_schema': imports.context.field_schema;
    'get': execution_context.get;
    'set': execution_context.set;
    'exists': execution_context.exists;
    'delete': execution_context.delete;
    'snapshot': execution_context.snapshot
};

tuple:test_suite := (
    {
        "action": exports.schema_definition;
        "inputs": {"age": {"type": "int"; "required": true;};};
        "outputs": {"age": {"type": "integer"; "required": true;};};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "schema_definition normalizza i tipi DSL nello schema Cerberus";
    },
    {
        "action": exports.field_schema;
        "inputs": {"args": [{"type": "list"; "schema": {"type": "string";};}]};
        "outputs": {"type": "list"; "schema": {"type": "string";};};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "field_schema normalizza lo schema di un campo lista";
    },
    {
        "action": exports.get;
        "inputs": "user.name";
        "outputs": "Ada";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "ExecutionContext.get risolve un percorso annidato";
    },
    {
        "action": exports.get;
        "inputs": ("user.missing", "fallback");
        "outputs": "fallback";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "ExecutionContext.get restituisce il default per un percorso assente";
    },
    {
        "action": exports.set;
        "inputs": ("user.role", "admin");
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "ExecutionContext.set crea e aggiorna percorsi annidati";
    },
    {
        "action": exports.exists;
        "inputs": "user.name";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "ExecutionContext.exists riconosce una chiave presente";
    },
    {
        "action": exports.delete;
        "inputs": "user.name";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "ExecutionContext.delete rimuove una chiave esistente";
    },
    {
        "action": exports.delete;
        "inputs": "user.missing";
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "ExecutionContext.delete segnala una chiave assente senza crash"
    },
    {
        "action": exports.snapshot;
        "inputs": ();
        "outputs": {"user": {"role": "admin"}; "items": ["zero", "one"]};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "ExecutionContext.snapshot restituisce una copia dello stato aggiornato"
    }
);