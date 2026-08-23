imports: {
    'module': import("infrastructure.authentication.stub")
};

any:provider := imports.module.Adapter(name: "stub");

exports: {
    "sign_up": provider.sign_up;
    "sign_in": provider.sign_in
};

tuple:test_suite := (
    {
        "action": exports.sign_up;
        "inputs": {"email": "stub@example.test"; "password": "secret"};
        "outputs": none;
        "assert": @received.success == true & @received.outputs.user.email == "stub@example.test";
        "note": "sign_up crea un account nel provider authentication stub";
    },
    {
        "action": exports.sign_in;
        "inputs": {"email": "stub@example.test"; "password": "secret"};
        "outputs": none;
        "assert": @received.success == true & @received.outputs.user.email == "stub@example.test" & @received.outputs.providers.stub.tokens.access_token == "access-stub-example-test";
        "note": "sign_in verifica le credenziali e restituisce identita e token stub";
    }
);
