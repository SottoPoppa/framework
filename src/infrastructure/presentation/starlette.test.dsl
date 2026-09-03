imports: {
    'module': import("infrastructure.presentation.starlette");
    'mock': import("unittest.mock");
    'types': import("types")
};

any:adapter := imports.module.Adapter(loader: none, defender: none, presenter: none, messenger: none, authenticator: none, storekeeper: none, manager: {"defender": {"key": "test-key"}});
any:unsupported_request := imports.module.Request({"type": "http"; "method": "PUT"; "path": "/"; "query_string": ""; "headers": []; "session": {}});
any:action_request := imports.types.SimpleNamespace(method: "GET", query_params: {"q": "dsl"}, session: {});
any:authenticate := imports.mock.AsyncMock(return_value: {"success": true; "outputs": {"user": "alice"}; "errors": []});
any:authenticator := imports.types.SimpleNamespace(authenticate: authenticate);
any:auth_adapter := imports.module.Adapter(loader: none, defender: none, presenter: none, messenger: none, authenticator: authenticator, storekeeper: none, manager: {"defender": {"key": "test-key"}});

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
        "inputs": {"args": (adapter.views)};
    'action': imports.module.Adapter.action;
    'mount_route': imports.module.Adapter.mount_route;
    'shutdown': imports.module.Adapter.shutdown;
    'validate_capabilities': imports.module.Adapter.validate_capabilities
};

tuple:html_cases := (
    {
        "id": "text-title";
        "action": exports.mount_tag;
        "inputs": (adapter, "text", {"id": "title"}, ["Hello"]);
        "note": "Il renderer produce esattamente l'HTML del tag text";
    },
    {
        "id": "div-content";
        "action": exports.node_create;
        "inputs": (adapter, imports.module.htpy.div, {}, ["Hello"]);
        "note": "Il renderer mantiene tag e contenuto nel markup HTML";
    },
    {
        "id": "action-link";
        "action": exports.mount_tag;
        "inputs": (adapter, "action", {"type": "link"; "href": "/target"}, ["Go"]);
        "note": "Action link produce un anchor con href e contenuto";
    },
    {
        "id": "text-plain";
        "action": exports.mount_tag;
        "inputs": (adapter, "text", {}, ["Content"]);
        "note": "Text senza attributi mantiene tag e contenuto";
    },
    {
        "id": "action-button";
        "action": exports.mount_tag;
        "inputs": (adapter, "action", {"type": "button"}, ["Click"]);
        "note": "Action button produce un elemento button";
    },
    {
        "id": "row-content";
        "action": exports.mount_tag;
        "inputs": (adapter, "row", {}, ["Content"]);
        "note": "Row produce un contenitore flex";
    }
);

dict:expected_html := {
    "text-title": '<span class="text-xs " id="title">Hello</span>';
    "div-content": "<div>Hello</div>";
    "action-link": '<a class="btn link " href="/target">Go</a>';
    "text-plain": '<span class="text-xs ">Content</span>';
    "action-button": '<button class="px-4 py-2 hover:opacity-80 transition-opacity ">Click</button>';
    "row-content": '<div class="flex-row  flex">Content</div>';
};

