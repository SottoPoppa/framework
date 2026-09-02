any:port_schema := "message";
any:adapter_schema := "message_adapter";

message:configuration := {
    "type": "event_bus";
    "url": "https://localhost/events";
    "tls": { "enabled": false; "verify_cert": false };
    "authentication": { "mechanism": "none" }
};

security: {
    "tls": false;
    "encryption": false;
    "audit": false;
    "rate_limiting": false
};

policies: {
    policy:PUBLISH := { effect: "allow"; target: { action: "publish" }; condition: @action == "publish" };
    policy:SUBSCRIBE := { effect: "allow"; target: { action: "subscribe" }; condition: @action == "subscribe" };
    policy:READ := { effect: "allow"; target: { action: "read" }; condition: @action == "read" }
};

rules: {
    "publish": [policies.PUBLISH];
    "subscribe": [policies.SUBSCRIBE];
    "read": [policies.READ]
};
