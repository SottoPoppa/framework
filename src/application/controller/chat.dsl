{
    message(default: "",entry:false) -> message;

    // Accedi esplicitamente al namespace 'shared' per evitare ambiguità
    dependencies(entry: false) -> file_dependencies(shared.terminal.selected);

    send(entry:false, deps: ["dependencies"]) -> messenger.send(
            session,
            adapter: "dsl",
            receiver: "kanban",
            message: {
                "dependencies": dependencies;
                "request": message;
            },
            domain: "work_tasks"
        );

    copilot_source(
        entry: true,
        source: true,
        on_event: "render_response"
    ) -> messenger.receive(
            session,
            receiver: "copilot",
            domain: "general"
        );
    
    render_response(entry: false, deps: false) -> presenter.rebuild(
            session,
            "chat-response",
            {}
        );

}