tuple:test_suite := (
    {
        "action": exports.validate_capabilities;
        "inputs": adapter;
        "outputs": true;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette espone un profilo presentation validabile dal Port"
    },
    {
        "action": exports.attrs;
        "inputs": ("container", {"attrs": {"class": "base"; "width": "full"; "id": "panel"}});
        "outputs": {"class": "base w-full"; "id": "panel"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette converte gli attributi di layout in classi Tailwind";
    },
    {
        "action": exports.attrs;
        "inputs": ("container", {"attrs": {"width": "1/2"; "height": "200px"; "padding": "8px,16px"; "margin": "4px"}});
        "outputs": {"class": " w-1/2 h-[200px] py-[8px] px-[16px] m-[4px]"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette applica dimensioni, padding composto e margin semplice";
    },
    {
        "action": exports.attrs;
        "inputs": ("row", {"attrs": {"justify": "between"; "align": "center"; "spacing": "12px"; "expand": "true"}});
        "outputs": {"class": " flex justify-between items-center gap-[12px] flex-1"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette aggiunge flex e converte allineamento, gap ed espansione";
    },
    {
        "action": exports.attrs;
        "inputs": ("container", {"attrs": {"overflow": "hidden"; "radius": "large"; "position": "relative"}});
        "outputs": {"class": " overflow-hidden rounded-lg relative"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette converte overflow, radius e position";
    },
    {
        "action": exports.attrs;
        "inputs": ("text", {"attrs": {"color": "#123456"; "align": "center"}});
        "outputs": {"class": " text-[#123456] text-center"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette converte colore e allineamento del testo";
    },
    {
        "action": exports.attrs;
        "inputs": ("text", {"attrs": {"color": "primary"; "spacing": "normal"; "height": "24px"; "uppercase": "true"; "truncate": "true"}});
        "outputs": {"class": " text-primary uppercase truncate tracking-normal leading-[24px]"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette applica i mapping tipografici con chiavi specializzate per text";
    },
    {
        "action": exports.attrs;
        "inputs": ("divider", {"attrs": {"color": "#123456"; "thickness": "2px"}});
        "outputs": {"class": " border-[2px] border-[#123456]"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette mantiene la semantica grafica del divider";
    },
    {
        "action": exports.attrs;
        "inputs": ("svg", {"attrs": {"width": "100"; "height": "40"; "viewBox": "0 0 100 40"}});
        "outputs": {"class": ""; "width": "100"; "height": "40"; "viewBox": "0 0 100 40"};
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette mantiene width e height come attributi SVG invece di convertirli in classi";
    },
    {
        "action": exports.node_create;
        "inputs": (adapter, imports.module.htpy.div, {}, ["Hello"]);
        "outputs": "<div>Hello</div>";
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette crea un nodo HTML con attributi e contenuto";
    },
    {
        "action": exports.mount_tag;
        "inputs": (adapter, "text", {"id": "title"}, ["Hello"]);
        "outputs": '<span class="text-xs " id="title">Hello</span>';
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette applica lo schema del tag e delega la creazione al renderer";
    },
    {
        "action": exports.http_exception_handler;
        "inputs": (adapter, none, imports.module.HTTPException(status_code: 418, detail: "teapot"));
        "outputs": 418;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "Starlette converte una HTTPException in una JSONResponse con lo status corretto";
    },
    {
        "action": exports.signout;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante il logout";
    },
    {
        "action": exports.signin;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante il login";
    },
    {
        "action": exports.signup;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante la registrazione";
    },
    {
        "action": exports.signaid;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "Starlette rifiuta i metodi HTTP non supportati durante il ripristino";
    },
    {
        "action": exports.action;
        "inputs": (adapter, unsupported_request);
        "outputs": 405;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "Starlette restituisce 405 per un metodo action non supportato";
    },
    {
        "action": exports.action;
        "inputs": (adapter, action_request);
        "outputs": 200;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "SimpleNamespace crea una request nativa con attributi sufficienti per action";
    },
    {
        "action": exports.signin;
        "inputs": (auth_adapter, action_request);
        "outputs": 303;
        "assert": @received.is_success == true & @received.output.value.status_code == @expected;
        "note": "AsyncMock e SimpleNamespace isolano il defender e verificano la mutazione della sessione";
    },
    {
        "action": exports.register_route;
        "inputs": (adapter, {"path": "/health"; "method": "GET"; "type": "action"});
        "outputs": "/health";
        "assert": @received.is_success == true & @received.output.value.0 == @expected;
        "note": "Starlette registra una route applicativa nell'indice del Port";
    },
    {
        "action": exports.mount_route;
        "inputs": (adapter, []);
        "outputs": none;
        "assert": @received.is_success == true;
        "note": "Starlette monta una route reale e aggiorna l'indice delle view";
    },
    {
        "action": exports.keys;
        "inputs": {"args": (adapter.views)};
        "outputs": ["/health"];
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette conserva la route montata nell'indice delle view";
    },
    {
        "action": exports.shutdown;
        "inputs": adapter;
        "outputs": none;
        "assert": @received.is_success == true & @received.output.value == @expected;
        "note": "Starlette chiude il lifecycle senza server attivo";
    },
    html_cases
    |> map_records(add_expected, expected_html)
    |> map_records(
        transform_record,
        updates: {"assert": @received.is_success == true & @received.output.value == @expected},
    ),
    imports.module.Adapter.tags
    |> tag_variants
    |> map_records(bind_input, adapter)
    |> map_records(
        transform_record,
        updates: {
            "action": exports.mount_tag;
            "assert": @received.is_success == true & @received.output.value != none;
        },
    )
);