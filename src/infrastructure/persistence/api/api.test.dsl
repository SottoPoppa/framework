imports: {
    'module': import("infrastructure.persistence.api")
};

any:adapter := imports.module.Adapter(
    provider: "glpi",
    url: "https://glpi.example.test"
);
any:token_adapter := imports.module.Adapter(
    provider: "glpi",
    url: "https://glpi.example.test",
    access_token: "secret",
    expires_at: 4102444800,
    token_type: "Token"
);

session:session := {
    "id": "00000000-0000-0000-0000-000000000001";
    "providers": {};
    "user": {}
};

exports: {
    "adapter": adapter;
    "token_adapter": token_adapter
};

tuple:test_suite := (
    {
        "action": exports.adapter._api_url;
        "inputs": "Assistance/Ticket/1";
        "outputs": "https://glpi.example.test/api.php/v2.3/Assistance/Ticket/1";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Adapter._api_url costruisce il percorso API GLPI V2";
    },
    {
        "action": exports.adapter._headers;
        "inputs": {"headers": {"X-Test": "api"}; "has_body": true};
        "outputs": {"Accept": "application/json"; "Content-Type": "application/json"; "X-Test": "api"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Adapter._headers aggiunge Content-Type solo alle richieste con body";
    },
    {
        "action": exports.token_adapter._headers;
        "inputs": {};
        "outputs": "Token secret";
        "assert": @received.is_success == true & @received.output.value.Authorization == @expected;
        "note": "Adapter._headers usa il token OAuth esplicito e il suo tipo";
    },
    {
        "action": exports.adapter.request;
        "inputs": {"method": "GET"; "location": "Assistance/Ticket/1"; "session": session};
        "outputs": none;
        "assert": @received.is_success == false & @received.output.value == @expected;
        "note": "Adapter.request rifiuta una richiesta senza configurazione OAuth";
    },
    {
        "action": exports.adapter.create;
        "inputs": {
            "resource": "Assistance/Ticket";
            "payload": {"name": "OmniPort"};
            "session": session
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.value == @expected;
        "note": "Adapter.create richiede un token prima di inviare il payload";
    },
    {
        "action": exports.adapter.read;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "glpi"; "location": "Assistance/Ticket/1"; "operation": "read"; "repository": "tickets"}
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.value == @expected;
        "note": "Adapter.read applica il metodo GET del Port e richiede autenticazione";
    },
    {
        "action": exports.adapter.update;
        "inputs": {
            "resource": "Assistance/Ticket";
            "item_id": 1;
            "payload": {"name": "Aggiornato"};
            "session": session
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.value == @expected;
        "note": "Adapter.update applica PATCH e richiede autenticazione";
    },
    {
        "action": exports.adapter.delete;
        "inputs": {
            "resource": "Assistance/Ticket";
            "item_id": 1;
            "session": session
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.value == @expected;
        "note": "Adapter.delete applica DELETE e richiede autenticazione";
    },
    {
        "action": exports.adapter.query;
        "inputs": {
            "resource": "Assistance/Ticket";
            "session": session
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.value == @expected;
        "note": "Adapter.query delega alla lettura di una collezione autenticata";
    },
    {
        "action": exports.adapter.view;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "glpi"; "location": "Assistance/Ticket"; "operation": "view"; "repository": "tickets"}
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.value == @expected;
        "note": "Adapter.view applica la lettura del Port senza una risorsa implicita"
    }
);