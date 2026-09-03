imports: {
    'scheme': import("framework.core.scheme");
    'template': import("framework.service.template");
};

exports: {
    "get": imports.scheme.get;
    "format": imports.template.format;
    "convert": imports.scheme.convert;
    "put": imports.scheme.put;
    "normalize": imports.scheme.normalize;
};

data: {
    "nome": "Progetto A";
    "config": {"timeout": 30;};
    "versioni": [{"id": 1; "status": "completo";}, {"id": 2; "status": "fallito";}];
};

type:schema := {
    "name": {"type": "string"; "required": true;};
    "age": {"type": "number"; "required": true;};
};

tuple:test_suite := (
    {
        "action": exports.get;
        "inputs": (data, "config.timeout");
        "outputs": 30;
        "assert": @received.output.value == @expected;
        "note": "get legge un valore annidato tramite dot path";
    },
    {
        "action": exports.get;
        "inputs": (data, "versioni.*[status=fallito].id");
        "outputs": [2];
        "assert": @received.output.value == @expected;
        "note": "get filtra una lista con una wildcard condizionale";
    },
    {
        "action": exports.format;
        "inputs": {"target": "Ciao {{nome}}"; "nome": "Progetto A";};
        "outputs": "Ciao Progetto A";
        "assert": @received.output.value == @expected;
        "note": "format sostituisce le variabili Jinja";
    },
    {
        "action": exports.convert;
        "inputs": ("10", int);
        "outputs": 10;
        "assert": @received.output.value == @expected;
        "note": "convert converte una stringa in intero";
    },
    {
        "action": exports.put;
        "inputs": (data, "config.timeout", 60);
        "outputs": {"nome": "Progetto A"; "config": {"timeout": 60;}; "versioni": [{"id": 1; "status": "completo";}, {"id": 2; "status": "fallito";}];};
        "assert": @received.output.value == @expected;
        "note": "put restituisce una copia aggiornata";
    },
    {
        "action": exports.normalize;
        "inputs": ({"name": "Mario"; "age": 30;}, schema);
        "outputs": {"name": "Mario"; "age": 30;};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "normalize valida e restituisce i dati normalizzati";
    }
);