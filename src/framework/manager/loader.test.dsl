imports: {
    'module': import("framework.manager.loader");
};

any:framework := imports.module.Framework();
any:infrastructure := imports.module.Infrastructure();
any:loader := imports.module.Loader();

exports: {
    'imports': framework.imports;
    'component': framework.component;
    'import_module': infrastructure.import_module;
    'run_integration_tests': loader.run_integration_tests;
};

tuple:test_suite := (
    {
        "action": exports.imports;
        "inputs": "import os";
        "outputs": ["os"];
        "assert": @received == @expected;
        "note": "imports estrae un modulo Python dal sorgente";
    },
    {
        "action": exports.component;
        "inputs": "missing.component";
        "outputs": none;
        "assert": @received == @expected;
        "note": "component restituisce none per una risorsa non registrata";
    },
    {
        "action": exports.import_module;
        "inputs": "framework.manager.loader";
        "outputs": true;
        "assert": @received.Framework != none;
        "note": "import_module risolve un modulo framework reale senza fixture";
    },
    {
        "action": exports.run_integration_tests;
        "inputs": none;
        "outputs": false;
        "assert": @received == @expected;
        "note": "run_integration_tests fallisce in modo esplicito senza Tester nel container";
    }
);