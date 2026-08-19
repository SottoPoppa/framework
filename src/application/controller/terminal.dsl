{
    selected: "src/infrastructure/presentation/console.py";
    select(deps:false,default:selected,entry:false) -> select;
    //dependencies: loader.file_dependencies(selected);
    dependencies: [];
    
    //files: storekeeper.overview(sid, repository: "file",filter: {"startswith":{"relative_path": "/src"};"eq": {"type": "file"}});
    files: {};


    editor: {
        application:storekeeper.gather(sid, repository: "file",filter: {"eq": {"filename": get(dependencies,"0")}});
        framework:storekeeper.gather(sid, repository: "file",filter: {"eq": {"filename": get(dependencies,"1")}});
        infrastructure:storekeeper.gather(sid, repository: "file",filter: {"eq": {"filename": get(dependencies,"2")}});
    };

    gg(deps:false,entry:false) -> presenter.rebuild("editor-application",sid,{});


    //close(deps:false) -> exit();
    submit(deps:false) -> messenger.send(sid, domain: "console:info", message: submit);
    //stampa() -> [storekeeper.overview(sid, repository: "file",filter: {"type": {"eq": "file"}}),exit(1)];
    stampa(deps:false) -> messenger.send(sid, domain: "console:info", message:   dire);
    new(deps:false) -> presenter.rebuild("editor-application",sid);
    cmd:{
        //new(deps:false) -> presenter.rebuild("editor-application",sid);
        close(deps:false, entry:false) -> exit(1);
        //close(deps:false) -> messenger.send(sid, domain: "console:error", message: "ciao");
    };
}