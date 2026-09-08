imports: {
    'execution': import("framework.core.execution");
    'data': import("framework.core.data");
    'model': import("framework.core.model")
};

any:registry := imports.data.Registry({"add": imports.execution.operator.add});
any:executor := imports.execution.Executor(registry);
exports: {
    'execute': executor.execute
};

tuple:test_suite := (
    {
        "action": exports.execute;
        "inputs": (imports.model.Literal(2), {});
        "outputs": 2;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Executor.execute valuta un Literal"
    }
);