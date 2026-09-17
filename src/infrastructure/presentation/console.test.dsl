imports: {
	'module': import("infrastructure.presentation.console")
};

exports: {
	'make_action': imports.module._make_action
};

tuple:test_suite := (
	{
		"action": exports.make_action;
		"inputs": {"attrs": {"id": "submit"; "value": ""}; "inner": ["Invia"]};
		"outputs": "";
		"assert": @received.is_success == true & @received.output.value._dsl_value == @expected;
		"note": "Un'azione conserva un valore vuoto esplicito senza sostituirlo con il testo visualizzato";
	}
);
