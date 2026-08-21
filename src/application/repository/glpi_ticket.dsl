/* Repository GLPI per le operazioni CRUD sui ticket. */
factory:repository := {
    location: {
        "GLPI": [
            "/apirest.php/Ticket/{{filter.eq.id}}",
            "/apirest.php/Ticket"
        ]
    };

    model: glpi_ticket;

    envelope: "data";

    mapper: {
        "id": {"GLPI": "id"};
        "name": {"GLPI": "name"};
        "content": {"GLPI": "content"};
        "status": {"GLPI": "status"};
        "priority": {"GLPI": "priority"};
        "date_creation": {"GLPI": "date_creation"};
        "date_mod": {"GLPI": "date_mod"};
        "entity.id": {"GLPI": "entities_id"}
    };
};
