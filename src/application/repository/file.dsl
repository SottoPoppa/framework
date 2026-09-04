/* Definizione del Modello Repository (Dichiarativo) */
factory:repository := {
    location: {
        "WORKFOLDER": [
            "/tmp/{{filter.eq.filename}}",
            "/tmp"
        ];
        "SOURCE": [
            "{{filter.eq.filename}}",
            "src"
        ]
    };
    
    model: file;
    
    values: {
        //"tree": { "MODEL": build_tree_dict };
    };
    
    payloads: {
        //"view": view;
    };
    
    functions: {
        //"update": update_payload;
    };
};