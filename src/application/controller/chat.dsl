{
    message(default: "",entry:false) -> message;

    // Accedi esplicitamente al namespace 'shared' per evitare ambiguità
    dependencies(entry: false) -> file_dependencies(shared.terminal.selected);

    send(entry:false, deps:false) -> messenger.send(
            session,
            receiver: "copilot",
            message: "File da considerare per primi, ma prima leggi SKILL.md se ancora non lo hai letto! :\n"
                + str(dependencies)
                + "\n\nRichiesta dell'utente:\n"
                + message,
            domain: "general"
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