imports: {
    'module': import("framework.manager.defender")
};

any:defender := imports.module.Manager(none, ());

exports: {
    'capabilities_authorized': defender.capabilities_authorized;
    'compatible_adapters': defender.compatible_adapters
};

tuple:test_suite := (
    {
        "action": exports.compatible_adapters;
        "inputs": (none, "presentation", {"tls": true; "authentication": ["jwt"]}, [{"name": "secure"; "tls": true; "min_tls_version": "TLSv1.3"; "csrf": true; "authentication": ["jwt"]; "rate_limiting": true}, {"name": "legacy"; "tls": false; "min_tls_version": "TLSv1.2"; "csrf": false; "authentication": []}]);
        "outputs": "secure";
        "assert": @received.is_success == true & @received.output.value.0.name == @expected;
        "note": "compatible_adapters seleziona solo gli adapter conformi alla policy"
    },
    {
        "action": exports.capabilities_authorized;
        "inputs": (none, {"security": {"tls": true; "min_tls_version": "TLSv1.2"; "required_authentication": "jwt"}}, {"tls": true; "min_tls_version": "TLSv1.3"; "csrf": true; "authentication": ["jwt"]; "rate_limiting": true});
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Il Defender accetta un adapter presentation che soddisfa i requisiti di sicurezza"
    },
    {
        "action": exports.capabilities_authorized;
        "inputs": (none, {"security": {"tls": true; "min_tls_version": "TLSv1.2"; "required_authentication": "jwt"}}, {"tls": false; "authentication": []});
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Il Defender rifiuta un profilo presentation privo dei requisiti"
    }
);