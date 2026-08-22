// Smoke test del runtime bootstrap-ato usato dagli integration test

exports: {
    "get_managers": test.loader.get_managers
};

tuple:test_suite := (
    {
        "action": exports.get_managers;
        "inputs": ();
        "outputs": true;
        "assert": @received.tester != none;
        "note": "il contesto di integrazione espone il Tester dal container reale";
    }
);
