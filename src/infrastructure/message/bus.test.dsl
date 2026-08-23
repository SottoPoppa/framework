imports: {
    'module': import("infrastructure.message.bus")
};

exports: {
    'post': imports.module.Adapter.post;
    'forget': imports.module.Adapter.forget;
};

tuple:test_suite := (
    {
        "action": exports.post;
        "inputs": (imports.module.Adapter(),);
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Message bus accetta un post senza reader registrati";
    },
    {
        "action": exports.forget;
        "inputs": (imports.module.Adapter(), {"id": "reader"});
        "outputs": none;
        "assert": @received.outputs == @expected;
        "note": "Message bus dimentica le code associate a una sessione";
    }
);