imports: {
    'module': import("framework.manager.storekeeper");
    'persistence': import("infrastructure.persistence.mock");
    'factory': import("framework.service.factory");
    'orchestrator': import("framework.manager.orchestrator");
    'messenger_module': import("framework.manager.messenger");
    'defender_module': import("framework.manager.defender");
    'message': import("infrastructure.message.mock")
};

// Provider di persistenza mock usato dal ciclo CRUD.
any:provider := imports.persistence.Adapter(name:"test");
any:preparation_provider := imports.persistence.Adapter(name:"test");
// Il repository traduce il payload del provider nel modello canonico "file".
any:repository := imports.factory.Repository(
    location: {"test": ["items/{{id}}"]},
    model: {
        "path": {"type": "string"; "required": true; "empty": false};
        "name": {"type": "string"; "required": true; "empty": false};
        "extension": {"type": "string"; "required": true; "empty": false};
        "mime_type": {"type": "string"; "default": "application/octet-stream"};
        "size": {"type": "integer"; "default": 0};
        "encoding": {"type": "string"; "default": "utf-8"};
        "content": {"type": "string"; "default": ""};
        "metadata": {"type": "dict"; "default": {}};
        "permissions": {"type": "string"; "default": ""};
        "owner": {"type": "string"; "default": ""};
        "created_at": {"type": "datetime"; "nullable": true; "default": none};
        "modified_at": {"type": "datetime"; "nullable": true; "default": none};
        "accessed_at": {"type": "datetime"; "nullable": true; "default": none}
    },
    mapper: {
        "path": {"test": "provider_path"};
        "name": {"test": "provider_name"};
        "extension": {"test": "provider_extension"}
    }
);
any:orchestrator := imports.orchestrator.Manager(none);
any:messenger_defender := imports.defender_module.Manager(none, []);
// Provider message mock per verificare startup/shutdown end-to-end.
any:message_provider := imports.message.Adapter(name: "console");
any:messenger := imports.messenger_module.Manager(
    messages: [message_provider],
    defender: messenger_defender
);
any:preparation_manager := imports.module.Manager(
    providers: [preparation_provider],
    defender: none,
    orchestrator: orchestrator,
    messenger: messenger,
    maked: {"items": repository}
);
any:manager := imports.module.Manager(
    providers: [provider],
    defender: none,
    orchestrator: orchestrator,
    messenger: messenger,
    maked: {"items": repository}
);

// Le API del manager e la ricezione dei messaggi sono le operazioni esportate.
exports: {
    'startup': manager.startup;
    'shutdown': manager.shutdown;
    'receive_message': messenger.receive;
    'preparation': imports.module.Manager.preparation;
    'overview': manager.overview;
    'gather': manager.gather;
    'store': manager.store;
    'remove': manager.remove;
    'change': manager.change
};

session:session := {"id": "storekeeper-test"};
// Input provider-specifico: il mapper lo converte nei campi del modello file.
any:base := {
    "repository": "items";
    "provider": "test";
    "id": "1";
    "payload": {
        "provider_path": "/tmp/created.txt";
        "provider_name": "created";
        "provider_extension": "txt";
        "content": "created"
    }
};
any:updated := {
    "repository": "items";
    "provider": "test";
    "id": "1";
    "payload": {
        "provider_path": "/tmp/updated.txt";
        "provider_name": "updated";
        "provider_extension": "txt";
        "content": "updated"
    }
};
// Input minimo usato per verificare preparation e costruzione del task.
any:preparation_input := {
    "repository": "items";
    "provider": "test";
    "operation": "create";
    "id": "1";
    "payload": {
        "provider_path": "/tmp/created.txt";
        "provider_name": "created";
        "provider_extension": "txt";
        "content": "created"
    }
};
// Output atteso dopo mapper e normalizzazione del modello file, inclusi i default.
any:created_model := {
    "path": "/tmp/created.txt";
    "name": "created";
    "extension": "txt";
    "mime_type": "application/octet-stream";
    "size": 0;
    "encoding": "utf-8";
    "content": "created";
    "metadata": {};
    "permissions": "";
    "owner": "";
    "created_at": none;
    "modified_at": none;
    "accessed_at": none
};
any:updated_model := {
    "path": "/tmp/updated.txt";
    "name": "updated";
    "extension": "txt";
    "mime_type": "application/octet-stream";
    "size": 0;
    "encoding": "utf-8";
    "content": "updated";
    "metadata": {};
    "permissions": "";
    "owner": "";
    "created_at": none;
    "modified_at": none;
    "accessed_at": none
};

// Il flusso verifica startup, shutdown, preparation e CRUD nello stesso repository.
tuple:test_suite := (
    {
        "action": exports.startup;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "startup invia il messaggio di avvio senza richiedere provider start";
    },
    {
        "action": exports.receive_message;
        "inputs": {
            "args": [session];
            "kwargs": {"domain": "console:info"}
        };
        "outputs": {
            "message": "Storekeeper avviato.";
            "domain": "info"
        };
        "assert": @received.is_success == true & @received.output.value.message == @expected.message & @received.output.value.domain == @expected.domain;
        "note": "il messaggio di startup attraversa Messenger e viene ricevuto dal provider mock";
    },
    {
        "action": exports.shutdown;
        "inputs": [session];
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "shutdown invia il messaggio di arresto";
    },
    {
        "action": exports.receive_message;
        "inputs": {
            "args": [session];
            "kwargs": {"domain": "console:info"}
        };
        "outputs": {
            "message": "Storekeeper arrestato.";
            "domain": "info"
        };
        "assert": @received.is_success == true & @received.output.value.message == @expected.message & @received.output.value.domain == @expected.domain;
        "note": "il messaggio di shutdown attraversa Messenger e viene ricevuto dal provider mock";
    },
    {
        "action": exports.preparation;
        "inputs": {
            "args": [preparation_manager, session, preparation_input]
        };
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value.0 != none & @received.output.value.1 != none;
        "note": "preparation carica il repository in cache e prepara il task del provider";
    },
    {
        "action": exports.store;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": created_model;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Storekeeper.store inoltra create, applica la mappa provider e normalizza il modello file";
    },
    {
        "action": exports.gather;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": created_model;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Storekeeper.gather inoltra read e restituisce il modello file normalizzato";
    },
    {
        "action": exports.overview;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": created_model;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Storekeeper.overview inoltra view e restituisce il modello file normalizzato";
    },
    {
        "action": exports.change;
        "inputs": {
            "args": [session];
            "kwargs": updated
        };
        "outputs": updated_model;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Storekeeper.change inoltra update e riapplica mappa e modello";
    },
    {
        "action": exports.remove;
        "inputs": {
            "args": [session];
            "kwargs": base
        };
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Storekeeper.remove inoltra delete al provider configurato; il modello non normalizza una risposta vuota";
    }
);