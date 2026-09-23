imports: {
    'module': import("infrastructure.persistence.api.api")
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
        "action": exports.adapter.request;
        "inputs": {"method": "GET"; "location": "Assistance/Ticket/1"; "session": session};
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
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
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Adapter.create richiede un token prima di inviare il payload";
    },
    {
        "action": exports.adapter.read;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "glpi"; "location": "Assistance/Ticket/1"; "operation": "read"; "repository": "tickets"}
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
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
        "assert": @received.is_success == false & @received.output.error != none;
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
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Adapter.delete applica DELETE e richiede autenticazione";
    },
    {
        "action": exports.adapter.query;
        "inputs": {
            "resource": "Assistance/Ticket";
            "session": session
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Adapter.query delega alla lettura di una collezione autenticata";
    },
    {
        "action": exports.adapter.view;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "glpi"; "location": "Assistance/Ticket"; "operation": "view"; "repository": "tickets"}
        };
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Adapter.view applica la lettura del Port senza una risorsa implicita"
    }
);