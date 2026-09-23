imports: {
	'module': import("infrastructure.presentation.tui.textual")
};

any:adapter := imports.module.Adapter(none, none, none, none, imports.module.LogBuffer());

exports: {
	'adapter': adapter
};

tuple:test_suite := (
	{
		"action": exports.adapter.mount_css;
		"inputs": "Screen { background: $surface; }";
		"outputs": none;
		"assert": @received.is_success == true;
		"note": "Textual accetta un foglio di stile vuoto senza avviare il runtime";
	}
);
