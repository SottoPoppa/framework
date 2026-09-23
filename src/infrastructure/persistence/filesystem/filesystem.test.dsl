imports: {
	'module': import("framework.adapter.persistence.filesystem")
};

exports: {
	'filter': imports.module.Adapter.filter;
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
);
