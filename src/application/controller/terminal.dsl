{
    selected: "src/infrastructure/presentation/console.py";

    select(
        deps:false,
        default:selected,
        entry:false,
        on_end:"gg"
    ) -> select;

    dependencies(entry:false) -> file_dependencies(select);

    files() ->
        storekeeper.overview(
            session,
            repository:"file",
            filter:{"eq":{"type":"file"}}
        ) |> result();

    application_files(entry:false) ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "application/")
        );

    framework_files(entry:false) ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "framework/")
        );

    infrastructure_files(entry:false) ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "infrastructure/")
        );

    editor:{
        application(entry:false) ->
            storekeeper.gather(
                session,
                repository:"file",
                filter:{"eq":{"filename":application_files.0.relative_path}}
            );

        framework(entry:false) ->
            storekeeper.gather(
                session,
                repository:"file",
                filter:{"eq":{"filename":framework_files.0.relative_path}}
            );

        infrastructure(entry:false) ->
            storekeeper.gather(
                session,
                repository:"file",
                filter:{"eq":{"filename":infrastructure_files.0.relative_path}}
            );
    };

    gg(
        deps:false,
        entry:false,
    ) -> presenter.rebuild(session, "editors", {});

    cmd:{
        close(
            deps:false,
            entry:false
        ) -> exit(1);
    };
}