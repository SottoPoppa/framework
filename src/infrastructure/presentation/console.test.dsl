imports: {
	'module': import("infrastructure.presentation.console")
};

exports: {
	'make_action': imports.module._make_action;
	'format_flow_event': imports.module._format_flow_event
};

tuple:test_suite := (
	{
		"action": exports.make_action;
		"inputs": {"attrs": {"id": "submit"; "value": ""}; "inner": ["Invia"]};
		"outputs": "";
		"assert": @received.is_success == true & @received.output.value._dsl_value == @expected;
		"note": "Un'azione conserva un valore vuoto esplicito senza sostituirlo con il testo visualizzato";
	},
	{
		"action": exports.format_flow_event;
		"inputs": {"message": "request failed"; "level": "ERROR"; "metadata": {"node": "create_task"}};
		"outputs": "[bold red]ERROR[/bold] [bold]unknown[/bold] [dim]unknown[/dim]\n  [red]cause[/red]: request failed\n  [dim]details[/dim]\n  [yellow]node[/yellow]: 'create_task'";
		"assert": @received.is_success == true & @received.output.value == @expected;
		"note": "La console presenta gli errori Flow in formato espanso e leggibile";
	}
);
