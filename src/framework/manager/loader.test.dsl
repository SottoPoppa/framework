imports: {
    'module': import("framework.manager.loader");
    'framework_module': import("framework.core.framework");
    'infrastructure_module': import("framework.core.infrastructure")
};

any:framework := imports.framework_module.Framework();
any:infrastructure := imports.infrastructure_module.Infrastructure();
any:loader := imports.module.Loader(framework, infrastructure);

exports: {
    'imports': framework.imports;
    'component': framework.component;
    'import_module': infrastructure.import_module;
    'load_module': framework.load_module
};

tuple:test_suite := (
    {
        "action": exports.imports;
        "inputs": "import os";
        "outputs": true;
        "assert": @received.is_success == @expected;
        "note": "imports estrae un modulo Python dal sorgente"
    },
    {
        "action": exports.component;
        "inputs": "missing.component";
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "component restituisce none per una risorsa non registrata"
    },
    {
        "action": exports.import_module;
        "inputs": "framework.manager.loader";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value.Framework != none;
        "note": "import_module risolve un modulo framework reale senza fixture"
    },
    {
        "action": exports.load_module;
        "inputs": ("framework.service.scheme", "src/framework/service/scheme.py", {"schemes": {"test": {}}});
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value.schemes.test != none;
        "note": "load_module inietta gli extra anche in un modulo già importato"
    }
);