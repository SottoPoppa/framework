// Repository usato dagli integration test del filesystem.
// L'adapter restituisce il contenuto raw, quindi non applichiamo uno schema.
factory:repository := {
    location: {
        "WORKFOLDER": [
            "/tmp/{{filter.eq.filename}}"
        ]
    };
};
