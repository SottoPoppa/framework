/* Controller dichiarativo per la board Kanban SCRUM. */

files(entry: true) ->
    storekeeper.overview(
        session,
        repository: "file",
        filter: {"eq": {"type": "file"}},
        exclude_dirs: [
            ".git", ".venv", "venv", "__pycache__", "node_modules",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
            "cloud.colosso.egg-info"
        ]
    ) |> result();

/* Crea un task nel backlog. La policy gestisce l'autorizzazione. */
create_task(entry: false, on_end: "refresh_board") -> storekeeper.store(
    session,
    repository: "task",
    payload: {
        "id": format("task-{0}", random(100000, 999999));
        "title": @payload.title;
        "description": @payload.description;
        "file": @payload.file;
        "status": "backlog";
        "priority": @payload.priority;
        "created_at": utc_now();
        "updated_at": none;
        "started_at": none;
        "completed_at": none;
        }
);

refresh_board(entry: false, deps: false) -> presenter.rebuild(
    session,
    "kanban-board",
    {}
);

/* Transizioni di stato della board. */
move_to_todo(entry: false, on_end: "refresh_board") -> storekeeper.change(
    session,
    repository: "task",
    filter: {eq: {id: @payload.value; status: "backlog"}},
    payload: {status: "todo"; updated_at: utc_now()}
);

move_to_inprogress(entry: false, on_end: "load_task_for_work") -> storekeeper.change(
    session,
    repository: "task",
    filter: {eq: {id: @payload.value; status: "todo"}},
    payload: union(
        {status: "in_progress"; started_at: utc_now(); updated_at: utc_now()},
        {assigned_to: @session.authentication.user_id}
    )
);

load_task_for_work(entry: false, deps: false, on_end: "execute_task") -> storekeeper.gather(
    session,
    repository: "task",
    filter: {eq: {id: @payload.value}}
);

execute_task(entry: false, deps: false, on_end: "refresh_board") -> messenger.send(
    session,
        receiver: "copilot",
        message: "Sei un agente di implementazione. Devi eseguire realmente questo task Kanban usando omniport_terminal: prima esegui pwd e leggi SKILL.md, poi analizza il codice, modifica i file necessari, esegui i test e correggi gli errori. Una richiesta utente esplicita di creare o modificare un file è autorizzata e deve essere eseguita nel percorso richiesto, anche se il file è fuori da src/application. Verifica sempre il risultato con il terminale, per esempio con test -f e cat. Non limitarti a descrivere la soluzione e non dichiarare completato il task senza aver usato il terminale. Task selezionato:\n"
            + str(load_task_for_work.output.value.0)
            + "\nFile principale associato:\n"
            + str(load_task_for_work.output.value.0.file)
            + "\nFile correlati calcolati dal framework:\n"
            + str(file_dependencies(load_task_for_work.output.value.0.file))
            + "\nQuando hai terminato, riporta i file modificati, i test eseguiti e il risultato.",
        domain: "general"
    );

move_to_review(entry: false, on_end: "refresh_board") -> storekeeper.change(
    session,
    repository: "task",
    filter: {eq: {id: @payload.value; status: "in_progress"}},
    payload: {status: "review"; updated_at: utc_now()}
);

approve_task(entry: false, on_end: "refresh_board") -> storekeeper.change(
    session,
    repository: "task",
    filter: {eq: {id: @payload.value; status: "review"}},
    payload: {status: "done"; updated_at: utc_now(); completed_at: utc_now()}
);

reject_task(entry: false, on_end: "refresh_board") -> storekeeper.change(
    session,
    repository: "task",
    filter: {eq: {id: @payload.value; status: "review"}},
    payload: {status: "todo"; updated_at: utc_now(); completed_at: none}
);

reopen_task(entry: false, on_end: "refresh_board") -> storekeeper.change(
    session,
    repository: "task",
    filter: {eq: {id: @payload.value; status: "done"}},
    payload: {
        status: "todo";
        assigned_to: none;
        updated_at: utc_now();
        completed_at: none;
    }
);

/* Carica tutti i task per la board. */
load_board(entry: true) -> storekeeper.gather(
    session,
    repository: "task"
);

todo_tasks(entry: true) -> storekeeper.gather(
    session,
    repository: "task",
    filter: {eq: {status: "todo"}}
);

in_progress_tasks(entry: true) -> storekeeper.gather(
    session,
    repository: "task",
    filter: {eq: {status: "in_progress"}}
);

work_tasks(
    entry: false,
    deps: false,
    on_end: "load_todo_tasks_for_work"
) -> @payload;

load_todo_tasks_for_work(
    entry: false,
    deps: false,
    on_end: "load_in_progress_tasks_for_work"
) -> storekeeper.gather(
    session,
    repository: "task",
    filter: {eq: {status: "todo"}}
);

load_in_progress_tasks_for_work(
    entry: false,
    deps: false,
    on_end: "send_work_tasks"
) -> storekeeper.gather(
    session,
    repository: "task",
    filter: {eq: {status: "in_progress"}}
);

send_work_tasks(entry: false, deps: false) -> messenger.send(
    session,
    receiver: "copilot",
    message: "File da considerare per primi, ma prima leggi SKILL.md se ancora non lo hai letto! :\n"
        + str(@payload.dependencies)
        + "\n\nTask Kanban in To Do:\n"
        + str(load_todo_tasks_for_work.output.value)
        + "\n\nTask Kanban in In Progress:\n"
        + str(load_in_progress_tasks_for_work.output.value)
        + "\n\nUsa questi task come contesto operativo. Se la richiesta chiede di agire su un task, richiedi un ID esatto presente nell'elenco e opera solo su quel task. Se l'ID manca, non esiste o e' ambiguo, chiedi chiarimenti senza iniziare modifiche. Non inventare task o stati.\n\nRichiesta dell'utente:\n"
        + str(@payload.request),
    domain: "general"
);