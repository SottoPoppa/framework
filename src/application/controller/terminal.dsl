{
    selected: "src/infrastructure/presentation/tui/textual.py";

    select(
        default: selected,
        entry: true,
        on_end: "refresh_workspace"
    ) -> selected;

    select_application(
        entry: false,
        on_end: "refresh_application"
    ) -> selected_application;

    select_framework(
        entry: false,
        on_end: "refresh_framework"
    ) -> selected_framework;

    select_infrastructure(
        entry: false,
        on_end: "refresh_infrastructure"
    ) -> selected_infrastructure;

    dependencies(
        deps: ["select"],
        entry: false
    ) -> file_dependencies(select);

    files() ->
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

    application_files(deps: ["dependencies"]) ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "src/application/")
        );

    framework_files(deps: ["dependencies"]) ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "src/framework/")
        );

    infrastructure_files(deps: ["dependencies"]) ->
        tuple_filter_tuple(
            dependencies,
            prefix_match("relative_path", "src/infrastructure/")
        );

    selected_is_framework(deps: ["select"]) ->
        selected.startswith("src/framework/");

    selected_is_infrastructure(deps: ["select"]) ->
        selected.startswith("src/infrastructure/");

    selected_is_other_scope(
        deps: ["selected_is_framework", "selected_is_infrastructure"]
    ) ->
        selected_is_framework or selected_is_infrastructure;

    selected_is_application(deps: ["selected_is_other_scope"]) ->
        not selected_is_other_scope;

    selected_scope(deps: [
        "selected_is_framework",
        "selected_is_infrastructure",
        "selected_is_application"
    ]) ->
        selected_is_framework * "framework"
        + selected_is_infrastructure * "infrastructure"
        + selected_is_application * "application";

    refresh_workspace(entry: false) ->
        presenter.rebuild(session, "workspace-editors", {});

    refresh_application(entry: false) ->
        presenter.rebuild(session, "application", {});

    refresh_framework(entry: false) ->
        presenter.rebuild(session, "framework", {});

    refresh_infrastructure(entry: false) ->
        presenter.rebuild(session, "infrastructure", {});

    cmd: {
        close(entry: false) ->
            exit(1)
    };
}