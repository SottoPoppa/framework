any:port_schema := "authentication";
any:adapter_schema := "authentication_adapter";

authentication:configuration := {
    "policy_name": "default";
    "allowed_methods": ["password"];
    "password_policy": {
        "min_length": 8;
        "require_uppercase": false;
        "require_lowercase": true;
        "require_numbers": false;
        "require_symbols": false
    };
    "mfa_policy": { "mode": "disabled" };
    "session_and_token": {
        "jwt_algorithm": "HS256";
        "access_token_ttl_seconds": 3600;
        "refresh_token_ttl_seconds": 86400;
        "enable_refresh_rotation": false
    };
    "account_lockout": {
        "enabled": false;
        "max_failed_attempts": 5;
        "lockout_duration_minutes": 15
    }
};

security: {
    "password_hashing": false;
    "mfa": false;
    "token_rotation": false;
    "sso": false;
    "account_lockout": false;
    "required_authentication": "password"
};

policies: {
    policy:SIGN_IN := { effect: "allow"; target: { action: "sign_in" }; condition: @action == "sign_in" };
    policy:SIGN_UP := { effect: "allow"; target: { action: "sign_up" }; condition: @action == "sign_up" };
    policy:SIGN_OUT := { effect: "allow"; target: { action: "sign_out" }; condition: @action == "sign_out" };
    policy:SIGN_AID := { effect: "allow"; target: { action: "sign_aid" }; condition: @action == "sign_aid" }
};

rules: {
    "sign_in": [policies.SIGN_IN];
    "sign_up": [policies.SIGN_UP];
    "sign_out": [policies.SIGN_OUT];
    "sign_aid": [policies.SIGN_AID]
};
