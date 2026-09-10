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
    policy:DENY_COPILOT_BROADCAST := {
        effect: "deny";
        target: { action: "publish" };
        condition: @action == "publish" & @request.provider == "copilot" & @request.destination != "copilot"
    };
    policy:PUBLISH := {
        effect: "allow";
        target: { action: "publish" };
        condition: @action == "publish"
    };
    policy:SUBSCRIBE := { effect: "allow"; target: { action: "subscribe" }; condition: @action == "subscribe" }
};

rules: {
    "publish": [policies.DENY_COPILOT_BROADCAST, policies.PUBLISH];
    "subscribe": [policies.SUBSCRIBE]
};
