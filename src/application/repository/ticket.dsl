/* Repository GLPI per le operazioni CRUD sui ticket. */
factory:repository := {
    location: {
        "glpi": [
            "Assistance/Ticket/{{filter.eq.id}}",
            "Assistance/Ticket"
        ]
    };

    model: ticket;

    envelope: "data";

    mapper: {
        "id": {
            "GLPI": "id"
        };

        "name": {
            "GLPI": "name"
        };

        "content": {
            "GLPI": "content"
        };

        "status": {
            "GLPI": "status.id"
        };

        "priority": {
            "GLPI": "priority"
        };

        "date_creation": {
            "GLPI": "date_creation"
        };

        "date_mod": {
            "GLPI": "date_mod"
        };

        "entity.id": {
            "GLPI": "entity.id"
        }
    };
};