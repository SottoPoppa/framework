imports: {
    'scope': import("framework.core.scope")
};

any:root := imports.scope.Scope({"user": {"name": "Ada"}; "items": ["zero", "one"]});
any:nested := root.child({"theme": "dark"});

exports: {
    'get': root.get;
    'set': root.set;
    'exists': root.exists;
    'delete': root.delete;
    'lookup': nested.lookup;
    'flatten': nested.flatten
};

tuple:test_suite := (
    {
        "action": exports.get;
        "inputs": ("user.name",);
        "outputs": "Ada";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Scope.get risolve un percorso annidato"
    },
    {
        "action": exports.get;
        "inputs": ("user.surname", "assente");
        "outputs": "assente";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Scope.get restituisce il default per un percorso assente"
    },
    {
        "action": exports.set;
        "inputs": ("user.role", "admin");
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Scope.set crea e aggiorna percorsi annidati"
    },
    {
        "action": exports.exists;
        "inputs": ("user.role",);
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Scope.exists riconosce una chiave presente"
    },
    {
        "action": exports.lookup;
        "inputs": ("user.name",);
        "outputs": "Ada";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Scope figlio risolve i binding del padre lungo la catena"
    },
    {
        "action": exports.flatten;
        "inputs": ();
        "outputs": "dark";
        "assert": @received.is_success == true & @received.output.value.theme == @expected;
        "note": "Scope.flatten unisce la catena coprendo i livelli esterni"
    },
    {
        "action": exports.delete;
        "inputs": ("user.role",);
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Scope.delete rimuove una chiave del livello corrente"
    },
    {
        "action": exports.delete;
        "inputs": ("user.role",);
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Scope.delete segnala una chiave assente senza sollevare errori"
    }
);
