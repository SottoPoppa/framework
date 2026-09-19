/* Definizione del Modello Repository (Dichiarativo) */
factory:repository := {
    location: {
        "WORKFOLDER": [
            "{% raw %}{{filter.eq.filename}}{% endraw %}",
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