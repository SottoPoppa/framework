// Test per il Manager del Tester
// Questo file verifica che la funzione import() funzioni correttamente

imports: {
    'tester_module': import("framework.manager.tester");
    'presentation_module': import("framework.port.presentation")
};

exports: {
    'resolve_filter': imports.tester_module.resolve_filter;
    'resolve_target_name': imports.tester_module.resolve_target_name;
    'is_integration_test_path': imports.tester_module.is_integration_test_path;
    'is_contract_test_path': imports.tester_module.is_contract_test_path;
    'port': imports.presentation_module.Port
};

// Test semplice: verify import() funziona
tuple:test_suite := (
    {
        "action": exports.resolve_filter;
        "inputs": "managers";
        "outputs": "src/framework/manager";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Test import() - resolve_filter con 'managers'";
    },
    {
        "action": exports.resolve_filter;
        "inputs": "ports";
        "outputs": "src/framework/port";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Test import() - resolve_filter con 'ports'";
    },
    {
        "action": exports.is_integration_test_path;
        "inputs": "src/application/controller/account.integration.test.dsl";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "riconosce un test di integrazione accanto al target";
    },
    {
        "action": exports.is_integration_test_path;
        "inputs": "src/application/controller/account.test.dsl";
        "outputs": false;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "non classifica un test di contract come integrazione";
    },
    {
        "action": exports.is_contract_test_path;
        "inputs": "src/application/controller/account.test.dsl";
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "riconosce un test di contract";
    },
    {
        "action": exports.resolve_target_name;
        "inputs": exports.resolve_filter;
        "outputs": "resolve_filter";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "resolve_target_name restituisce il nome stabile della funzione esportata";
    },
    {
        "action": exports.port.initialize;
        "inputs": imports.presentation_module.Port;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Un metodo di una classe esportata viene associato al relativo export oggetto";
    }
);



