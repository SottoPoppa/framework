/* Repository per i Task della Kanban SCRUM */
factory:repository := {
    location: {
        "WORKFOLDER": [
            "tasks.json"
        ]
    };

    model: task;

    envelope: "tasks";
};
