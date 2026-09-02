any:port_schema := "persistence";
any:adapter_schema := "persistence_adapter";

persistence:configuration := {
    "storage_type": "filesystem";
    "connection": {
        "endpoint_or_path": "src/";
        "driver_or_provider": "posix";
        "timeout_ms": 1000
    };
    "crud_permissions": {
        "allow_create": true;
        "allow_read": true;
        "allow_update": true;
        "allow_delete": true;
        "soft_delete": false
    };
    "persistence_policy": {
        "strategy": "immediate_write";
        "sync_flush": true
    }
};

security: {
    "encryption_at_rest": false;
    "audit": false;
    "soft_delete": false;
    "required_authentication": "filesystem_permissions"
};

policies: {
    policy:CREATE := { effect: "allow"; target: { action: "CREATE" }; condition: @action == "CREATE" };
    policy:READ := { effect: "allow"; target: { action: "READ" }; condition: @action == "READ" };
    policy:UPDATE := { effect: "allow"; target: { action: "UPDATE" }; condition: @action == "UPDATE" };
    policy:DELETE := { effect: "allow"; target: { action: "DELETE" }; condition: @action == "DELETE" }
};

rules: {
    "CREATE": [policies.CREATE];
    "READ": [policies.READ];
    "UPDATE": [policies.UPDATE];
    "DELETE": [policies.DELETE]
};
