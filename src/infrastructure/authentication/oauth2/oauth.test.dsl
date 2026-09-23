imports: {
    'module': import("infrastructure.authentication.oauth2.oauth")
};

any:provider := imports.module.Adapter(
    provider: "provider",
    token_url: "https://auth.example.test/token",
    authorization_endpoint: "https://auth.example.test/authorize",
    redirect_uri: "https://app.example.test/callback",
    client_id: "client",
    client_secret: "secret",
    grant_type: "password",
    auth_style: "body",
    scope: "api"
);

dict:oauth_session := {
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
    "headers": provider.get_headers;
    "user": provider.get_user;
    "authorization_url": provider.authorization_url;
    "token_expired": provider.token_expired
};

tuple:test_suite := (
    {
        "action": exports.headers;
        "inputs": (oauth_session,);
        "outputs": {"Authorization": "Bearer test-access-token"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "OAuth costruisce gli header dal token presente nella sessione";
    },
    {
        "action": exports.user;
        "inputs": (oauth_session,);
        "outputs": {"email": "user@example.test"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "OAuth recupera l'utente dalla sessione";
    },
    {
        "action": exports.authorization_url;
        "inputs": {"kwargs": {"state": "test-state"; "code_verifier": "test-code-verifier"}};
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value.code_challenge != none & @received.output.value.url != none;
        "note": "OAuth costruisce URL authorization con state e PKCE";
    },
    {
        "action": exports.token_expired;
        "inputs": {"args": [{"expires_at": 1}]};
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "OAuth riconosce un token scaduto dalla sessione";
    }
);