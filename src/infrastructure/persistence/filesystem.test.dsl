imports: {
	'module': import("infrastructure.persistence.filesystem")
};

exports: {
	'filter': imports.module.Adapter.filter;
	'resolve_path': imports.module.Adapter._resolve_path;
	'payload_data': imports.module.Adapter._payload_data
};

tuple:test_suite := (
	{
		"action": exports.filter;
		"inputs": {"args": (imports.module.Adapter, ({"name": "README.md"; "type": "file"}, {"name": "src"; "type": "directory"})); "kwargs": {"filter": {"eq": {"type": "file"}}}};
		"outputs": none;
		"assert": @received.is_success == true & @received.output.value != none;
		"note": "Adapter.filter seleziona gli elementi file dal dataset";
	},
	{
		"action": exports.filter;
		"inputs": {"args": (imports.module.Adapter, ({"relative_path": "src/application"; "type": "directory"}, {"relative_path": "README.md"; "type": "file"})); "kwargs": {"filter": {"startswith": {"relative_path": "src/"}}}};
		"outputs": none;
		"assert": @received.is_success == true & @received.output.value != none;
		"note": "Adapter.filter normalizza lo slash e applica startswith sui percorsi";
	},
	{
		"action": exports.resolve_path;
		"inputs": {"location": "/tmp/integration.txt"; "filter": {"eq": {"filename": "ignored.txt"}}};
		"outputs": "/tmp/integration.txt";
		"assert": @received.is_success == true & @received.output.value == @expected;
		"note": "Adapter usa il percorso prodotto dal Repository quando disponibile";
	},
	{
		"action": exports.payload_data;
		"inputs": {"payload": {"content": "hello"}};
		"outputs": "hello";
		"assert": @received.is_success == true & @received.output.value == @expected;
		"note": "Adapter estrae il contenuto dal payload del Repository";
	}
);
