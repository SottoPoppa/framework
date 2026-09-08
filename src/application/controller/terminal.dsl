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
        on_end: "gg"
    ) -> select_application;

    select_infrastructure(
        default: infrastructure_files.0,
        deps: ["infrastructure_files"],
        on_end: "gg"
    ) -> select_infrastructure;

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

    select_framework(
        default: framework_files.0,
        deps: ["framework_files"],
        on_end: "gg"
    ) -> select_framework;


    editor: {
        application(entry: false) ->
            storekeeper.gather(
                session,
                repository: "file",
                filter: {
                    "eq": {
                        "filename": select_application
                    }
                }
            );

        framework(entry: false) ->
            storekeeper.gather(
                session,
                repository: "file",
                filter: {
                    "eq": {
                        "filename": select_framework
                    }
                }
            );

        infrastructure(entry: false) ->
            storekeeper.gather(
                session,
                repository: "file",
                filter: {
                    "eq": {
                        "filename": select_infrastructure
                    }
                }
            )
    };

    gg(entry: false,
        //deps: ["editor.application", "editor.framework", "editor.infrastructure"]
    ) ->
        presenter.rebuild(session, "editors", {});

    cmd: {
        close(entry: false) ->
            exit(1)
    };
}