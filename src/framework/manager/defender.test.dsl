imports: {
    'module': import("framework.manager.defender")
};

exports: {
    'capabilities_authorized': imports.module.Manager.capabilities_authorized;
    'compatible_adapters': imports.module.Manager.compatible_adapters
};

tuple:test_suite := (
    {
        "action": exports.compatible_adapters;
        "inputs": (none, "presentation", {"tls": true; "authentication": ["jwt"]}, [{"name": "secure"; "tls": true; "min_tls_version": "TLSv1.3"; "csrf": true; "authentication": ["jwt"]; "rate_limiting": true}, {"name": "legacy"; "tls": false; "min_tls_version": "TLSv1.2"; "csrf": false; "authentication": []}]);
        "outputs": ["secure"];
        "assert": @received.outputs == @expected;
        "note": "compatible_adapters seleziona solo gli adapter conformi alla policy"
    },
    {
        "action": exports.capabilities_authorized;
        "inputs": (none, {"security": {"tls": true; "min_tls_version": "TLSv1.2"; "required_authentication": "jwt"}}, {"tls": true; "min_tls_version": "TLSv1.3"; "csrf": true; "authentication": ["jwt"]; "rate_limiting": true});
        "outputs": true;
        "assert": @received.outputs == @expected;
        "note": "Il Defender accetta un adapter presentation che soddisfa i requisiti di sicurezza"
    },
    {
        "action": exports.capabilities_authorized;
        "inputs": (none, {"security": {"tls": true; "min_tls_version": "TLSv1.2"; "required_authentication": "jwt"}}, {"tls": false; "authentication": []});
        "outputs": false;
        "assert": @received.outputs == @expected;
        "note": "Il Defender rifiuta un profilo presentation privo dei requisiti"
    }
);