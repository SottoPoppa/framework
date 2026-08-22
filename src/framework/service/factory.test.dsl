imports: {
    'factory': import("framework.service.factory");
};

any:repository := imports.factory.Repository(
    location: {"GITHUB": ["repos/{{ owner }}/{{ name }}"]},
    model: "file"
);

any:mapped_repository := imports.factory.Repository(
    model: "file",
    mapper: {
        "path": {"github": "repo_path"};
        "name": {"github": "repo_name"}
    }
);

exports: {
    'get_requirements': repository.get_requirements;
    'select': repository.select;
    'parameters': repository.parameters;
    'results': repository.results;
    'mapped_results': mapped_repository.results;
};

any:file_data := {
    "path": "/tmp/readme.txt";
    "name": "readme";
    "extension": "txt"
};

any:mapped_file_data := {
    "repo_path": "/tmp/mapped.txt";
    "repo_name": "mapped";
    "extension": "txt"
};

tuple:test_suite := (
    {
        "action": exports.get_requirements;
        "inputs": "";
        "outputs": [];
        "assert": @received == @expected;
        "note": "get_requirements gestisce un template vuoto";
    },
    {
        "action": exports.get_requirements;
        "inputs": "repos/{{ owner }}/{{ name }}";
        "outputs": ["name", "owner"];
        "assert": @received == @expected;
        "note": "get_requirements estrae tutte le variabili del template";
    },
    {
        "action": exports.select;
        "inputs": (["static/path"], {});
        "outputs": "static/path";
        "assert": @received == @expected;
        "note": "select sceglie un template statico senza requisiti";
    },
    {
        "action": exports.parameters;
        "inputs": {
            "provider": "github";
            "operation": "read";
            "owner": "octo";
            "name": "repo"
        };
        "outputs": "repos/octo/repo";
        "assert": @received.location == @expected & @received.provider == "github";
        "note": "parameters seleziona e formatta il template del provider";
    },
    {
        "action": exports.results;
        "inputs": [file_data, "GITHUB"];
        "outputs": {
            "path": "/tmp/readme.txt";
            "name": "readme";
            "extension": "txt";
            "mime_type": "application/octet-stream";
            "size": 0;
            "encoding": "utf-8";
            "content": "";
            "metadata": {};
            "permissions": "";
            "owner": "";
            "created_at": none;
            "modified_at": none;
            "accessed_at": none
        };
        "assert": @received == @expected;
        "note": "results normalizza la risposta secondo lo schema file e applica i default";
    },
    {
        "action": exports.results;
        "inputs": [{}, "WORKFOLDER"];
        "outputs": none;
        "assert": @received == @expected;
        "note": "results tratta una risposta vuota di delete come esito senza payload";
    },
    {
        "action": exports.mapped_results;
        "inputs": [mapped_file_data, "github"];
        "outputs": {
            "path": "/tmp/mapped.txt";
            "name": "mapped";
            "extension": "txt";
            "mime_type": "application/octet-stream";
            "size": 0;
            "encoding": "utf-8";
            "content": "";
            "metadata": {};
            "permissions": "";
            "owner": "";
            "created_at": none;
            "modified_at": none;
            "accessed_at": none
        };
        "assert": @received == @expected;
        "note": "results mappa le chiavi del provider verso il modello canonico";
    }
);