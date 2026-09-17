/* Controller dichiarativo per la board Kanban SCRUM. */

/* Crea un task nel backlog. La policy gestisce l'autorizzazione. */
create_task(entry: false, on_end: "refresh_board") -> storekeeper.store(
    session,
    repository: "task",
    payload: {
        "id": format("task-{0}", random(100000, 999999));
        "title": @payload.title;
        "description": @payload.description;
        "status": "backlog";
        "priority": @payload.priority;
        "created_at": "2026-09-12T00:00:00Z";
        "updated_at": none;
        "completed_at": none;
        }
);

refresh_board(entry: false, deps: false) -> presenter.rebuild(
    session,
    "kanban-board",
    {}
);

/* Transizioni di stato della board. */
move_to_todo(entry: false) -> storekeeper.change(
    session,
    repository: "task",
    filter: {id: @payload.task_id},
    payload: {status: "todo"}
);

move_to_inprogress(entry: false) -> storekeeper.change(
    session,
    repository: "task",
    filter: {id: @payload.task_id},
    payload: union(
        {status: "in_progress"},
        {assigned_to: @session.user_id}
    )
);

move_to_review(entry: false) -> storekeeper.change(
    session,
    repository: "task",
    filter: {id: @payload.task_id},
    payload: {status: "review"}
);

approve_task(entry: false) -> storekeeper.change(
    session,
    repository: "task",
    filter: {id: @payload.task_id},
    payload: {status: "done"}
);

reject_task(entry: false) -> storekeeper.change(
    session,
    repository: "task",
    filter: {"id": @payload.task_id},
    payload: {status: "todo"}
);

/* Carica tutti i task per la board. */
load_board(entry: true) -> storekeeper.gather(
    session,
    repository: "task"
);