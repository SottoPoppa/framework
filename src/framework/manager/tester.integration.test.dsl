// Smoke test del runtime bootstrap-ato usato dagli integration test

exports: {
    "get_managers": test.loader.get_managers
};

tuple:test_suite := (
    {
        "action": exports.get_managers;
        "inputs": ();
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value.tester != none;
        "note": "il contesto di integrazione espone il Tester dal container reale";
    }
);
