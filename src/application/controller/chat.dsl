{
    message(default: "",entry:false) -> message;

    // I risultati degli altri controller vivono nella sessione utente.
    dependencies(entry: false) -> file_dependencies(@session.results.terminal.selected);

    send(entry:false, deps: ["dependencies"]) -> messenger.send(
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
            receiver: "copilot",
            domain: "general"
        );
    
    render_response(entry: false, deps: false) -> presenter.rebuild(
            "chat-response",
            {}
        );

}