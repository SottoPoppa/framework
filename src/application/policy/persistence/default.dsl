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
    policy:SESSION_ACCESS := { effect: "allow"; target: { resource: "sessions" }; condition: (@action == "READ" | @action == "UPDATE") & @resource == "sessions" & @request.filter.eq.id == @session.id };
    policy:CREATE := { effect: "allow"; target: { action: "CREATE" }; condition: @action == "CREATE" & @session.user.id != none };
    policy:READ := { effect: "allow"; target: { action: "READ" }; condition: @action == "READ" & @session.user.id != none };
    policy:FILE_READ := { effect: "allow"; target: { action: "READ"; resource: "file" }; condition: @action == "READ" & @resource == "file" };
    policy:VIEW := { effect: "allow"; target: { action: "VIEW" }; condition: @action == "VIEW" };
    policy:UPDATE := { effect: "allow"; target: { action: "UPDATE" }; condition: @action == "UPDATE" & @session.user.id != none };
    policy:DELETE := { effect: "allow"; target: { action: "DELETE" }; condition: @action == "DELETE" & @session.user.id != none }
};

rules: {
    "sessions": [policies.SESSION_ACCESS];
    "CREATE": [policies.CREATE];
    "READ": [policies.READ, policies.FILE_READ];
    "VIEW": [policies.VIEW];
    "UPDATE": [policies.UPDATE];
    "DELETE": [policies.DELETE]
};
