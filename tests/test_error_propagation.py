import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from jinja2 import Environment

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import framework.core.flow as flow
from framework.core.application import Application
from framework.core.data import Registry
from framework.core.evaluation import EvaluationError, Evaluator
from framework.core.framework import Framework
from framework.core.interpreter import Interpreter
from framework.core.model import Call, DagDefinition, Deferred, Literal, Ref
from framework.core.parser import Parser
from framework.core.session import NodeState, Session, SessionData
from framework.core.scope import Scope
from framework.manager.authenticator import Manager as Authenticator
from framework.manager.defender import Manager as Defender
from framework.manager.loader import Loader
from framework.manager.messenger import Manager as Messenger
from framework.manager.orchestrator import Manager as Orchestrator
from framework.manager.presenter import Manager as Presenter
from framework.manager.storekeeper import Manager as Storekeeper
from framework.manager.tester import Manager as Tester
from framework.service.factory import Repository
from framework.service.route import resolve_route
import framework.service.dom as dom_service
import framework.service.template as template_service
from framework.core.infrastructure import Infrastructure
from infrastructure.persistence.filesystem.filesystem import (
    Adapter as FilesystemAdapter,
    FileWatcherHandler,
)
from infrastructure.presentation.adapter import Adapter as PresentationAdapter
from infrastructure.presentation.web import starlette as starlette_web
from infrastructure.presentation.tui.widgets import (
    OptionValue,
    _make_action,
    _make_tabbed_content,
)
from infrastructure.presentation.tui.widgets import attrs as textual_attrs
from infrastructure.presentation.tui.textual import (
    Adapter as TextualAdapter,
    AppDinamica,
)
from framework.port.presentation import Port as PresentationPort
from textual.geometry import Spacing
from textual.app import ComposeResult
from textual.widgets import Select, Static


class ErrorPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_filesystem_query_excludes_requested_directories(self):
        with tempfile.TemporaryDirectory() as root:
            included = Path(root, "src", "application", "app.dsl")
            excluded_venv = Path(root, "venv", "lib", "package.py")
            excluded_git = Path(root, ".git", "config")
            for file_path in (included, excluded_venv, excluded_git):
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("data", encoding="utf-8")

            adapter = FilesystemAdapter(messenger=None, path=root)
            result = await adapter.query(
                filter={"eq": {"type": "file"}},
                exclude_dirs=("venv", ".git"),
            )

        self.assertTrue(flow.check(result))
        records = flow.output(result)
        self.assertEqual(
            [record["relative_path"] for record in records],
            ["src/application/app.dsl"],
        )

    def test_textual_padding_and_margin_are_numeric_spacing(self):
        rendered = textual_attrs(
            Static(), {"padding": "1", "margin": "0,1"}
        )

        self.assertEqual(rendered.styles.padding, Spacing(1, 1, 1, 1))
        self.assertEqual(rendered.styles.margin, Spacing(0, 1, 0, 1))
        self.assertEqual(
            rendered.styles.padding + rendered.styles.border.spacing,
            Spacing(1, 1, 1, 1),
        )

    def test_textual_tabbed_content_uses_configured_initial_value(self):
        rendered = _make_tabbed_content(
            {
                "attrs": {"id": "workspace-editors", "value": "infrastructure"},
                "inner": [
                    OptionValue("Infrastructure", "infrastructure", content=[Static()])
                ],
            }
        )

        self.assertEqual(rendered._initial, "infrastructure")

    async def test_textual_select_ignores_initial_change_but_dispatches_user_change(self):
        messenger = types.SimpleNamespace(send=AsyncMock())
        adapter = types.SimpleNamespace(
            messenger=messenger,
            session=object(),
            logger=Mock(),
            log_buffer=object(),
            render_view=AsyncMock(return_value=flow.success(None)),
            node_get=Mock(
                return_value=dom_service.parse(
                    '<Input id="select" value="initial.py" change="terminal:select"/>'
                )
            ),
        )

        class ProbeApp(AppDinamica):
            def compose(self) -> ComposeResult:
                yield Select(
                    [("initial.py", "initial.py"), ("next.py", "next.py")],
                    value="initial.py",
                    id="select",
                )

        app = ProbeApp(adapter)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(messenger.send.await_count, 0)

            app.query_one("#select", Select).value = "next.py"
            await pilot.pause()
            self.assertEqual(messenger.send.await_count, 1)

    async def test_textual_click_syncs_matching_select_after_success(self):
        messenger = types.SimpleNamespace(
            send=AsyncMock(return_value=flow.success(None))
        )
        adapter = types.SimpleNamespace(
            messenger=messenger,
            session=object(),
            logger=Mock(),
            log_buffer=object(),
            render_view=AsyncMock(return_value=flow.success(None)),
            node_get=Mock(
                return_value=dom_service.parse(
                    '<Input id="select" value="initial.py" change="terminal:select"/>'
                )
            ),
        )
        app = AppDinamica(adapter)
        source = types.SimpleNamespace(
            _dsl_click="terminal:select",
            _dsl_value="next.py",
            parent=None,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            select = Select(
                [("Initial", "initial.py"), ("Next", "next.py")],
                value="initial.py",
                id="select",
            )
            await app.screen.mount(select)
            await pilot.pause()

            await app.on_click(types.SimpleNamespace(widget=source))
            await pilot.pause()

            self.assertEqual(select.value, "next.py")
            messenger.send.assert_awaited_once_with(
                adapter.session,
                adapter="dsl",
                receiver="terminal",
                domain="select",
                message="next.py",
            )

    async def test_textual_storekeeper_cache_reuses_unchanged_files(self):
        with tempfile.TemporaryDirectory() as root:
            filename = Path(root, "editor.py")
            filename.write_text("first", encoding="utf-8")
            requests = []

            async def gather(_session, **request):
                requests.append(request)
                return flow.success({"content": filename.read_text(encoding="utf-8")})

            provider = types.SimpleNamespace(
                config={"name": "workfolder"}, path=root
            )
            storekeeper = types.SimpleNamespace(
                gather=AsyncMock(side_effect=gather),
                maked={},
                persistences=[provider],
            )
            adapter = object.__new__(TextualAdapter)
            adapter._storekeeper_file_cache = OrderedDict()
            adapter.loader = types.SimpleNamespace(
                get_managers=Mock(return_value={"storekeeper": storekeeper})
            )
            request = {
                "repository": "file",
                "filter": {"eq": {"filename": filename.name}},
            }

            first = await adapter._load_storekeeper(None, request)
            repeated = await adapter._load_storekeeper(None, request)
            filename.write_text("updated content", encoding="utf-8")
            updated = await adapter._load_storekeeper(None, request)

        self.assertEqual(first["content"], "first")
        self.assertEqual(repeated, first)
        self.assertEqual(updated["content"], "updated content")
        self.assertEqual(len(requests), 2)

    async def test_terminal_file_options_are_skipped_during_fragment_refresh(self):
        source = Path("src/application/view/page/terminal.xml").read_text(
            encoding="utf-8"
        )
        environment = Environment(
            extensions=(template_service.AsyncBlockExtension,), enable_async=True
        )
        environment.filters["check"] = lambda result: result["ok"]
        environment.filters["value"] = lambda result: result["value"]
        template = environment.from_string(source)
        terminal = types.SimpleNamespace(
            files={"ok": True, "value": [{"relative_path": "src/cache_probe.py"}]},
            select="src/infrastructure/presentation/tui/textual.py",
            select_application="",
            select_framework="",
            select_infrastructure="",
            application_files=[],
            framework_files=[],
            infrastructure_files=[],
        )
        chat = types.SimpleNamespace(
            copilot_source=types.SimpleNamespace(message="")
        )
        context = {"terminal": terminal, "chat": chat}

        initial = await template.render_async(context)
        refreshed = await template.render_async(
            context | {"_fragment_refresh": True}
        )

        self.assertIn('<Option value="src/cache_probe.py"/>', initial)
        self.assertNotIn('<Option value="src/cache_probe.py"/>', refreshed)
        self.assertNotRegex(initial, r'value="\{\{\s*\}\}"')
        self.assertNotRegex(refreshed, r'value="\{\{\s*\}\}"')
        self.assertRegex(
            initial,
            r'<Group id="workspace-editors" type="tab"[^>]*value="infrastructure"',
        )

    async def test_template_render_uses_explicit_context_without_running_controllers(self):
        runtime_session = types.SimpleNamespace(
            run=AsyncMock(side_effect=AssertionError("controller was re-executed")),
        )

        async def render_node(parent, node, context, runtime_session=None):
            return dom_service.serialize(node)

        rendered = await template_service.render(
            Infrastructure(),
            {},
            runtime_session,
            render_node,
            text=(
                "<Window><Text>{{ terminal.selected }}</Text>"
                "<Text>{{ chat.message }}</Text></Window>"
            ),
            controller_context={
                "terminal": {"selected": "widgets.py"},
                "chat": {"message": ""},
            },
        )

        self.assertIn("widgets.py", rendered)
        runtime_session.run.assert_not_awaited()

    async def test_route_controller_execution_is_explicit(self):
        managers = {"presenter": object()}
        runtime_session = types.SimpleNamespace(
            run=AsyncMock(
                side_effect=[
                    flow.success({"selected": "widgets.py"}),
                    flow.success({"message": ""}),
                ]
            )
        )
        adapter = object.__new__(starlette_web.Adapter)
        adapter.loader = types.SimpleNamespace(
            get_managers=Mock(return_value=managers)
        )

        controller_context = await adapter.execute_controllers(
            runtime_session,
            ("terminal", "chat"),
        )

        self.assertEqual(
            controller_context,
            {
                "terminal": {"selected": "widgets.py"},
                "chat": {"message": ""},
            },
        )
        self.assertEqual(runtime_session.run.await_count, 2)
        self.assertEqual(
            [call.args[0] for call in runtime_session.run.await_args_list],
            ["terminal", "chat"],
        )
        self.assertIs(
            runtime_session.run.await_args_list[0].args[1]["manager"],
            managers,
        )

    async def test_textual_replaces_tabbed_content_instead_of_reconciling_it(self):
        adapter = TextualAdapter(None, None, None, None, None)
        current = _make_tabbed_content({
            "attrs": {"id": "workspace-editors", "value": "application"},
            "inner": [
                OptionValue(
                    "application",
                    "application",
                    content=[Static("primo")],
                )
            ],
        })
        rendered = _make_tabbed_content({
            "attrs": {"id": "workspace-editors", "value": "infrastructure"},
            "inner": [
                OptionValue(
                    "infrastructure",
                    "infrastructure",
                    content=[Static("secondo")],
                )
            ],
        })

        self.assertFalse(
            await adapter._update_widget_in_place(
                current,
                rendered,
                {"id": "workspace-editors"},
            )
        )

    async def test_dsl_resource_defers_templates_and_expands_policy_includes(self):
        infrastructure = Infrastructure()

        repository = infrastructure.resource(
            "src/application/repository/integration_file.dsl"
        )
        session_path = "src/application/repository/sessions.dsl"
        sessions = infrastructure.resource(session_path)
        presentation = infrastructure.resource(
            "src/application/policy/presentation/presentation.dsl"
        )

        self.assertRegex(repository, r"\{\{\s*filter\.eq\.filename\s*\}\}")
        self.assertRegex(sessions, r"\{\{\s*session\.id\s*\}\}")
        self.assertIn("route:GET_INDEX", presentation)

        interpreter = Interpreter()
        await interpreter.load_file(session_path, sessions)
        runtime_session = interpreter.open_session()
        async with runtime_session:
            result = await runtime_session.run(session_path)
            repository_data = flow.output(result)["repository"]
        session_repository = Repository(**repository_data)
        parameters = await session_repository.parameters(
            provider="workfolder",
            operation="read",
            session={"id": "session-test"},
        )
        self.assertEqual(
            parameters["location"], "/tmp/sessions/session-test.json"
        )

    async def test_storekeeper_block_loads_only_when_branch_renders(self):
        requests = []
        payload = "<img src=x onerror=alert(1)>"

        async def gather(runtime_session, **request):
            requests.append(request)
            return flow.success([{"title": payload}])

        source = (
            '<Window type="page">{% if enabled %}'
            '{% storekeeper(repository="task", filter={"eq":{"status":"backlog"}}) as tasks %}'
            '<Text>{{ tasks[0].title }}</Text>'
            "{% endstorekeeper %}{% endif %}</Window>"
        )
        storekeeper = types.SimpleNamespace(
            gather=AsyncMock(side_effect=gather)
        )
        adapter = object.__new__(starlette_web.Adapter)
        adapter.loader = types.SimpleNamespace(
            infrastructure=Infrastructure(),
            get_managers=Mock(return_value={"storekeeper": storekeeper}),
        )

        inactive = await adapter.render_template(None, text=source, enabled=False)
        self.assertEqual(requests, [])
        storekeeper.gather.assert_not_awaited()

        active = await adapter.render_template(None, text=source, enabled=True)
        self.assertEqual(
            requests,
            [{"repository": "task", "filter": {"eq": {"status": "backlog"}}}],
        )
        html = str(active)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)

    def test_starlette_escapes_plain_text_and_preserves_rendered_markup(self):
        payload = "<img src=x onerror=alert(1)>"
        rendered_text = starlette_web.Adapter.node_create(
            None, starlette_web.htpy.span, {}, [payload]
        )
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", str(rendered_text))
        self.assertNotIn("<img src=x", str(rendered_text))

        rendered_parent = starlette_web.Adapter.node_create(
            None, starlette_web.htpy.div, {}, [rendered_text]
        )
        self.assertIn(str(rendered_text), str(rendered_parent))

    def test_starlette_rejects_scriptable_url_schemes(self):
        rejected = (
            ("action", "href", "javascript:alert(1)"),
            ("action", "href", "java\nscript:alert(1)"),
            ("media", "src", "data:text/html,<script>alert(1)</script>"),
        )
        for tag, name, value in rejected:
            with self.subTest(tag=tag, name=name, value=value):
                rendered = starlette_web.attrs(
                    tag, {"attrs": {name: value, "id": "safe-id"}}
                )
                self.assertNotIn(name, rendered)
                self.assertEqual(rendered["id"], "safe-id")

        for value in ("/tasks", "https://example.test/tasks", "mailto:a@example.test"):
            with self.subTest(value=value):
                rendered = starlette_web.attrs(
                    "action", {"attrs": {"href": value}}
                )
                self.assertEqual(rendered["href"], value)

    async def test_storekeeper_template_loader_returns_read_data_only(self):
        runtime_session = object()
        rows = [{"id": "task-1"}]
        storekeeper = types.SimpleNamespace(
            gather=AsyncMock(return_value=flow.success(rows))
        )
        adapter = object.__new__(starlette_web.Adapter)
        adapter.loader = types.SimpleNamespace(
            get_managers=Mock(return_value={"storekeeper": storekeeper})
        )

        result = await adapter._load_storekeeper(
            runtime_session, {"repository": "task"}
        )

        self.assertEqual(result, tuple(rows))
        storekeeper.gather.assert_awaited_once_with(
            runtime_session, repository="task"
        )
        with self.assertRaisesRegex(
            ValueError, "Operazione Storekeeper non supportata"
        ):
            await adapter._load_storekeeper(
                runtime_session,
                {"operation": "change", "repository": "task"},
            )

    async def test_messenger_jinja_block_loads_message_data(self):
        message = {"message": "A new notification", "domain": "info"}
        messenger = types.SimpleNamespace(
            receive=AsyncMock(return_value=flow.success(message))
        )
        adapter = object.__new__(starlette_web.Adapter)
        adapter.messenger = None
        adapter.loader = types.SimpleNamespace(
            infrastructure=Infrastructure(),
            get_managers=Mock(return_value={"messenger": messenger}),
        )
        source = (
            '<Window type="page">{% if enabled %}'
            '{% messenger(domain="info") as notice %}'
            '{% if notice %}<Text>{{ notice.message }}</Text>{% endif %}'
            '{% endmessenger %}'
            '{% endif %}</Window>'
        )

        inactive = await adapter.render_template(
            None, text=source, enabled=False
        )
        self.assertNotIn("A new notification", str(inactive))
        messenger.receive.assert_not_awaited()

        rendered = await adapter.render_template(
            None, text=source, enabled=True
        )

        self.assertIn("A new notification", str(rendered))
        messenger.receive.assert_awaited_once_with(None, domain="info")
        with self.assertRaisesRegex(ValueError, "solo operazioni di ricezione"):
            await adapter._load_messenger(
                None, {"operation": "send", "message": "not from a view"}
            )

    async def test_layout_renders_messenger_jinja_block(self):
        messenger = types.SimpleNamespace(
            receive=AsyncMock(
                return_value=flow.success(
                    {"message": "A new notification", "title": "Inbox"}
                )
            )
        )
        adapter = object.__new__(starlette_web.Adapter)
        adapter.messenger = None
        adapter.loader = types.SimpleNamespace(
            infrastructure=Infrastructure(),
            get_managers=Mock(return_value={"messenger": messenger}),
        )

        async def render_dom(_parent, node, _context, runtime_session=None):
            return dom_service.serialize(node)

        original_get_jinja = template_service.get_jinja

        def get_jinja_with_route(infrastructure=None, **options):
            environment = original_get_jinja(infrastructure, **options)
            environment.filters.setdefault(
                "route", lambda value, *args, **kwargs: value
            )
            return environment

        async def load_messenger(request):
            return await adapter._load_messenger(None, request)

        with patch.object(
            template_service, "get_jinja", side_effect=get_jinja_with_route
        ):
            rendered = await template_service.render(
                adapter.loader.infrastructure,
                {},
                None,
                render_dom,
                file="src/application/view/layout/page.xml",
                async_block_loaders={"messenger": load_messenger},
                url=types.SimpleNamespace(
                    path=["dashboard"], query={}
                ),
            )

        self.assertIn("A new notification", rendered)
        self.assertNotIn("<Messenger", rendered)
        messenger.receive.assert_awaited_once_with(None)

    async def test_terminal_template_skips_missing_companion_files(self):
        source_file = "src/framework/core/flow.py"
        available_files = flow.success([{"relative_path": source_file}])
        terminal = {
            "files": available_files,
            "select": source_file,
            "application_files": (),
            "framework_files": (source_file,),
            "infrastructure_files": (),
            "select_application": "",
            "select_framework": source_file,
            "select_infrastructure": "",
        }
        requests = []

        async def load_storekeeper(request):
            filename = request["filter"]["eq"]["filename"]
            requests.append(filename)
            return {"content": f"contents of {filename}"}

        async def render_dom(_parent, node, _context, runtime_session=None):
            return dom_service.serialize(node)

        original_get_jinja = template_service.get_jinja

        def get_jinja_with_filters(infrastructure=None, **options):
            environment = original_get_jinja(infrastructure, **options)
            environment.filters.setdefault("check", flow.check)
            environment.filters.setdefault("value", flow.output)
            return environment

        with patch.object(
            template_service, "get_jinja", side_effect=get_jinja_with_filters
        ):
            rendered = await template_service.render(
                Infrastructure(),
                {},
                None,
                render_dom,
                file="src/application/view/page/terminal.xml",
                async_block_loaders={"storekeeper": load_storekeeper},
                terminal=terminal,
                chat={"copilot_source": {"message": ""}},
            )

        self.assertEqual(requests, [source_file])
        self.assertIn(f"contents of {source_file}", rendered)

    async def test_messenger_xml_tag_uses_standard_unknown_tag_error(self):
        messenger = types.SimpleNamespace(receive=AsyncMock())
        adapter = object.__new__(starlette_web.Adapter)
        adapter.DOM = {}
        adapter.messenger = None
        adapter.loader = types.SimpleNamespace(
            infrastructure=Infrastructure(),
            get_managers=Mock(return_value={"messenger": messenger}),
        )
        source = '<Window type="page"><Messenger><Text>legacy</Text></Messenger></Window>'

        with self.assertRaisesRegex(Exception, "Tag messenger non trovato"):
            await adapter.render_template(None, text=source)

        messenger.receive.assert_not_awaited()

    async def test_storekeeper_xml_tag_uses_standard_unknown_tag_error(self):
        storekeeper = types.SimpleNamespace(gather=AsyncMock())
        adapter = object.__new__(starlette_web.Adapter)
        adapter.DOM = {}
        adapter.loader = types.SimpleNamespace(
            infrastructure=Infrastructure(),
            get_managers=Mock(return_value={"storekeeper": storekeeper}),
        )
        source = (
            '<Window type="page"><Storekeeper id="items" '
            'repository="task"><Text>legacy</Text></Storekeeper></Window>'
        )

        with self.assertRaisesRegex(Exception, "Tag storekeeper non trovato"):
            await adapter.render_template(None, text=source)

        storekeeper.gather.assert_not_awaited()

    def test_framework_install_reads_config_via_infrastructure_resource(self):
        framework = Framework()
        infrastructure = Infrastructure()

        context = framework._read_install_config(
            {"config_file": "pyproject.toml"}, infrastructure
        )

        self.assertEqual(context["config"]["project"]["name"], "cloud.colosso")

    def test_framework_install_uses_adapter_implementation_path(self):
        framework = Framework()
        context = {
            "config": {
                "presentation": {
                    "web": {"implementation": "starlette"},
                },
            },
            "enabled_adapters": [("presentation", "web")],
        }

        install_context = framework._install_sources(context, {}, {}, {})

        self.assertIn(
            (
                "adapter",
                "presentation.web",
                "src/infrastructure/presentation/web/starlette.py",
            ),
            install_context["sources"],
        )

    async def test_starlette_start_awaits_uvicorn_server(self):
        adapter = object.__new__(starlette_web.Adapter)
        adapter.defender = types.SimpleNamespace(
            get_configuration=lambda _name: {
                "security_and_waf": {"tls_enabled": False}
            }
        )
        adapter.config = {"host": "127.0.0.1", "port": 8000}
        adapter.routes_static = []
        adapter.middleware_static = []
        adapter.parse_route = AsyncMock()
        adapter.mount_route = AsyncMock()
        server_config = types.SimpleNamespace(load=Mock(), ssl=None)
        server = types.SimpleNamespace(serve=AsyncMock(return_value=None))

        with (
            patch.object(starlette_web, "Config", return_value=server_config),
            patch.object(starlette_web, "Server", return_value=server),
        ):
            received = await adapter.start(object())

        self.assertTrue(received.is_success)
        try:
            server.serve.assert_awaited_once()
        finally:
            if not server.serve.await_count:
                pending = flow.output(received)
                if hasattr(pending, "close"):
                    pending.close()

    def test_websocket_origin_requires_same_origin_or_explicit_allowlist(self):
        websocket = types.SimpleNamespace(
            url="wss://app.example.test/reactive",
            headers={"origin": "https://app.example.test"},
        )

        self.assertTrue(
            starlette_web.Adapter._websocket_origin_allowed(websocket)
        )
        websocket.headers["origin"] = "https://attacker.example"
        self.assertFalse(
            starlette_web.Adapter._websocket_origin_allowed(websocket)
        )
        self.assertTrue(
            starlette_web.Adapter._websocket_origin_allowed(
                websocket, ["https://attacker.example"]
            )
        )
        websocket.headers.clear()
        self.assertFalse(
            starlette_web.Adapter._websocket_origin_allowed(websocket)
        )
        websocket.headers["origin"] = "https://app.example.test"
        websocket.url = "wss://[invalid/reactive"
        self.assertFalse(
            starlette_web.Adapter._websocket_origin_allowed(websocket)
        )

    async def test_reactive_websocket_rejects_untrusted_origin_before_accept(self):
        adapter = object.__new__(starlette_web.Adapter)
        adapter.config = {}
        websocket = types.SimpleNamespace(
            url="wss://app.example.test/reactive",
            headers={"origin": "https://attacker.example"},
            accept=AsyncMock(),
            close=AsyncMock(),
        )

        await adapter.render_reactive(websocket)

        websocket.accept.assert_not_awaited()
        websocket.close.assert_awaited_once_with(
            code=1008, reason="Origin not allowed"
        )

    async def test_starlette_rejects_http_when_tls_is_not_configured(self):
        defender = types.SimpleNamespace(get_configuration=lambda name: {})
        middleware = starlette_web.DefenderMiddleware(AsyncMock(), defender, [])
        request = types.SimpleNamespace(url=types.SimpleNamespace(scheme="http"))

        response = await middleware.dispatch(request, AsyncMock())

        self.assertEqual(response.status_code, 400)

    async def test_starlette_requires_csrf_and_returns_token_by_default(self):
        defender = types.SimpleNamespace(
            get_configuration=lambda name: {},
            authorized=AsyncMock(return_value=True),
        )
        middleware = starlette_web.DefenderMiddleware(AsyncMock(), defender, [])
        metadata = {"path": "/mutate", "view": "mutate"}
        request = types.SimpleNamespace(
            url=types.SimpleNamespace(scheme="https", path="/mutate"),
            session={"id": "session", "csrf_token": "expected-token"},
            client=types.SimpleNamespace(host="127.0.0.1"),
            method="POST",
            headers={"x-csrf-token": "wrong-token"},
            state=types.SimpleNamespace(),
        )
        resolve_route = "infrastructure.presentation.web.starlette.route.resolve_route"
        with patch(resolve_route, return_value={"metadata": metadata}):
            rejected = await middleware.dispatch(request, AsyncMock())
        self.assertEqual(rejected.status_code, 403)

        request.headers["x-csrf-token"] = "expected-token"
        with patch(resolve_route, return_value={"metadata": metadata}):
            accepted = await middleware.dispatch(
                request, AsyncMock(return_value=starlette_web.HTMLResponse("ok"))
            )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.headers["X-CSRF-Token"], "expected-token")
        self.assertIn("Strict-Transport-Security", accepted.headers)

    async def test_oauth_boolean_parser_accepts_textual_flags(self):
        if importlib.util.find_spec("aiohttp") is None:
            self.skipTest("OAuth2 adapter e opzionale")

        from infrastructure.authentication.oauth2.oauth import Adapter as OAuthAdapter

        self.assertTrue(OAuthAdapter._bool("true"))
        self.assertFalse(OAuthAdapter._bool("false"))

    async def test_oauth_get_headers_rejects_expired_token_after_failed_refresh(self):
        if importlib.util.find_spec("aiohttp") is None:
            self.skipTest("OAuth2 adapter e opzionale")

        from infrastructure.authentication.oauth2.oauth import Adapter as OAuthAdapter

        adapter = OAuthAdapter(
            provider="provider",
            token_url="https://auth.example.test/token",
            authorization_endpoint="https://auth.example.test/authorize",
            redirect_uri="https://app.example.test/callback",
            client_id="client",
            client_secret="secret",
            grant_type="password",
            auth_style="body",
        )
        session = {"providers": {"provider": {"tokens": {
            "access_token": "expired-access-token",
            "refresh_token": "refresh-token",
            "expires_at": 1,
        }}}}
        refresh = AsyncMock(return_value=flow.error("refresh rejected"))

        with patch.object(adapter, "refresh", new=refresh):
            with self.assertRaisesRegex(RuntimeError, "OAuth token refresh failed"):
                await adapter.get_headers(session)

        refresh.assert_awaited_once_with(
            refresh_token="refresh-token",
            session=session,
        )

    async def test_supabase_adapter_creates_client_from_configuration(self):
        if importlib.util.find_spec("supabase") is None:
            self.skipTest("supabase e un adapter opzionale")

        from infrastructure.authentication.supabase import supabase as supabase_adapter

        adapter = supabase_adapter.Adapter(
            url="https://supabase.example.test",
            key="test-anon-key",
            models={"user": {"id": {"type": "string"}}},
        )
        client = object()
        with patch.object(supabase_adapter.supabase, "create_client", return_value=client) as create_client:
            result = adapter._client()

        self.assertIs(result, client)
        create_client.assert_called_once_with(
            "https://supabase.example.test",
            "test-anon-key",
        )

    async def test_evaluator_requires_explicit_session_data_argument(self):
        session_data = SessionData({
            "id": "session-data",
            "context": {},
            "authentication": {},
            "results": {},
        })
        def get_default_session(session):
            return session

        evaluator = Evaluator(Registry({"get_default_session": get_default_session}))

        received_session_data = await evaluator.evaluate(
            Call("get_default_session", (Literal(session_data),)), Scope()
        )
        self.assertIs(received_session_data, session_data)
        with self.assertRaises(EvaluationError):
            await evaluator.evaluate(Call("get_default_session"), Scope())

    async def test_session_data_is_immutable_and_rejects_runtime_values(self):
        session_data = SessionData({
            "id": "session-data",
            "context": {"locale": "it"},
            "authentication": {"providers": {}},
            "results": {"chat": {"reply": "ciao"}},
        })

        self.assertIsInstance(session_data, dict)
        self.assertEqual(session_data["results"]["chat"]["reply"], "ciao")
        with self.assertRaises(TypeError):
            session_data["id"] = "changed"
        with self.assertRaises(TypeError):
            session_data["context"]["locale"] = "en"
        with self.assertRaises(TypeError):
            session_data["context"].update({"locale": "en"})
        with self.assertRaises(TypeError):
            session_data["authentication"].setdefault("user", {})
        with self.assertRaises(TypeError):
            SessionData({
                "id": "invalid-runtime",
                "context": {"handle": object()},
                "authentication": {},
                "results": {},
            })

    async def test_runner_adopts_returned_session_data_snapshot(self):
        original = SessionData({
            "id": "session-transition",
            "context": {},
            "authentication": {},
            "results": {},
        })
        updated = original.evolve(authentication={"user": {"id": "user-1"}})
        interpreter = Interpreter()
        handle = interpreter.open_session(
            sid=original["id"],
            state=original,
        )
        execution = Session(
            "authentication",
            "authentication-execution",
            Scope({"session": original}),
            runtime_session=handle,
        )
        handle._executions["authentication"] = execution

        interpreter.runner._publish(execution, "authenticate", updated)

        self.assertEqual(
            handle.session_data["authentication"]["user"]["id"],
            "user-1",
        )
        self.assertIs(execution.context.get("session"), handle.session_data)
        self.assertEqual(
            handle.session_data.get_result("authentication", "authenticate"),
            updated.to_dict(),
        )

    async def test_messenger_uses_explicit_session_data_to_find_runtime(self):
        session_data = SessionData({
            "id": "messenger-user",
            "context": {},
            "authentication": {},
            "results": {},
        })
        runtime = types.SimpleNamespace(
            dispatch_controller_event=AsyncMock(return_value={"delivered": True})
        )
        defender = types.SimpleNamespace(
            controllers=["kanban"],
            authorized=AsyncMock(return_value=True),
            session_get=unittest.mock.Mock(return_value=runtime),
        )
        messenger = Messenger([], defender, None)
        evaluator = Evaluator(Registry({"send": messenger.send}))

        result = await evaluator.evaluate(
            Call(
                "send",
                (Literal(session_data),),
                keywords={
                    "adapter": "dsl",
                    "receiver": "kanban",
                    "domain": "refresh_board",
                    "message": {"task": "42"},
                },
            ),
            Scope(),
        )

        self.assertTrue(flow.is_result(result))
        self.assertTrue(flow.check(result))
        self.assertEqual(flow.output(result), {"delivered": True})
        defender.session_get.assert_called_once_with(session_data)
        runtime.dispatch_controller_event.assert_awaited_once_with(
            "kanban",
            "refresh_board",
            {"task": "42"},
        )

    async def test_session_handle_starts_controller_before_dispatching_event(self):
        runtime = Interpreter().open_session(sid="dispatch-user")
        execution = Session(
            "kanban",
            "kanban-execution",
            runtime_session=runtime,
        )

        async def start_controller(controller):
            runtime._executions[controller] = execution
            return flow.success({})

        with patch.object(
            runtime,
            "run",
            new_callable=AsyncMock,
            side_effect=start_controller,
        ) as run_controller, patch.object(
            runtime.runner,
            "emit",
            new_callable=AsyncMock,
            return_value={"emitted": True},
        ) as emit:
            result = await runtime.dispatch_controller_event(
                "kanban", "refresh_board", None
            )

        self.assertEqual(result, {"emitted": True})
        run_controller.assert_awaited_once_with("kanban")
        emit.assert_awaited_once_with(execution, "refresh_board", None)

    async def test_orchestrator_builds_runtime_handle_from_session_data(self):
        session_data = SessionData({
            "id": "orchestrator-user",
            "context": {},
            "authentication": {"user": {"id": "user-1"}},
            "results": {},
        })
        manager = Orchestrator(None)

        runtime = manager._runtime_session(session_data)

        self.assertEqual(runtime.sid, session_data["id"])
        self.assertEqual(runtime.session_data["authentication"]["user"]["id"], "user-1")

    async def test_orchestrator_first_completed_cancels_pending_loser(self):
        manager = Orchestrator(None)
        cancelled = asyncio.Event()

        async def pending():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        result = await manager.first_completed(
            None,
            operations=[asyncio.sleep(0, result="winner"), pending()],
        )

        self.assertTrue(result.is_success)
        self.assertEqual(flow.output(result), "winner")
        self.assertTrue(cancelled.is_set())

    async def test_orchestrator_first_completed_propagates_normalization_error(self):
        manager = Orchestrator(None)

        async def reject_payload(transaction, profile=None):
            return flow.error("invalid payload")

        result = await manager.first_completed(
            None,
            operations=[asyncio.sleep(0, result={"invalid": True})],
            success=reject_payload,
        )

        self.assertFalse(result.is_success)
        self.assertIn("invalid payload", str(flow.output(result)))

    async def test_orchestrator_all_completed_propagates_failed_flow_result(self):
        manager = Orchestrator(None)

        async def fail():
            return flow.error("task failed")

        result = await manager.all_completed(None, tasks=[fail()])

        self.assertFalse(result.is_success)
        self.assertIn("task failed", str(flow.output(result)))

    async def test_orchestrator_chain_completed_propagates_task_exception(self):
        manager = Orchestrator(None)

        async def raise_error(**constants):
            raise ValueError("step raised")

        result = await manager.chain_completed(None, tasks=[raise_error])

        self.assertFalse(result.is_success)
        self.assertIn("step raised", str(flow.output(result)))

    async def test_chat_dependencies_read_published_terminal_select_result(self):
        source_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "application"
            / "controller"
            / "chat.dsl"
        )
        interpreter = Interpreter()
        interpreter.registry.register("file_dependencies", lambda path: path)
        program = interpreter.load("chat-test", source_path.read_text(encoding="utf-8"))
        dependency_node = next(
            node for node in program.definition.nodes if node.name == "dependencies"
        )
        session_data = SessionData({
            "id": "chat-test",
            "context": {},
            "authentication": {},
            "results": {
                "terminal": {
                    "select": "src/infrastructure/presentation/console.py"
                }
            },
        })

        received = await interpreter.evaluate(
            dependency_node.action.expression,
            {"session": session_data},
        )

        self.assertEqual(
            received,
            "src/infrastructure/presentation/console.py",
        )

    async def test_parser_decodes_escaped_string_literals(self):
        program = Parser().parse(r'value: "line\n say \"quoted\"";')
        parsed_value = program.statements[0].items[0].value.value

        self.assertEqual(parsed_value, 'line\n say "quoted"')

    async def test_encefalo_initializes_available_module_vocabulary(self):
        from infrastructure.network.neural.encefalo import Encefalo

        encefalo = Encefalo()

        self.assertEqual(
            encefalo.moduli["Modulo 6: Memoria (Episodica)"][0][0],
            (600, "Remoto"),
        )
        self.assertEqual(
            encefalo.moduli["Modulo 8: Attentivo (Focus)"][0][0],
            (800, "Rilevante"),
        )
        self.assertEqual(
            encefalo.moduli["Modulo 9: Meta-Cognitivo (Talamo)"][0][0],
            (900, "Attivo"),
        )

    async def test_api_adapter_reads_tokens_from_session_data(self):
        from infrastructure.persistence.api.api import Adapter as ApiAdapter

        session_data = SessionData({
            "id": "api-user",
            "context": {},
            "authentication": {
                "providers": {
                    "github": {"tokens": {"access_token": "test-token"}}
                }
            },
            "results": {},
        })

        tokens = ApiAdapter._session_tokens(
            types.SimpleNamespace(name="github"), session_data
        )

        self.assertEqual(tokens["access_token"], "test-token")

    def test_defender_session_get_accepts_session_data(self):
        interpreter = Interpreter()
        original = interpreter.open_session(sid="defender-user")
        defender = Defender.__new__(Defender)
        defender.interpreter = interpreter

        recovered = defender.session_get(original.session_data)

        self.assertEqual(recovered.session_data.to_dict(), original.session_data.to_dict())

    async def test_textual_action_preserves_explicit_empty_value(self):
        action = _make_action({
            "attrs": {"id": "submit", "value": ""},
            "inner": ["Invia"],
        })

        self.assertEqual(action._dsl_value, "")
        self.assertTrue(action._dsl_has_value)

    async def test_framework_package_keeps_real_submodule_search_path(self):
        package_name = f"_framework_test_package_{id(self)}"
        with tempfile.TemporaryDirectory() as package_root:
            package_directory = Path(package_root) / package_name
            package_directory.mkdir()
            (package_directory / "__init__.py").write_text("", encoding="utf-8")
            (package_directory / "child.py").write_text(
                'VALUE = "loaded"\n',
                encoding="utf-8",
            )
            sys.path.insert(0, package_root)
            importlib.invalidate_caches()
            try:
                Framework()._pkg(package_name)
                child = importlib.import_module(f"{package_name}.child")
                self.assertEqual(child.VALUE, "loaded")
            finally:
                sys.path.remove(package_root)
                sys.modules.pop(f"{package_name}.child", None)
                sys.modules.pop(package_name, None)

    async def test_unwrap_preserves_non_exception_failure_payload(self):
        async def unwrap_result(value):
            return flow.unwrap(value)

        received = await flow.result()(unwrap_result)(flow.error("bad input"))

        self.assertFalse(received.is_success)
        self.assertIsInstance(received.output.error, flow.FlowError)
        self.assertEqual(received.output.error.value, "bad input")

    async def test_tester_rejects_unresolved_or_failed_assertions(self):
        with self.assertRaisesRegex(AssertionError, "non risolto"):
            Tester._assertion_value(
                flow.success(Deferred(None, ("received.missing",)))
            )

        with self.assertRaisesRegex(AssertionError, "non riuscito"):
            Tester._assertion_value(flow.error("assert evaluation failed"))

        with self.assertRaisesRegex(TypeError, "deve restituire bool"):
            Tester._assertion_value(flow.success("truthy"))

        self.assertTrue(Tester._assertion_value(flow.success(True)))

    async def test_scope_resolves_properties_on_dict_subclasses(self):
        received = flow.success({"rebuilt": True})

        self.assertTrue(received.is_success)
        self.assertTrue(Scope({"received": received}).lookup("received.is_success"))
        self.assertTrue(Scope({"received": received}).lookup("received.output.is_success"))

    async def test_evaluator_reads_nested_values_from_immutable_results(self):
        definition = DagDefinition.from_nodes(
            "main",
            (),
            context={"value": Literal(10)},
        )
        received = flow.success(definition)
        scope = Scope({"received": received})
        evaluator = Evaluator()

        name = await evaluator.evaluate(Ref("received.output.value.name"), scope)
        value = await evaluator.evaluate(
            Ref("received.output.value.context.value"),
            scope,
        )

        self.assertEqual(name, "main")
        self.assertEqual(value, 10)
        self.assertIs(received.output.value, definition)

    async def test_dsl_logical_operators_short_circuit_deferred_operands(self):
        interpreter = Interpreter()
        program = interpreter.load(
            "logical-short-circuit",
            "any: and_guard := false & @missing.value == true;"
            "any: or_guard := true | @missing.value == true;",
        )

        and_result = await interpreter.evaluate(
            program.definition.context["and_guard"]
        )
        or_result = await interpreter.evaluate(
            program.definition.context["or_guard"]
        )

        self.assertIs(and_result, False)
        self.assertIs(or_result, True)

    async def test_evaluator_preserves_unbound_deferred_expression_as_data(self):
        expression = Call(
            "==",
            (Ref("action", deferrable=True), Literal("subscribe")),
        )

        evaluator = Evaluator()
        received = await evaluator.evaluate(expression, Scope())
        resolved = await evaluator.evaluate(
            expression,
            Scope({"action": "subscribe"}),
        )

        self.assertIsInstance(received, Deferred)
        self.assertEqual(received.parameters, ("action",))
        self.assertIs(resolved, True)

    async def test_authenticate_merges_successful_flow_result(self):
        class Defender:
            async def authorized(self, *args, **kwargs):
                return True

        class Provider:
            name = "stub"

            async def sign_in(self, **kwargs):
                return flow.success({
                    "providers": {"stub": {"token": "test-token"}},
                    "user": {"id": "user-1"},
                })

        session = SessionData({
            "id": "session-1",
            "context": {},
            "authentication": {},
            "results": {},
        })
        manager = Authenticator(None, Defender(), [Provider()])

        received = await manager.authenticate(session, email="a@example.test", password="x")

        self.assertTrue(received.is_success)
        updated = flow.output(received)
        self.assertIsInstance(updated, SessionData)
        self.assertEqual(session["authentication"], {})
        self.assertEqual(updated["authentication"]["user"]["id"], "user-1")
        self.assertEqual(
            updated["authentication"]["providers"]["stub"]["token"],
            "test-token",
        )

    async def test_defender_policy_session_flattens_session_data_authentication(self):
        session_data = SessionData({
            "id": "policy-user",
            "context": {},
            "authentication": {"user": {"id": "user-1"}, "providers": {}},
            "results": {},
        })

        policy_session = Defender._policy_session(session_data)

        self.assertEqual(policy_session["id"], "policy-user")
        self.assertEqual(policy_session["user"]["id"], "user-1")
        self.assertEqual(policy_session["authentication"], session_data["authentication"])

    async def test_presenter_resolves_session_data_to_defender_handle(self):
        handle = object()
        session_data = SessionData({
            "id": "presenter-user",
            "context": {},
            "authentication": {},
            "results": {},
        })

        class DefenderStub:
            def session_get(self, received):
                if received is not session_data:
                    raise AssertionError("Presenter did not pass SessionData")
                return handle

        class Loader:
            def get_managers(self):
                return {"defender": DefenderStub()}

        presenter = Presenter(
            [],
            Loader(),
            types.SimpleNamespace(get_logger=lambda _name: types.SimpleNamespace()),
        )

        self.assertIs(presenter._runtime_session(session_data), handle)

    async def test_invalidate_clears_session_after_successful_flow_result(self):
        class Defender:
            async def authorized(self, *args, **kwargs):
                return True

        class Provider:
            async def sign_out(self, session):
                return flow.success({"session": session})

        session = SessionData({
            "id": "session-1",
            "context": {},
            "authentication": {
                "providers": {"stub": {}},
                "user": {"id": "user-1"},
            },
            "results": {},
        })
        manager = Authenticator(None, Defender(), [Provider()])

        received = await manager.invalidate(session)

        self.assertTrue(received.is_success)
        updated = flow.output(received)
        self.assertEqual(session["authentication"]["user"]["id"], "user-1")
        self.assertNotIn("providers", updated["authentication"])
        self.assertNotIn("user", updated["authentication"])

    async def test_receive_propagates_provider_exception(self):
        class Provider:
            adapter = "test"
            config = {"name": "broken"}

            async def read(self, *args, **kwargs):
                raise RuntimeError("read failed")

        manager = Messenger([Provider()], defender=None, framework=None)

        received = await manager.receive(object(), receiver="broken")

        self.assertFalse(received.is_success)
        self.assertIsInstance(received.output.error, RuntimeError)
        self.assertEqual(str(received.output.error), "read failed")

    async def test_send_fails_when_every_provider_is_denied(self):
        class Defender:
            async def authorized(self, *args, **kwargs):
                return False

        class Provider:
            adapter = "test"
            config = {"name": "blocked"}
            posted = False

            async def post(self, *args, **kwargs):
                self.posted = True

        provider = Provider()
        manager = Messenger([provider], defender=Defender(), framework=None)

        received = await manager.send(object(), receiver="blocked", message="secret")

        self.assertFalse(received.is_success)
        self.assertFalse(provider.posted)

    async def test_application_startup_does_not_skip_manager_failure(self):
        class Logger:
            def info(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

        class FrameworkStub:
            def get_logger(self, _name):
                return Logger()

        class Loader:
            framework = FrameworkStub()
            kwargs = {}

            def get_managers(self):
                return {}

        class Manager:
            async def startup(self, _session):
                return flow.error("manager failed")

        app = Application(Loader(), [Manager()])
        app._install_signal_handlers = lambda: None

        with self.assertRaises(flow.FlowError) as raised:
            await asyncio.wait_for(app.startup(), timeout=0.05)

        self.assertEqual(raised.exception.value, "manager failed")

    async def test_application_startup_propagates_background_task_exception(self):
        class Logger:
            def info(self, *args, **kwargs):
                pass

            def debug(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

        class FrameworkStub:
            def get_logger(self, _name):
                return Logger()

        class Loader:
            framework = FrameworkStub()
            kwargs = {}

        failure = RuntimeError("background task failed")

        class Manager:
            async def startup(self, _session):
                async def work():
                    raise failure

                return work()

        app = Application(Loader(), [Manager()])
        app._install_signal_handlers = lambda: None

        with self.assertRaisesRegex(RuntimeError, "background task failed") as raised:
            await asyncio.wait_for(app.startup(), timeout=0.1)

        self.assertIs(raised.exception, failure)

    async def test_application_startup_propagates_background_flow_failure(self):
        class Logger:
            def info(self, *args, **kwargs):
                pass

            def debug(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

        class FrameworkStub:
            def get_logger(self, _name):
                return Logger()

        class Loader:
            framework = FrameworkStub()
            kwargs = {}

        class Manager:
            async def startup(self, _session):
                async def work():
                    return flow.error("background result failed")

                return work()

        app = Application(Loader(), [Manager()])
        app._install_signal_handlers = lambda: None

        with self.assertRaises(flow.FlowError) as raised:
            await asyncio.wait_for(app.startup(), timeout=0.1)

        self.assertEqual(raised.exception.value, "background result failed")

    async def test_application_shutdown_continues_and_reports_manager_error(self):
        class Logger:
            def __init__(self):
                self.errors = []
                self.infos = []

            def info(self, message, **kwargs):
                self.infos.append(message)

            def error(self, message, **kwargs):
                self.errors.append((message, kwargs))

        class FrameworkStub:
            def __init__(self):
                self.logger = Logger()

            def get_logger(self, _name):
                return self.logger

        class Loader:
            def __init__(self):
                self.framework = FrameworkStub()

        class WorkingManager:
            stopped = False

            async def shutdown(self, _session):
                self.stopped = True
                return flow.success(None)

        class BrokenManager:
            failure = RuntimeError("shutdown failed")

            async def shutdown(self, _session):
                raise self.failure

        loader = Loader()
        working = WorkingManager()
        app = Application(loader, [BrokenManager(), working])

        result = await app.shutdown()
        repeated_result = await app.shutdown()

        self.assertTrue(working.stopped)
        self.assertTrue(loader.framework.logger.errors)
        self.assertNotIn("Framework spento correttamente", loader.framework.logger.infos)
        self.assertFalse(result.is_success)
        self.assertIs(result.output.error[0], app._managers[0].failure)
        self.assertIs(repeated_result, result)

    async def test_defender_propagates_policy_session_creation_failure(self):
        class LoaderStub:
            current_config = {
                "manager": {"presenter": {"presentation": "test.dsl"}}
            }

            def get_managers(self):
                return {}

            async def resource(self, _path):
                return "policy DSL"

        framework_stub = types.SimpleNamespace(
            logger=types.SimpleNamespace(error=lambda *args, **kwargs: None)
        )
        manager = Defender(LoaderStub(), framework_stub, [])
        manager.interpreter.start = AsyncMock(return_value=None)
        manager.interpreter.load_file = AsyncMock(return_value=None)
        manager.session_create = AsyncMock(
            return_value=flow.error("policy session failed")
        )

        received = await manager.startup()

        self.assertFalse(received.is_success)
        self.assertEqual(flow.output(received), "policy session failed")

    async def test_defender_propagates_policy_execution_failure(self):
        class LoaderStub:
            current_config = {
                "manager": {"presenter": {"presentation": "test.dsl"}}
            }

            def get_managers(self):
                return {}

            async def resource(self, _path):
                return "policy DSL"

        class PolicySession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def run(self, _path):
                return flow.error("policy execution failed")

        framework_stub = types.SimpleNamespace(
            logger=types.SimpleNamespace(error=lambda *args, **kwargs: None)
        )
        manager = Defender(LoaderStub(), framework_stub, [])
        manager.interpreter.start = AsyncMock(return_value=None)
        manager.interpreter.load_file = AsyncMock(return_value=None)
        manager.session_create = AsyncMock(
            return_value=flow.success(PolicySession())
        )

        received = await manager.startup()

        self.assertFalse(received.is_success)
        self.assertEqual(flow.output(received), "policy execution failed")

    async def test_loader_propagates_runtime_session_failure(self):
        class DefenderStub:
            async def startup(self):
                return flow.success(None)

            async def session_create(self):
                return flow.error("runtime session failed")

        class Container:
            def get(self, _target):
                return DefenderStub()

        loader = object.__new__(Loader)
        loader.framework = types.SimpleNamespace(
            component=lambda _name: types.SimpleNamespace(
                module=types.SimpleNamespace(Manager=Defender)
            )
        )
        loader.container = Container()
        loader.logger = types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        )
        loader._apply_port_configurations = lambda _defender: None

        with self.assertRaises(flow.FlowError) as raised:
            await loader._start_runtime({})

        self.assertEqual(raised.exception.value, "runtime session failed")

    async def test_controller_execution_propagates_controller_failure(self):
        class RuntimeSession:
            async def run(self, *_args):
                return flow.error("controller failed")

        adapter = object.__new__(starlette_web.Adapter)
        adapter.loader = types.SimpleNamespace(
            get_managers=lambda: {},
        )

        with self.assertRaises(flow.FlowError) as raised:
            await adapter.execute_controllers(RuntimeSession(), ["kanban"])

        self.assertEqual(raised.exception.value, "controller failed")

    async def test_presenter_propagates_render_view_failure(self):
        class Logger:
            def info(self, *args, **kwargs):
                pass

        class FrameworkStub:
            def get_logger(self, _name):
                return Logger()

        class Infrastructure:
            def same_resource(self, _left, _right):
                return True

        class LoaderStub:
            infrastructure = Infrastructure()

        class Driver:
            routes = {"/board": {"GET": {"view": "board.dsl"}}}
            url = "/board"

            async def render_view(self, _url):
                return flow.error("view render failed")

        manager = Presenter([Driver()], LoaderStub(), FrameworkStub())

        received = await manager.reload(object(), "board.dsl")

        self.assertFalse(received.is_success)
        self.assertEqual(flow.output(received), "view render failed")

    async def test_node_update_does_not_swallow_backend_error(self):
        class Node:
            def update(self, _text):
                raise RuntimeError("text update failed")

        class Harness:
            node_union = PresentationPort.node_union

            def _apply_node_attrs(self, _node, _attrs):
                return None

        received = await PresentationAdapter.node_update(
            Harness(), Node(), {"inner": ["updated"]}
        )

        self.assertFalse(received.is_success)
        self.assertIsInstance(received.output.error, RuntimeError)

    async def test_storekeeper_propagates_provider_start_failure(self):
        class MessengerStub:
            async def send(self, *args, **kwargs):
                return flow.success(None)

        class Provider:
            config = {"name": "broken"}

            async def start(self, _session):
                return flow.error("disk unavailable")

        manager = Storekeeper([Provider()], None, None, MessengerStub())

        received = await manager.startup(object())

        self.assertFalse(received.is_success)
        self.assertEqual(flow.output(received), "disk unavailable")

    async def test_storekeeper_stops_providers_on_shutdown(self):
        class MessengerStub:
            async def send(self, *args, **kwargs):
                return flow.success(None)

        class Provider:
            config = {"name": "test"}
            stopped = False

            async def stop(self, _session):
                self.stopped = True
                return flow.success(None)

        provider = Provider()
        manager = Storekeeper([provider], None, None, MessengerStub())

        received = await manager.shutdown(object())

        self.assertTrue(received.is_success)
        self.assertTrue(provider.stopped)

    async def test_storekeeper_propagates_repository_session_creation_failure(self):
        class Loader:
            async def resource(self, _path):
                return "repository DSL"

        class Interpreter:
            async def load_file(self, *_args):
                return None

        class Defender:
            loader = Loader()
            interpreter = Interpreter()

            async def session_create(self):
                return flow.error("session creation failed")

        manager = Storekeeper([], Defender(), None, None)

        received = await manager._load_repository("items")

        self.assertFalse(received.is_success)
        self.assertEqual(flow.output(received), "session creation failed")
        self.assertNotIn("items", manager.repositories)

    async def test_storekeeper_propagates_repository_execution_failure(self):
        class Loader:
            async def resource(self, _path):
                return "repository DSL"

        class Interpreter:
            async def load_file(self, *_args):
                return None

        class RepositorySession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def run(self, _path):
                return flow.error("repository execution failed")

        class Defender:
            loader = Loader()
            interpreter = Interpreter()

            async def session_create(self):
                return flow.success(RepositorySession())

        manager = Storekeeper([], Defender(), None, None)

        received = await manager._load_repository("items")

        self.assertFalse(received.is_success)
        self.assertEqual(flow.output(received), "repository execution failed")
        self.assertNotIn("items", manager.repositories)

    async def test_orchestrator_chain_propagates_flow_failure(self):
        async def failing_task(**kwargs):
            return flow.error("operation failed")

        received = await Orchestrator(None).chain_completed(
            object(), tasks=[failing_task]
        )

        self.assertFalse(received.is_success)
        self.assertEqual(flow.output(received), "operation failed")

    async def test_orchestrator_first_completed_waits_for_successful_operation(self):
        async def failed_operation():
            await asyncio.sleep(0)
            return flow.error("first provider failed")

        async def successful_operation():
            await asyncio.sleep(0.01)
            return flow.success("ready")

        tasks = [asyncio.create_task(failed_operation()), asyncio.create_task(successful_operation())]
        received = await Orchestrator(None).first_completed(object(), operations=tasks)

        self.assertTrue(received.is_success)
        self.assertEqual(flow.output(received), "ready")

    async def test_orchestrator_all_completed_preserves_task_exception(self):
        async def failing_operation():
            raise RuntimeError("worker exploded")

        task = asyncio.create_task(failing_operation())
        received = await Orchestrator(None).all_completed(object(), tasks=[task])

        self.assertFalse(received.is_success)
        self.assertIn("worker exploded", str(flow.output(received)))

    async def test_filesystem_resolve_path_prefers_explicit_location(self):
        path = FilesystemAdapter._resolve_path(
            location="/tmp/integration.txt",
            filter={"eq": {"filename": "ignored.txt"}},
        )

        self.assertEqual(path, "/tmp/integration.txt")

    async def test_filesystem_rejects_filename_traversal_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            outside_file = Path(directory) / "outside.txt"
            outside_file.write_text("private", encoding="utf-8")
            adapter = FilesystemAdapter(messenger=None, path=str(root))

            received = await adapter.request(
                method="GET",
                path=str(root),
                filter={"eq": {"filename": "../outside.txt"}},
            )

            self.assertFalse(received.is_success)
            self.assertEqual(outside_file.read_text(encoding="utf-8"), "private")

    async def test_filesystem_payload_data_extracts_content(self):
        content = FilesystemAdapter._payload_data(
            payload={"content": "hello"}
        )

        self.assertEqual(content, "hello")

    async def test_filesystem_json_document_preserves_list_shape(self):
        document = FilesystemAdapter._json_document(
            [{"id": 1}], [{"id": 2}]
        )

        self.assertEqual(document, [{"id": 2}])

    async def test_corrupt_json_is_not_replaced_by_post(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            original = "{not valid json"
            path.write_text(original, encoding="utf-8")
            adapter = FilesystemAdapter(messenger=None, path=directory)

            received = await adapter.request(
                method="POST",
                location=str(path),
                payload={"id": "new"},
            )

            self.assertFalse(received.is_success)
            self.assertIsInstance(received.output.error, json.JSONDecodeError)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    async def test_watcher_logs_failed_event_publication(self):
        class Logger:
            def __init__(self):
                self.errors = []

            def error(self, message, **kwargs):
                self.errors.append((message, kwargs))

        class Adapter:
            logger = Logger()

            async def handle_watcher_event(self, *_args):
                return flow.error("event publish failed")

        adapter = Adapter()
        handler = FileWatcherHandler(adapter, object(), asyncio.get_running_loop())
        event = types.SimpleNamespace(is_directory=False, src_path="/tmp/item.txt")

        handler._trigger_event("modified", event)
        await asyncio.sleep(0.01)

        self.assertTrue(adapter.logger.errors)
        self.assertIn("Pubblicazione evento watcher fallita", adapter.logger.errors[0][0])

    async def test_filesystem_stop_propagates_observer_error(self):
        class Observer:
            def is_alive(self):
                return False

            def stop(self):
                raise RuntimeError("observer stop failed")

            def join(self):
                return None

        adapter = FilesystemAdapter(messenger=None)
        adapter.observer = Observer()

        received = await adapter.stop()

        self.assertFalse(received.is_success)
        self.assertIsInstance(received.output.error, RuntimeError)

    async def test_session_wait_wraps_non_exception_error(self):
        session = Session("dag", "session-1")
        session.errors["node"] = "node failed"
        session.mark("node", NodeState.FAILED)

        with self.assertRaises(flow.FlowError) as raised:
            await session.wait("node")

        self.assertEqual(raised.exception.value, "node failed")

    async def test_forced_module_reload_restores_previous_module_on_failure(self):
        module_name = "temporary_error_reload"
        previous = types.ModuleType(module_name)
        sys.modules[module_name] = previous
        framework = Framework()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "broken.py"
                path.write_text("def broken(:\n", encoding="utf-8")

                with self.assertRaises(SyntaxError):
                    await framework.load_module(module_name, str(path), force=True)

            self.assertIs(sys.modules[module_name], previous)
        finally:
            sys.modules.pop(module_name, None)

    async def test_malformed_route_table_raises_instead_of_becoming_not_found(self):
        with self.assertRaises(StopIteration):
            resolve_route({"/broken": {}}, "/broken", "GET")


if __name__ == "__main__":
    unittest.main()