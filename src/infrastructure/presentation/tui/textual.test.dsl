imports: {
	'module': import("infrastructure.presentation.tui.textual")
};

any:adapter := imports.module.Adapter(none, none, none, none, imports.module.LogBuffer());
any:palette_node := imports.module.dom.parse('<Navigation id="palette" type="palette"><Action route="/ide"><Text>Open IDE</Text></Action><Action type="button" route="/ide" click="terminal:select" value="src/app.py"><Text>Open source file</Text></Action></Navigation>');

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
	},
	{
		"action": exports.adapter.render_node;
		"inputs": {"args": (none, palette_node, {})};
		"outputs": none;
		"assert": @received != none;
		"note": "Il renderer Textual costruisce la sorgente della palette dai comandi XML";
	}
);
