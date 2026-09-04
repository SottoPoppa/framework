{
    selected: "src/infrastructure/presentation/console.py";
    select(deps:false,default:selected,entry:false) -> select;
    dependencies: [selected];
    files:storekeeper.overview(session, repository: "file", filter: {"eq": {"type": "file"}});


    editor: {
        application:storekeeper.gather(session, repository: "file",filter: {"eq": {"filename": selected}});
        framework:storekeeper.gather(session, repository: "file",filter: {"eq": {"filename": selected}});
        infrastructure:storekeeper.gather(session, repository: "file",filter: {"eq": {"filename": selected}});
    };

    gg(deps:false,entry:false) -> presenter.rebuild("editors",session,{});
    stampa(deps:false) -> messenger.send(session, domain: "console:info", message: select);

    cmd:{
        close(deps:false, entry:false) -> exit(1);
    };
}