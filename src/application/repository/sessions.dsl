/* Repository tecnico per lo stato di sessione server-side. */
factory:repository := {
    location: {
        "WORKFOLDER": [
            "/tmp/sessions/{{session.id}}.json"
        ]
    };
};
