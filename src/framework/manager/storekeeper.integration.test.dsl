// Integration test reale: Storekeeper -> Repository DSL -> adapter in-memory

exports: {
    "store": test.managers.storekeeper.store;
    "gather": test.managers.storekeeper.gather
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
    "size": 0;
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
        "assert": @received == @expected;
        "note": "Storekeeper.store persiste una risorsa usando il repository file e il provider in-memory";
    },
    {
        "action": exports.gather;
        "inputs": {
            "args": [session];
            "kwargs": resource
        };
        "outputs": expected;
        "assert": @received == @expected;
        "note": "Storekeeper.gather legge la risorsa appena persistita tramite lo stesso repository";
    }
);
