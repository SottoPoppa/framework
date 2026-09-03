// Integration test: Networker -> network stub

exports: {
    "provision": test.managers.networker.provision;
    "route": test.managers.networker.route;
    "compute": test.managers.networker.compute;
    "monitor": test.managers.networker.monitor;
    "status": test.managers.networker.status
};

session:session := test.session;

any:intent := {
    "requirements": {"platform": "stub"};
    "service": "integration"
};
any:application := {"name": "integration-app"};
any:requirements := {"platform": "stub"};

tuple:test_suite := (
    {
        "action": exports.provision;
        "inputs": {"args": [session, intent]};
        "outputs": {"provider": "stub"};
        "assert": @received.output.value.provider == @expected.provider;
        "note": "provision usa il network stub selezionato per capability"
    },
    {
        "action": exports.route;
        "inputs": {"args": [session, application, requirements]};
        "outputs": {"provider": "stub"};
        "assert": @received.output.value.provider == @expected.provider;
        "note": "route delega la scelta al network stub"
    },
    {
        "action": exports.compute;
        "inputs": {"args": [session]};
        "outputs": none;
        "assert": @received.output.value != none;
        "note": "compute raccoglie il risultato del network stub"
    },
    {
        "action": exports.monitor;
        "inputs": {"args": [session]};
        "outputs": {"networks": none};
        "assert": @received.output.value.networks != none;
        "note": "monitor espone lo stato del network stub"
    },
    {
        "action": exports.status;
        "inputs": {"args": [session]};
        "outputs": none;
        "assert": @received.output.value.stub != none;
        "note": "status indicizza il risultato del network stub"
    }
);
