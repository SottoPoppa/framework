imports: {
    'module': import("infrastructure.authentication.oauth")
};

any:provider := imports.module.Adapter(
    name: "provider",
    token_url: "https://auth.example.test/token",
    client_id: "client",
    client_secret: "secret",
    grant_type: "password",
    auth_style: "body",
    scope: "api"
);

dict:session := {
    "id": "oauth-test";
    "providers": {
        "provider": {
            "tokens": {
                "access_token": "test-access-token";
                "token_type": "Bearer"
            };
            "user": {
                "email": "user@example.test"
            }
        }
    }
};

exports: {
    "bool": provider._bool;
    "headers": provider.get_headers;
    "user": provider.get_user
};

tuple:test_suite := (
    {
        "action": exports.bool;
        "inputs": "true";
        "outputs": true;
        "assert": @received.outputs == @expected;
        "note": "OAuth interpreta il flag SSL testuale";
    },
    {
        "action": exports.bool;
        "inputs": "false";
        "outputs": false;
        "assert": @received.outputs == @expected;
        "note": "OAuth rifiuta il flag SSL disabilitato";
    },
    {
        "action": exports.headers;
        "inputs": (session,);
        "outputs": {"Authorization": "Bearer test-access-token"};
        "assert": @received.outputs == @expected;
        "note": "OAuth costruisce gli header dal token presente nella sessione";
    },
    {
        "action": exports.user;
        "inputs": (session,);
        "outputs": {"email": "user@example.test"};
        "assert": @received.outputs == @expected;
        "note": "OAuth recupera l'utente dalla sessione";
    }
);