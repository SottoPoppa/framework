imports: {
    'contract': import("framework.service.contract")
};

any:path_a := "/tmp/contract-order-a.json";
any:path_b := "/tmp/contract-order-b.json";

exports: {
    'write': imports.contract.Contract.write;
    'keys': keys
};

any:data_z_a := {"z": 1; "a": 2};
any:data_a_z := {"a": 2; "z": 1};

tuple:test_suite := (
    {
        "action": exports.write;
        "inputs": (path_a, data_z_a);
        "outputs": none;
        "assert": @received.is_success == true;
        "note": "Contract.write accetta un contract con chiavi non ordinate";
    },
    {
        "action": exports.keys;
        "inputs": {"args": [imports.contract.Contract.read(path_a)]};
        "outputs": ["a", "z"];
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Contract.write serializza le chiavi in ordine canonico";
    },
    {
        "action": exports.write;
        "inputs": (path_b, data_a_z);
        "outputs": none;
        "assert": @received.is_success == true;
        "note": "Contract.write gestisce anche l'ordine inverso delle chiavi";
    },
    {
        "action": exports.keys;
        "inputs": {"args": [imports.contract.Contract.read(path_b)]};
        "outputs": ["a", "z"];
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Ordini di input diversi producono lo stesso testo JSON per Git"
    }
);
