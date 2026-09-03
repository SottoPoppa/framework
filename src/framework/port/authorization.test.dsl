imports: {
    'module': import("framework.port.authorization")
};

exports: {
    'load_data_store': imports.module.port.load_data_store;
    'load_policies': imports.module.port.load_policies
};

tuple:test_suite := (
    {
        "action": exports.load_data_store;
        "inputs": imports.module.port;
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Authorization Port richiede un adapter concreto per caricare il data store";
    },
    {
        "action": exports.load_policies;
        "inputs": imports.module.port;
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Authorization Port richiede un adapter concreto per caricare le policy"
    }
);
