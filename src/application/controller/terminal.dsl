{
    selected: "src/infrastructure/presentation/console.py";

    select(
        default: selected,
        entry: true,
        on_end: "gg"
    ) -> selected;

    dependencies(entry: false) -> file_dependencies(select);

    select_application(
        default: application_files.0,
        deps: ["application_files"],
        on_end: "update_app"
    ) -> select_application;

    select_infrastructure(
        default: infrastructure_files.0,
        deps: ["infrastructure_files"],
        on_end: "update_infra"
    ) -> select_infrastructure;

    select_framework(
        default: framework_files.0,
        deps: ["framework_files"],
        on_end: "update_frame"
    ) -> select_framework;

    files() ->
        storekeeper.overview(
            session,
            repository: "file",
            filter: {"eq": {"type": "file"}}
        ) |> result();

    application_files() ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "src/application/")
        );

    framework_files() ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "src/framework/")
        );

    infrastructure_files() ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "src/infrastructure/")
        );

    gg(entry: false,
        //deps: ["editor.application", "editor.framework", "editor.infrastructure"]
    ) ->
        presenter.rebuild(session, "workspace-editors", {});

    update_app(entry: false) ->
        presenter.rebuild(session, "application", {});

    update_frame(entry: false) ->
        presenter.rebuild(session, "framework", {});

    update_infra(entry: false) ->
        presenter.rebuild(session, "infrastructure", {});

    cmd: {
        close(entry: false) ->
            exit(1)
    };
}