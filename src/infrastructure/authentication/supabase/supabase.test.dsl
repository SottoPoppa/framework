imports: {
    'module': import("infrastructure.authentication.supabase")
};

any:schema := {
    "id": {"type": "string"};
    "email": {"type": "string"};
    "password": {"type": "string"}
};

any:adapter := imports.module.Adapter(
    url: "https://supabase.example.test",
    key: "test-anon-key",
    models: {"user": schema}
);

tuple:test_suite := (
    {
        "action": adapter._client;
        "inputs": ();
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value != none;
        "note": "Supabase crea un client isolato usando URL e chiave configurati";
    },
    {
        "action": adapter.sign_out;
        "inputs": {"args": [{}]};
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Supabase rifiuta il logout senza token di sessione";
    },
    {
        "action": adapter.get_user;
        "inputs": {"args": [{}]};
        "outputs": none;
        "assert": @received.is_success == false & @received.output.error != none;
        "note": "Supabase rifiuta la lettura utente senza sessione autenticata";
    },
    {
        "action": adapter.sign_aid;
        "inputs": {"type": "invalid"};
        "outputs": "Invalid type";
        "assert": @received.is_success == false & @received.output.error == @expected;
        "note": "Supabase rifiuta un tipo di verifica OTP sconosciuto"
    }
);
