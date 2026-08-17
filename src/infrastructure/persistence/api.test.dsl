imports: {
    'module': import("infrastructure.persistence.api")
};

any:adapter := imports.module.Adapter(
    provider:"jsonplaceholder",
    url:"https://jsonplaceholder.typicode.com"
);

session:session := {
    "id": "00000000-0000-0000-0000-000000000001";
    "providers": {};
    "user": {}
};

exports: {
    "adapter": adapter
};

tuple:test_suite := (
    {
        "action": adapter._url;
        "inputs": "/posts/1";
        "outputs": "https://jsonplaceholder.typicode.com/posts/1";
        "assert": @received == @expected;
        "note": "Adapter._url normalizza il percorso e costruisce l'URL della risorsa";
    },
    {
        "action": adapter._headers;
        "inputs": {"headers": {"X-Test": "api"}};
        "outputs": {"Accept": "application/json"; "Content-Type": "application/json"; "X-Test": "api"};
        "assert": @received == @expected;
        "note": "Adapter._headers combina gli header predefiniti con quelli della richiesta";
    },
    {
        "action": adapter.request;
        "inputs": {"method": "GET"; "location": "/posts/1"};
        "outputs": 1;
        "assert": @received.id == @expected;
        "note": "Adapter.request esegue una GET e restituisce il payload JSON";
    },
    {
        "action": adapter.create;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "jsonplaceholder"; "location": "/posts"; "operation": "create"; "repository": "posts"; "payload": {"title": "OmniPort"; "body": "test"; "userId": 1}}
        };
        "outputs": "OmniPort";
        "assert": @received.title == @expected;
        "note": "Adapter.create delega a POST e restituisce la risorsa creata";
    },
    {
        "action": adapter.read;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "jsonplaceholder"; "location": "/posts/1"; "operation": "read"; "repository": "posts"}
        };
        "outputs": 1;
        "assert": @received.id == @expected;
        "note": "Adapter.read delega a GET sulla risorsa richiesta";
    },
    {
        "action": adapter.update;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "jsonplaceholder"; "location": "/posts/1"; "operation": "update"; "repository": "posts"; "payload": {"id": 1; "title": "Aggiornato"; "body": "test"; "userId": 1}}
        };
        "outputs": "Aggiornato";
        "assert": @received.title == @expected;
        "note": "Adapter.update delega a PUT e restituisce il payload aggiornato";
    },
    {
        "action": adapter.delete;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "jsonplaceholder"; "location": "/posts/1"; "operation": "delete"; "repository": "posts"}
        };
        "outputs": {};
        "assert": @received == @expected;
        "note": "Adapter.delete delega a DELETE e accetta la risposta senza payload";
    },
    {
        "action": adapter.query;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "jsonplaceholder"; "location": "/posts/1"; "operation": "read"; "repository": "posts"}
        };
        "outputs": 1;
        "assert": @received.id == @expected;
        "note": "Adapter.query usa GET per interrogare una risorsa API";
    },
    {
        "action": adapter.view;
        "inputs": {
            "session": session;
            "storekeeper": {"provider": "jsonplaceholder"; "location": "/posts/1"; "operation": "view"; "repository": "posts"}
        };
        "outputs": 1;
        "assert": @received.id == @expected;
        "note": "Adapter.view usa GET per leggere la rappresentazione della risorsa"
    }
);