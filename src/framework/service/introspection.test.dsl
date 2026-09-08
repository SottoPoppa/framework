imports: {
    'introspection': import("framework.service.introspection")
};

exports: {
    'file_dependencies': imports.introspection.Reflection.file_dependencies
};

tuple:test_suite := (
    {
        "action": exports.file_dependencies;
        "inputs": "src/framework/scheme/session.json";
        "outputs": ["src/framework/scheme/session.json", "src/framework/scheme/user.json"];
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "file_dependencies risolve una variabile Jinja verso lo schema JSON user";
    },
    {
        "action": exports.file_dependencies;
        "inputs": "src/framework/service/introspection.test.dsl";
        "outputs": [
            "src/framework/service/introspection.test.dsl",
            "src/framework/service/introspection.py"
        ];
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "file_dependencies risolve i moduli dichiarati nel dizionario imports DSL"
    }
);
