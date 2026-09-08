{
    selected: "src/infrastructure/presentation/console.py";

    select(
        default: selected,
        entry: true,
        on_end: "gg"
    ) -> selected;

    dependencies(entry: false) -> file_dependencies(select);

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

    editor: {
        application(entry: false) ->
            storekeeper.gather(
                session,
                repository: "file",
                filter: {
                    "eq": {
                        "filename": application_files.0
                    }
                }
            );

        framework(entry: false) ->
            storekeeper.gather(
                session,
                repository: "file",
                filter: {
                    "eq": {
                        "filename": framework_files.0
                    }
                }
            );

        infrastructure(entry: false) ->
            storekeeper.gather(
                session,
                repository: "file",
                filter: {
                    "eq": {
                        "filename": infrastructure_files.0
                    }
                }
            )
    };

    gg(entry: false,
        deps: ["editor.application", "editor.framework", "editor.infrastructure"]
    ) ->
        presenter.rebuild(session, "editors", {});

    cmd: {
        close(entry: false) ->
            exit(1)
    };
}