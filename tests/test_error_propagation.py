import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import framework.core.flow as flow
from framework.core.application import Application
from framework.core.data import Registry
from framework.core.evaluation import EvaluationError, Evaluator
from framework.core.framework import Framework
from framework.core.interpreter import Interpreter
from framework.core.model import Call, DagDefinition, Deferred, Literal, Ref
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
from framework.service.route import resolve_route
import framework.service.template as template_service
from infrastructure.persistence.filesystem.filesystem import (
    Adapter as FilesystemAdapter,
    FileWatcherHandler,
)
from infrastructure.presentation.adapter import Adapter as PresentationAdapter
from infrastructure.presentation.tui.widgets import _make_action
from framework.port.presentation import Port as PresentationPort


class ErrorPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_oauth_boolean_parser_accepts_textual_flags(self):
        if importlib.util.find_spec("aiohttp") is None:
            self.skipTest("OAuth2 adapter e opzionale")

        from infrastructure.authentication.oauth2.oauth import Adapter as OAuthAdapter

        self.assertTrue(OAuthAdapter._bool("true"))
        self.assertFalse(OAuthAdapter._bool("false"))

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

    async def test_template_propagates_controller_failure(self):
        class Template:
            def render(self, _context):
                return "<root />"

        class Environment:
            def from_string(self, _text):
                return Template()

        class RuntimeSession:
            async def run(self, *_args):
                return flow.error("controller failed")

        async def render_node(*_args, **_kwargs):
            return "rendered"

        with patch.object(template_service, "get_jinja", return_value=Environment()):
            with self.assertRaises(flow.FlowError) as raised:
                await template_service.render(
                    None,
                    {},
                    RuntimeSession(),
                    render_node,
                    text="<root />",
                    controllers=["kanban"],
                )

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