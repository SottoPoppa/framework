imports: {
    'parser': import("framework.core.parser")
};

any:parser_instance := imports.parser.Parser();
exports: {
    'parse': parser_instance.parse;
    'parse_result': parser_instance.parse_result
};

tuple:test_suite := (
    {
        "action": exports.parse;
        "inputs": "int:value := 10;";
        "outputs": 1;
        "assert": @received.is_success == true & @received.output.value.statements != none;
        "note": "Parser.parse produce un programma per una dichiarazione valida";
    },
    {
        "action": exports.parse;
        "inputs": "value: reset(10) |> result();";
        "outputs": 1;
        "assert": @received.is_success == true & @received.output.value.statements != none;
        "note": "Parser.parse riconosce pipe e chiamate DSL"
    },
    {
        "action": exports.parse_result;
        "inputs": "editor.application(entry: false) -> result();";
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value.error != none;
        "note": "Parser.parse_result restituisce un errore per task con trigger qualificato fuori da un blocco"
    }
);