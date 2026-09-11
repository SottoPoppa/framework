{
    message(default: "",entry:false) -> message;

    send(entry:false, deps:false) -> messenger.send(
            session,
            receiver: "copilot",
            message: message,
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