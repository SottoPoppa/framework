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
any:authorization_adapter := imports.module.Adapter(
    provider:"oauth2",
    url:"https://api.example.test",
    token_url:"https://auth.example.test/oauth/token",
    client_id:"client",
    client_secret:"secret",
    scope:"api",
    grant_type:"authorization_code",
    authorization_code:"temporary-code",
    redirect_uri:"https://client.example.test/callback"
);
any:password_adapter := imports.module.Adapter(
    provider:"oauth2",
    url:"https://api.example.test",
    token_url:"https://auth.example.test/oauth/token",
    client_id:"client",
    client_secret:"secret",
    grant_type:"password",
    username:"technical-user",
    password:"test-password",
    scope:"api"
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
    },
    {
        "action": authorization_adapter._token_payload;
        "inputs": {};
        "outputs": "authorization_code";
        "assert": @received.grant_type == @expected;
        "note": "OAuth2 adapter supporta il grant Authorization Code usato da GLPI";
    },
    {
        "action": authorization_adapter._token_payload;
        "inputs": {};
        "outputs": "temporary-code";
        "assert": @received.code == @expected;
        "note": "OAuth2 adapter invia il codice di autorizzazione al token endpoint";
    },
    {
        "action": password_adapter._token_payload;
        "inputs": {};
        "outputs": "password";
        "assert": @received.grant_type == @expected;
        "note": "OAuth2 adapter supporta il grant Password documentato da GLPI";
    },
    {
        "action": password_adapter._token_payload;
        "inputs": {};
        "outputs": "technical-user";
        "assert": @received.username == @expected;
        "note": "OAuth2 adapter invia lo username al token endpoint GLPI";
    }
);
