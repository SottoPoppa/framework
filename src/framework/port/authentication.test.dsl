imports: {
    'module': import("framework.port.authentication");
};

exports: {
    'sign_in': imports.module.Port.sign_in;
    'sign_up': imports.module.Port.sign_up;
    'sign_out': imports.module.Port.sign_out;
    'sign_aid': imports.module.Port.sign_aid;
    'get_user': imports.module.Port.get_user
};

tuple:test_suite := (
    {
        "action": exports.sign_in;
        "inputs": (imports.module.Port, "user@example.com", "secret");
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Authentication Port espone sign_in come hook astratto";
    },
    {
        "action": exports.sign_up;
        "inputs": (imports.module.Port, "user@example.com", "secret");
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Authentication Port espone sign_up come hook astratto";
    },
    {
        "action": exports.sign_out;
        "inputs": (imports.module.Port, "session");
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Authentication Port espone sign_out come hook astratto";
    },
    {
        "action": exports.sign_aid;
        "inputs": (imports.module.Port, "user@example.com");
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Authentication Port espone sign_aid come hook astratto";
    },
    {
        "action": exports.get_user;
        "inputs": (imports.module.Port, "session");
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Authentication Port espone get_user come hook astratto";
    }
);
