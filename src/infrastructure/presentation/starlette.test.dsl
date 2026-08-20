imports: {
    'module': import("infrastructure.presentation.starlette");
    'mock': import("unittest.mock");
    'types': import("types")
};

any:adapter := imports.module.Adapter(loader: none, defender: none, presenter: none, messenger: none, project: {"key": "test-key"});
any:unsupported_request := imports.module.Request({"type": "http"; "method": "PUT"; "path": "/"; "query_string": ""; "headers": []; "session": {}});
any:action_request := imports.types.SimpleNamespace(method: "GET", query_params: {"q": "dsl"}, session: {});
any:authenticate := imports.mock.AsyncMock(return_value: {"success": true; "outputs": {"user": "alice"}; "errors": []});
any:auth_defender := imports.types.SimpleNamespace(authenticate: authenticate);
any:auth_adapter := imports.module.Adapter(loader: none, defender: auth_defender, presenter: none, messenger: none, project: {"key": "test-key"});

exports: {
    'attrs': imports.module.attrs;
    'node_create': imports.module.Adapter.node_create;
    'mount_tag': imports.module.Adapter.mount_tag;
    'http_exception_handler': imports.module.Adapter.http_exception_handler;
    'register_route': imports.module.Adapter.register_route;
    'keys': keys;
    'signout': imports.module.Adapter.signout;
    'signin': imports.module.Adapter.signin;
    'signup': imports.module.Adapter.signup;
    'signaid': imports.module.Adapter.signaid;
    'action': imports.module.Adapter.action;
    'mount_route': imports.module.Adapter.mount_route;
    'shutdown': imports.module.Adapter.shutdown;
};

tuple:test_suite := (
    {
        "action": exports.attrs;
        "inputs": ("container", {"attrs": {"class": "base"; "width": "full"; "id": "panel"}});
        "outputs": {"class": "base w-full"; "id": "panel"};
        "assert": @received == @expected;
        "note": "Starlette converte gli attributi di layout in classi Tailwind";
    },
    {
        "action": exports.attrs;
        "inputs": ("container", {"attrs": {"width": "1/2"; "height": "200px"; "padding": "8px,16px"; "margin": "4px"}});
        "outputs": {"class": " w-1/2 h-[200px] py-[8px] px-[16px] m-[4px]"};
        "assert": @received == @expected;
        "note": "Starlette applica dimensioni, padding composto e margin semplice";
    },
    {
        "action": exports.attrs;
        "inputs": ("row", {"attrs": {"justify": "between"; "align": "center"; "spacing": "12px"; "expand": "true"}});
        "outputs": {"class": " flex justify-between items-center gap-[12px] flex-1"};
        "assert": @received == @expected;
        "note": "Starlette aggiunge flex e converte allineamento, gap ed espansione";
    },
    {
        "action": exports.attrs;
        "inputs": ("container", {"attrs": {"overflow": "hidden"; "radius": "large"; "position": "relative"}});
        "outputs": {"class": " overflow-hidden rounded-lg relative"};
        "assert": @received == @expected;
        "note": "Starlette converte overflow, radius e position";
    },
    {
        "action": exports.attrs;
        "inputs": ("text", {"attrs": {"color": "#123456"; "align": "center"}});
        "outputs": {"class": " text-[#123456] text-center"};
        "assert": @received == @expected;
        "note": "Starlette converte colore e allineamento del testo";
    },
    {
        "action": exports.attrs;
        "inputs": ("text", {"attrs": {"color": "primary"; "spacing": "normal"; "height": "24px"; "uppercase": "true"; "truncate": "true"}});
        "outputs": {"class": " text-primary uppercase truncate tracking-normal leading-[24px]"};
        "assert": @received == @expected;
        "note": "Starlette applica i mapping tipografici con chiavi specializzate per text";
    },
    {
        "action": exports.attrs;
        "inputs": ("divider", {"attrs": {"color": "#123456"; "thickness": "2px"}});
        "outputs": {"class": " border-[2px] border-[#123456]"};
        "assert": @received == @expected;
        "note": "Starlette mantiene la semantica grafica del divider";
    },
    {
        "action": exports.attrs;
        "inputs": ("svg", {"attrs": {"width": "100"; "height": "40"; "viewBox": "0 0 100 40"}});
        "outputs": {"class": ""; "width": "100"; "height": "40"; "viewBox": "0 0 100 40"};
        "assert": @received == @expected;
        "note": "Starlette mantiene width e height come attributi SVG invece di convertirli in classi";
    },
    {
        "action": exports.node_create;
        "inputs": (adapter, imports.module.htpy.div, {}, ["Hello"]);
        "outputs": "<div>Hello</div>";
        "assert": @received == @expected;
        "note": "Starlette crea un nodo HTML con attributi e contenuto";
    },
    {
        "action": exports.mount_tag;
        "inputs": (adapter, "text", {"id": "title"}, ["Hello"]);
        "outputs": '<span class="text-xs " id="title">Hello</span>';
        "assert": @received == @expected;
        "note": "Starlette applica lo schema del tag e delega la creazione al renderer";
    },
    {
        "action": exports.http_exception_handler;
        "inputs": (adapter, none, imports.module.HTTPException(status_code: 418, detail: "teapot"));
        "outputs": 418;
        "assert": @received.status_code == @expected;
        "note": "Starlette converte una HTTPException in una JSONResponse con lo status corretto";
    },
    {
        "action": exports.signout;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante il logout";
    },
    {
        "action": exports.signin;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante il login";
    },
    {
        "action": exports.signup;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante la registrazione";
    },
    {
        "action": exports.signaid;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante il ripristino";
    },
    {
        "action": exports.action;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.status_code == @expected;
        "note": "Starlette restituisce 405 per un metodo action non supportato";
    },
    {
        "action": exports.action;
        "inputs": (adapter, action_request);
        "outputs": 200;
        "assert": @received.status_code == @expected;
        "note": "SimpleNamespace crea una request nativa con attributi sufficienti per action";
    },
    {
        "action": exports.signin;
        "inputs": (auth_adapter, action_request);
        "outputs": 303;
        "assert": @received.status_code == @expected;
        "note": "AsyncMock e SimpleNamespace isolano il defender e verificano la mutazione della sessione";
    },
    {
        "action": exports.register_route;
        "inputs": (adapter, {"path": "/health"; "method": "GET"; "type": "action"});
        "outputs": "/health";
        "assert": @received.0 == @expected;
        "note": "Starlette registra una route applicativa nell'indice del Port";
    },
    {
        "action": exports.mount_route;
        "inputs": (adapter, []);
        "outputs": none;
        "assert": @received == @expected;
        "note": "Starlette monta una route reale e aggiorna l'indice delle view";
    },
    {
        "action": exports.keys;
        "inputs": {"args": (adapter.views)};
        "outputs": ["/health"];
        "assert": @received == @expected;
        "note": "Starlette conserva la route montata nell'indice delle view";
    },
    {
        "action": exports.shutdown;
        "inputs": adapter;
        "outputs": none;
        "assert": @received == @expected;
        "note": "Starlette chiude il lifecycle senza server attivo";
    }
);