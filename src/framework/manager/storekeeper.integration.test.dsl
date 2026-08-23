// Integration test reale: Storekeeper -> Repository file -> filesystem adapter

exports: {
    "store": test.managers.storekeeper.store;
    "gather": test.managers.storekeeper.gather;
    "remove": test.managers.storekeeper.remove
};

session:session := test.session;
any:resource := {
    "repository": "file";
    "provider": "workfolder";
    "filter": {"eq": {"filename": "integration-storekeeper.txt"}};
    "payload": {
        "path": "/tmp/integration-storekeeper.txt";
        "name": "integration-storekeeper";
        "extension": "txt";
        "content": "storekeeper integration"
    }
};

any:expected := {
    "path": "/tmp/integration-storekeeper.txt";
    "name": "integration-storekeeper";
    "extension": "txt";
    "mime_type": "application/octet-stream";
    "size": 23;
    "encoding": "utf-8";
    "content": "storekeeper integration";
    "metadata": {};
    "permissions": "";
    "owner": "";
    "created_at": none;
    "modified_at": none;
    "accessed_at": none
};

tuple:test_suite := (
    {
        "action": exports.store;
        "inputs": {
            "args": [session];
            "kwargs": resource
        };
        "outputs": expected;
        "assert": @received.outputs == @expected;
        "note": "Storekeeper.store persiste un record usando il repository file e il filesystem reale";
    },
    {
        "action": exports.gather;
        "inputs": {
            "args": [session];
            "kwargs": resource
        };
        "outputs": expected;
        "assert": @received.outputs == @expected;
        "note": "Storekeeper.gather legge il record persistito tramite lo stesso repository reale";
    },
    {
        "action": exports.remove;
        "inputs": {
            "args": [session];
            "kwargs": resource
        };
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Storekeeper.remove ripulisce la risorsa creata dal test integrativo";
    }
);
