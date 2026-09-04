{
    selected: "src/infrastructure/presentation/console.py";
    select(deps:false,default:selected,entry:false) -> select;
    dependencies:file_dependencies(selected);

    files:storekeeper.overview(session, repository: "file", filter: {"eq": {"type": "file"}}) |> result();
    
    application_files:dependencies |> tuple_filter_tuple(prefix_match("relative_path", "src/application/"));
    framework_files:dependencies |> tuple_filter_tuple(prefix_match("relative_path", "src/framework/"));
    infrastructure_files:dependencies |> tuple_filter_tuple(prefix_match("relative_path", "src/infrastructure/"));


    editor: {
        application:storekeeper.gather(session, repository: "file",filter: {"eq": {"filename": application_files.0}});
        framework:storekeeper.gather(session, repository: "file",filter: {"eq": {"filename": framework_files.0}});
        infrastructure:storekeeper.gather(session, repository: "file",filter: {"eq": {"filename": infrastructure_files.0}});
    };

    gg(deps:false,entry:false) -> presenter.rebuild("editors",session,{});
    
    stampa(deps:false) -> messenger.send(session, domain: "console:info", message: select);

    cmd:{
        close(deps:false, entry:false) -> exit(1);
    };
}