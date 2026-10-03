imports: {
    'module': import("framework.core.infrastructure");
};

any:infrastructure := imports.module.Infrastructure();

exports: {
    'resource': infrastructure.resource
};

tuple:test_suite := (
    {
        "action": exports.resource;
        "inputs": "pyproject.toml";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value.manager != none;
        "note": "resource converte il TOML in una configurazione accessibile"
    }
);