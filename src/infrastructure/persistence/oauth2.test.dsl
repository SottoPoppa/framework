imports: {
    'module': import("infrastructure.persistence.oauth2")
};

any:adapter := imports.module.Adapter(
    provider:"oauth2",
    url:"https://api.example.test",
    token_url:"https://auth.example.test/oauth/token",
    client_id:"client",
    client_secret:"secret",
    scope:"read write"
);

exports: {
    "adapter": adapter
};

tuple:test_suite := (
    {
        "action": adapter._url;
        "inputs": "/items/1";
        "outputs": "https://api.example.test/items/1";
        "assert": @received == @expected;
        "note": "OAuth2 adapter riusa la costruzione URL dell'adapter API";
    },
    {
        "action": adapter._token_payload;
        "inputs": {};
        "outputs": "client_credentials";
        "assert": @received.grant_type == @expected;
        "note": "OAuth2 adapter usa il grant client credentials";
    },
    {
        "action": adapter._token_payload;
        "inputs": {};
        "outputs": "read write";
        "assert": @received.scope == @expected;
        "note": "OAuth2 adapter include lo scope configurato nella richiesta token";
    },
    {
        "action": adapter._token_is_valid;
        "inputs": {};
        "outputs": false;
        "assert": @received == @expected;
        "note": "OAuth2 adapter non considera valido un token assente";
    }
);
