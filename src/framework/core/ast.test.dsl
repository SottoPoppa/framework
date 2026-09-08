imports: {
    'ast': import("framework.core.ast")
};

exports: {
    'node_meta': imports.ast.NodeMeta;
    'string_literal': imports.ast.StringLiteral
};

tuple:test_suite := (
    {
        "action": exports.node_meta;
        "inputs": (1, 2, 3, 4);
        "outputs": 1;
        "assert": @received.is_success == true & @received.output.value.line == @expected & @received.output.value.end_column == 4;
        "note": "NodeMeta conserva le posizioni del nodo AST";
    },
    {
        "action": exports.string_literal;
        "inputs": "ciao";
        "outputs": "ciao";
        "assert": @received.is_success == true & @received.output.value.value == @expected;
        "note": "StringLiteral costruisce un nodo con il valore testuale";
    }
);