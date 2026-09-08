/* Definizione del Modello Repository (Dichiarativo) */
factory:repository := {
    location: {
        "WORKFOLDER": [
            "{{filter.eq.filename}}",
            "/"
        ];
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