imports: {
    'module': import("infrastructure.persistence.oauth2");
    'storekeeper': import("framework.manager.storekeeper");
    'orchestrator': import("framework.manager.orchestrator");
    'factory': import("framework.service.factory");
    'os': import("os")
};

any:provider := imports.module.Adapter(
    name: imports.os.getenv("OAUTH2_PROVIDER") or "oauth2",
    url: imports.os.getenv("OAUTH2_URL"),
    token_url: imports.os.getenv("OAUTH2_TOKEN_URL"),
    client_id: imports.os.getenv("OAUTH2_CLIENT_ID"),
    client_secret: imports.os.getenv("OAUTH2_CLIENT_SECRET"),
    grant_type: imports.os.getenv("OAUTH2_GRANT_TYPE") or "password",
    auth_style: imports.os.getenv("OAUTH2_AUTH_STYLE") or "body",
    username: imports.os.getenv("OAUTH2_USERNAME"),
    password: imports.os.getenv("OAUTH2_PASSWORD"),
    scope: imports.os.getenv("OAUTH2_SCOPE") or "api",
    verify_ssl: (imports.os.getenv("OAUTH2_VERIFY_SSL") or "true") == "true"
);

any:repository := imports.factory.Repository(
    location: {
        "oauth2": [imports.os.getenv("OAUTH2_RESOURCE") or "Assistance/Ticket"]
    },
    model: "glpi_ticket"
);

any:manager := imports.storekeeper.Manager(
    providers: [provider],
    defender: none,
    orchestrator: imports.orchestrator.Manager(none),
    messenger: none,
    maked: {"oauth2": repository}
);

exports: {
    "gather": manager.gather
};

session:session := {"id": "oauth2-repository-integration-test"};

tuple:test_suite := (
    {
        "action": exports.gather;
        "inputs": {
            "args": [session];
            "kwargs": {
                "repository": "oauth2";
                "provider": imports.os.getenv("OAUTH2_PROVIDER") or "oauth2";
                "payload": {};
                "filter": {}
            }
        };
        "outputs": true;
        "assert": @received != none;
        "note": "Storekeeper normalizza la risposta OAuth2 nel modello JSON glpi_ticket";
    }
);
