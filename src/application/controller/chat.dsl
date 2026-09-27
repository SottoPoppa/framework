{
    message(default: "",entry:false) -> message;

    // I risultati degli altri controller vivono nella sessione utente.
    send(entry:false) -> messenger.send(
            session,
            adapter: "dsl",
            receiver: "kanban",
            message: {
                "dependencies": file_dependencies(@session.results.terminal.select);
                "request": @session.results.chat.message;
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