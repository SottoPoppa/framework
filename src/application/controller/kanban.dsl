/* Controller dichiarativo per la board Kanban SCRUM. */

files(entry: true) ->
    storekeeper.overview(
        repository: "file",
        filter: {"eq": {"type": "file"}}
    ) |> result();

/* Crea un task nel backlog. La policy gestisce l'autorizzazione. */
create_task(entry: false, on_end: "refresh_board") -> storekeeper.store(
    repository: "task",
    payload: {
        "id": format("task-{0}", random(100000, 999999));
        "title": @payload.title;
        "description": @payload.description;
        "file": @payload.file;
        "status": "backlog";
        "priority": @payload.priority;
        "created_at": "2026-09-12T00:00:00Z";
        "updated_at": none;
        "completed_at": none;
        }
);

refresh_board(entry: false, deps: false) -> presenter.rebuild(
    "kanban-board",
    {}
);

/* Transizioni di stato della board. */
move_to_todo(entry: false, on_end: "refresh_board") -> storekeeper.change(
    repository: "task",
    filter: {eq: {id: @payload.value}},
    payload: {status: "todo"}
);

move_to_inprogress(entry: false, on_end: "load_task_for_work") -> storekeeper.change(
    repository: "task",
    filter: {eq: {id: @payload.value}},
    payload: union(
        {status: "in_progress"},
        {assigned_to: @session.sid}
    )
);

load_task_for_work(entry: false, deps: false, on_end: "execute_task") -> storekeeper.gather(
    repository: "task",
    filter: {eq: {id: @payload.value}}
);

execute_task(entry: false, deps: false, on_end: "refresh_board") -> messenger.send(
        receiver: "copilot",
        message: "Sei un agente di implementazione. Devi eseguire realmente questo task Kanban usando omniport_terminal: prima esegui pwd e leggi SKILL.md, poi analizza il codice, modifica i file necessari, esegui i test e correggi gli errori. Una richiesta utente esplicita di creare o modificare un file è autorizzata e deve essere eseguita nel percorso richiesto, anche se il file è fuori da src/application. Verifica sempre il risultato con il terminale, per esempio con test -f e cat. Non limitarti a descrivere la soluzione e non dichiarare completato il task senza aver usato il terminale. Task selezionato:\n"
            + str(load_task_for_work)
            + "\nFile principale associato:\n"
            + str(load_task_for_work.0.file)
            + "\nFile correlati calcolati dal framework:\n"
            + str(file_dependencies(load_task_for_work.0.file))
            + "\nQuando hai terminato, riporta i file modificati, i test eseguiti e il risultato.",
        domain: "kanban.task"
    );

move_to_review(entry: false, on_end: "refresh_board") -> storekeeper.change(
    repository: "task",
    filter: {eq: {id: @payload.value}},
    payload: {status: "review"}
);

approve_task(entry: false, on_end: "refresh_board") -> storekeeper.change(
    repository: "task",
    filter: {eq: {id: @payload.value}},
    payload: {status: "done"}
);

reject_task(entry: false, on_end: "refresh_board") -> storekeeper.change(
    repository: "task",
    filter: {eq: {id: @payload.value}},
    payload: {status: "todo"}
);

reopen_task(entry: false, on_end: "refresh_board") -> storekeeper.change(
    repository: "task",
    filter: {eq: {id: @payload.value}},
    payload: {status: "todo"}
);

/* Carica tutti i task per la board. */
load_board(entry: true) -> storekeeper.gather(
    repository: "task"
);

todo_tasks(entry: true) -> storekeeper.gather(
    repository: "task",
    filter: {eq: {status: "todo"}}
);

in_progress_tasks(entry: true) -> storekeeper.gather(
    repository: "task",
    filter: {eq: {status: "in_progress"}}
);

work_tasks(
    entry: false,
    deps: ["todo_tasks", "in_progress_tasks"]
) -> messenger.send(
    receiver: "copilot",
    message: "File da considerare per primi, ma prima leggi SKILL.md se ancora non lo hai letto! :\n"
        + str(@payload.dependencies)
        + "\n\nTask Kanban in To Do:\n"
        + str(todo_tasks)
        + "\n\nTask Kanban in In Progress:\n"
        + str(in_progress_tasks)
        + "\n\nUsa questi task come contesto operativo. Identifica il task tramite il suo ID e non inventare task o stati.\n\nRichiesta dell'utente:\n"
        + str(@payload.request),
    domain: "general"
);