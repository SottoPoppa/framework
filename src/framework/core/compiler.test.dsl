imports: {
    'parser': import("framework.core.parser");
    'compiler': import("framework.core.compiler")
};

any:parser_instance := imports.parser.Parser();
any:compiler_instance := imports.compiler.Compiler();
any:source_program := parser_instance.parse("int:value := 10;");
exports: {
    'compile': compiler_instance.compile
};

tuple:test_suite := (
    {
        "action": exports.compile;
        "inputs": source_program;
        "outputs": "main";
        "assert": @received.is_success == true & @received.output.value.name == @expected & @received.output.value.context.value != none;
        "note": "Compiler.compile costruisce un DagDefinition dal programma DSL"
    }
);