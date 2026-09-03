imports: {
    'language': import("framework.core.language");
};

any:interpreter := imports.language.Interpreter();

exports: {
    'parse_only': interpreter.parse_only;
};

tuple:test_suite := (
    {
        "action": exports.parse_only;
        "inputs": "int:value := 10;";
        "outputs": true;
        "assert": @received.outputs != none;
        "note": "parse_only accetta una dichiarazione DSL valida";
    },
    {
        "action": exports.parse_only;
        "inputs": "int:other := 20;";
        "outputs": true;
        "assert": @received.outputs != none;
        "note": "parse_only gestisce una seconda dichiarazione DSL valida";
    }
);