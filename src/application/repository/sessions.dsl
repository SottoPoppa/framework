/* Repository tecnico per lo stato di sessione server-side. */
factory:repository := {
    location: {
        "WORKFOLDER": [
            "/tmp/sessions/{% raw %}{{session.id}}{% endraw %}.json"
        ]
    };
};
