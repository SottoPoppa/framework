imports: {
    'introspection': import("framework.service.introspection");
    'session': import("framework.core.session")
};

exports: {
    'file_dependencies': imports.introspection.Reflection.file_dependencies
};

tuple:test_suite := (
    {
        "action": exports.file_dependencies;
        "inputs": "src/framework/scheme/session.json";
        "outputs": ["src/framework/scheme/session.json", "src/framework/scheme/user.json"];
        "assert": @received.is_success == true & imports.session.pure_value(@received.output.value) == imports.session.pure_value(@expected);
        "note": "file_dependencies risolve una variabile Jinja verso lo schema JSON user";
    },
    {
        "action": exports.file_dependencies;
        "inputs": "src/framework/service/introspection.test.dsl";
        "outputs": [
            "src/framework/core/session.py",
            "src/framework/service/introspection.py",
            "src/framework/service/introspection.test.dsl"
        ];
        "assert": @received.is_success == true & imports.session.pure_value(@received.output.value) == imports.session.pure_value(@expected);
        "note": "file_dependencies risolve i moduli dichiarati nel dizionario imports DSL"
    }
);
