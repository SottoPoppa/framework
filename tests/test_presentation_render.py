import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from textual.app import App
from textual.widgets import Button, Input, Label, Link, RadioButton, Static


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from infrastructure.presentation.tui.textual import Adapter as TextualAdapter
from infrastructure.presentation.tui.textual import LogBuffer
from infrastructure.presentation.tui.textual import NavigationCommandProvider
from framework.service.dom import parse as parse_dom
from infrastructure.presentation.tui.widgets import (
	OptionValue,
	PaletteCommand,
	PaletteSource,
	tags,
	_make_tabbed_content,
)
from infrastructure.presentation.web import starlette
from infrastructure.presentation.adapter import Adapter as PresentationAdapter
from framework.manager.presenter import Manager as PresenterManager


class PresentationRenderTests(unittest.TestCase):
	def test_url_scheme_filter_is_case_insensitive_for_attribute_names(self):
		for name in ("HREF", "Href"):
			with self.subTest(name=name):
				attributes = starlette.attrs(
					"action",
					{"attrs": {name: "javascript:alert(1)"}},
				)
				html = starlette.Adapter.node_create(
					None,
					starlette.htpy.a,
					attributes,
					["Open"],
				)

				self.assertNotIn(name, attributes)
				self.assertNotIn("javascript:", html)

		safe_attributes = starlette.attrs(
			"action",
			{"attrs": {"HREF": "https://example.test"}},
		)
		self.assertEqual(safe_attributes["HREF"], "https://example.test")

	def test_fractional_dimensions_expand_flex_items(self):
		width = starlette.attrs("column", {"attrs": {"width": "1fr"}})
		height = starlette.attrs("row", {"attrs": {"height": "1fr"}})
		weighted_width = starlette.attrs("column", {"attrs": {"width": "2fr"}})

		self.assertIn("flex-1 min-w-40", width["class"])
		self.assertIn("flex-1 min-h-0", height["class"])
		self.assertIn("flex-[2] min-w-40", weighted_width["class"])

	def test_option_tag_renders_value_and_label(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)

		option = adapter.mount_tag("option", {"value": "active"}, ["Active"])

		self.assertIn('value="active"', str(option))
		self.assertIn(">Active</option>", str(option))

	def test_editor_renders_child_content_in_a_textarea(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		source = "def move_to_todo(): pass"
		editor = adapter.mount_tag(
			"input",
			{"type": "editor", "id": "source-editor", "language": "python"},
			[adapter.mount_tag("text", {}, [source])],
		)
		textarea = starlette.BeautifulSoup(str(editor), "html.parser").find(
			"textarea", id="source-editor"
		)

		self.assertIsNotNone(textarea)
		self.assertEqual(textarea.get_text(), source)
		self.assertEqual(textarea.get("language"), "python")

	def test_select_renders_valid_options_and_marks_the_selected_value(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		select = adapter.mount_tag(
			"input",
			{"type": "select", "id": "file-select", "value": "pyproject.toml"},
			[
				adapter.mount_tag("option", {"value": "README.md"}),
				adapter.mount_tag("option", {"value": "pyproject.toml"}),
				adapter.mount_tag("option", {"value": "src/application/controller/kanban.dsl"}),
			],
		)
		parsed = starlette.BeautifulSoup(str(select), "html.parser")
		options = parsed.select("select > option")

		self.assertEqual(len(options), 3)
		self.assertNotIn("type", parsed.select_one("select").attrs)
		self.assertEqual(options[0].get_text(), "README.md")
		self.assertTrue(options[1].has_attr("selected"))
		self.assertEqual(options[1].get_text(), "pyproject.toml")
		self.assertFalse(options[2].has_attr("selected"))
		self.assertEqual(options[2].get_text(), "src/application/controller/kanban.dsl")

	def test_action_preserves_form_target_for_event_payload(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		create_action = adapter.mount_tag(
			"action",
			{
				"type": "button",
				"id": "create-task",
				"click": "kanban:create_task",
				"form": "new-task-dialog",
			},
			["Create task"],
		)

		self.assertIn('data-click="kanban:create_task"', str(create_action))
		self.assertIn('form="new-task-dialog"', str(create_action))

	def test_tab_group_renders_sections_in_valid_panels(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		group = adapter.mount_tag(
			"group",
			{"id": "workspace-editors", "type": "tab", "value": "framework"},
			[
				adapter.mount_tag(
					"option",
					{"title": "Applicazione", "value": "application"},
					[adapter.mount_tag("container", {"id": "application-panel"}, ["App section"])],
				),
				adapter.mount_tag(
					"option",
					{"title": "Framework", "value": "framework"},
					[adapter.mount_tag("container", {"id": "framework-panel"}, ["Framework section"])],
				),
			],
		)
		parsed = starlette.BeautifulSoup(str(group), "html.parser")
		tabs = parsed.select('[role="tablist"] [role="tab"]')
		panels = parsed.select('[role="tabpanel"]')

		self.assertEqual([tab.get_text() for tab in tabs], ["Applicazione", "Framework"])
		self.assertEqual(tabs[1].get("aria-selected"), "true")
		self.assertIn("hidden", panels[0].attrs)
		self.assertNotIn("hidden", panels[1].attrs)
		self.assertIn("Framework section", panels[1].get_text())
		self.assertIsNone(parsed.find("option"))

	def test_navigation_tabs_render_as_buttons_and_keep_event_values(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		navigation = adapter.mount_tag(
			"navigation",
			{"type": "tabs", "id": "application-files", "value": "src/app.py"},
			[
				adapter.mount_tag(
					"option",
					{"value": "src/app.py", "click": "terminal:select_application"},
				),
			],
		)
		parsed = starlette.BeautifulSoup(str(navigation), "html.parser")
		tab = parsed.select_one('[role="tab"]')

		self.assertIsNotNone(tab)
		self.assertEqual(tab.get_text(), "src/app.py")
		self.assertEqual(tab.get("data-click"), "terminal:select_application")
		self.assertTrue(tab.has_attr("data-tab-event"))

	def test_modal_window_type_renders_targeted_overlay(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)

		modal = adapter.mount_tag(
			"window",
			{"type": "modal", "id": "confirm", "title": "Conferma"},
			["Continua"],
		)

		html = str(modal)
		self.assertIn('class="dsl-modal fixed inset-0 z-50 hidden items-center justify-center p-4 target:flex"', html)
		self.assertIn('id="confirm"', html)
		self.assertIn('role="dialog"', html)
		self.assertIn('aria-modal="true"', html)
		self.assertIn('href="#"', html)
		self.assertIn(">Conferma</h2>", html)
		self.assertIn("Continua", html)

	def test_page_window_provides_viewport_height_to_its_content(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)

		page = adapter.mount_tag("window", {"type": "page"}, ["Board"])

		self.assertIn('<body class="h-screen', str(page))

	def test_page_runtime_dispatches_action_values_and_routes(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		move_action = adapter.mount_tag(
			"action",
			{"type": "button", "click": "kanban:move_to_todo", "value": "task-1"},
			["Move"],
		)
		open_action = adapter.mount_tag(
			"action",
			{
				"type": "button",
				"route": "/ide",
				"click": "terminal:select",
				"value": "src/app.py",
			},
			["Open file"],
		)
		page = adapter.mount_tag("window", {"type": "page"}, [move_action, open_action])
		html = str(page)

		self.assertIn('data-click="kanban:move_to_todo"', html)
		self.assertIn('value="task-1"', html)
		self.assertIn("const eventPayload = (el, domEvent) =>", html)
		self.assertIn("const syncTerminalSelection = (value) =>", html)
		self.assertIn("const payload = eventPayload(el, domEvent)", html)
		self.assertIn("payload,", html)
		self.assertIn("location.assign(route)", html)

	def test_navigation_palette_renders_as_a_searchable_dialog(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)

		palette = adapter.mount_tag(
			"navigation",
			{"type": "palette", "id": "commands"},
			["Open IDE"],
		)

		html = str(palette)
		self.assertIn('href="#commands"', html)
		self.assertIn('role="dialog"', html)
		self.assertIn('data-palette-search=""', html)
		self.assertIn('data-palette-items=""', html)
		self.assertIn("Open IDE", html)
		self.assertNotIn("<nav", html)

	def test_uvicorn_logs_are_forwarded_to_framework_logger(self):
		framework_logger = Mock()
		handler = starlette._FrameworkLogHandler(framework_logger)
		record = starlette.logging.LogRecord(
			"uvicorn.error",
			starlette.logging.WARNING,
			__file__,
			1,
			"Request failed: %s",
			("bad request",),
			None,
		)

		handler.emit(record)

		framework_logger.warning.assert_called_once_with(
			"Request failed: bad request",
			source_logger="uvicorn.error",
		)
		log_config = starlette._uvicorn_log_config()
		self.assertEqual(set(log_config["formatters"]), {"default", "access"})
		self.assertIs(
			log_config["handlers"]["framework"]["framework_logger"],
			starlette.logger,
		)
		self.assertIn("uvicorn.access", log_config["loggers"])
		self.assertIn("uvicorn.access", log_config["loggers"])

	def test_starlette_uses_the_shared_presentation_adapter(self):
		self.assertTrue(issubclass(starlette.Adapter, PresentationAdapter))

	def test_presenter_selects_adapter_by_session_id(self):
		web_session = SimpleNamespace(sid="web-session")
		tui_session = SimpleNamespace(sid="tui-session")
		web_adapter = SimpleNamespace(sessions={"web-session": web_session})
		tui_adapter = SimpleNamespace(sessions={"tui-session": tui_session})
		presenter = PresenterManager.__new__(PresenterManager)
		presenter.presentations = [web_adapter, tui_adapter]

		self.assertIs(presenter._get_driver(web_session), web_adapter)
		self.assertIs(presenter._get_driver(tui_session), tui_adapter)


class StarletteRebuildTests(unittest.IsolatedAsyncioTestCase):
	async def test_rebuild_renders_original_view_and_sends_updated_fragment(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		runtime_session = SimpleNamespace(sid="web-session")
		source = (
			"<Window><Row id='kanban-board'>"
			"{% storekeeper(repository='task') as tasks %}"
			"{% for task in tasks %}{{ task.title }}{% endfor %}"
			"{% endstorekeeper %}</Row></Window>"
		)
		request_session = {"id": "web-session", "csrf_token": "test-token"}
		adapter._session_controllers["web-session"] = ["kanban"]
		adapter._session_views["web-session"] = {
			"text": source,
			"source_name": "src/application/view/page/kanban.xml",
			"session": request_session,
		}
		adapter.DOM["kanban-board"] = '<Row id="kanban-board">Old tasks</Row>'
		adapter.active_websockets["web-session"] = [
			SimpleNamespace(send_text=AsyncMock())
		]
		adapter.get_controller_contexts = Mock(return_value={"kanban": {}})
		adapter.render_template = AsyncMock(
			return_value='<div id="kanban-board">Updated task</div>'
		)

		await adapter.rebuild(runtime_session, "kanban-board", {})

		adapter.render_template.assert_awaited_once_with(
			runtime_session,
			text=source,
			controller_context={"kanban": {}},
			source_name="src/application/view/page/kanban.xml",
			session=request_session,
		)
		websocket = adapter.active_websockets["web-session"][0]
		websocket.send_text.assert_awaited_once()
		frame = starlette.json.loads(websocket.send_text.await_args.args[0])
		self.assertEqual(frame["type"], "update")
		self.assertEqual(frame["id"], "kanban-board")
		self.assertIn("Updated task", frame["html"])
		self.assertNotIn("Old tasks", frame["html"])


class PresentationTextualRebuildTests(unittest.IsolatedAsyncioTestCase):
	async def test_websocket_dispatches_events_through_dsl_messenger(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		runtime_session = SimpleNamespace(
			sid="web-session",
			emit=AsyncMock(return_value=None),
		)
		messenger = SimpleNamespace(send=AsyncMock(return_value=None))
		adapter.messenger = messenger
		adapter.defender = SimpleNamespace(
			session_get=lambda _sid: runtime_session,
		)
		adapter.sessions["web-session"] = runtime_session
		adapter.executor = SimpleNamespace(
			interpreter=SimpleNamespace(
				runner=SimpleNamespace(
					nodes={"src/application/controller/kanban.dsl"},
				)
			)
		)

		class FakeWebSocket:
			headers = {"origin": "http://example.test"}
			url = "ws://example.test/reactive"
			session = {"id": "web-session"}

			def __init__(self):
				self.received = False

			async def accept(self):
				return None

			async def receive_json(self):
				if not self.received:
					self.received = True
					return {
						"type": "event",
						"name": "kanban:move_to_todo",
						"payload": {"value": "task-1"},
					}
				raise starlette.WebSocketDisconnect(code=1000)

		await adapter.render_reactive(FakeWebSocket())

		messenger.send.assert_awaited_once_with(
			runtime_session,
			adapter="dsl",
			receiver="kanban",
			domain="move_to_todo",
			message={"value": "task-1"},
		)
		runtime_session.emit.assert_not_awaited()


	async def test_websocket_disconnect_cleans_session_socket_registry(self):
		adapter = starlette.Adapter(
			None, None, None, None, None,
			manager={"defender": {"key": "test-key"}},
		)
		runtime_session = SimpleNamespace(sid="web-session")
		adapter.sessions["web-session"] = runtime_session
		adapter.defender = SimpleNamespace(
			session_get=lambda _sid: runtime_session,
		)

		class FakeWebSocket:
			headers = {"origin": "http://example.test"}
			url = "ws://example.test/reactive"
			session = {"id": "web-session"}

			async def accept(self):
				return None

			async def receive_json(self):
				raise starlette.WebSocketDisconnect(code=1000)

		await adapter.render_reactive(FakeWebSocket())

		self.assertNotIn("web-session", adapter.active_websockets)


	async def test_palette_compilation_skips_transient_action_widgets(self):
		adapter = TextualAdapter(None, None, None, None, LogBuffer())

		def unexpected_action_factory(_node):
			self.fail("palette actions should not be mounted as Textual widgets")

		navigation = parse_dom(
			'<Navigation id="palette" type="palette">'
			'<Action id="open-ide" route="/ide">'
			'<Text> Open <Text id="palette-label">IDE</Text></Text></Action>'
			'<Action type="button" route="/ide" click="terminal:select" '
			'value="src/app.py"><Text>Open source file</Text></Action>'
			'</Navigation>'
		)
		with patch.dict(
			tags["action"],
			{
				"action": unexpected_action_factory,
				"button": unexpected_action_factory,
			},
		):
			palette = await adapter.render_node(None, navigation, {})

		self.assertIsInstance(palette, PaletteSource)
		self.assertIs(adapter.widgets.get("palette"), palette)
		self.assertEqual(
			[command.label for command in palette._dsl_palette_commands],
			["Open IDE", "Open source file"],
		)
		self.assertEqual(palette._dsl_palette_commands[0].value, " Open IDE")
		self.assertFalse(palette._dsl_palette_commands[0].has_value)
		self.assertEqual(palette._dsl_palette_commands[0].action_id, "open-ide")
		self.assertIsNotNone(adapter.node_get("open-ide"))
		self.assertIsNotNone(adapter.node_get("palette-label"))
		self.assertEqual(palette._dsl_palette_commands[1].click, "terminal:select")
		self.assertEqual(palette._dsl_palette_commands[1].value, "src/app.py")
		self.assertTrue(palette._dsl_palette_commands[1].has_value)

	async def test_terminal_scope_component_expands_for_each_scope(self):
		project_root = Path(__file__).resolve().parents[1]

		class FakeInfrastructure:
			jinja_environments = {}

			def resource(self, path):
				return (project_root / path).read_text(encoding="utf-8")

		class FakeLoader:
			infrastructure = FakeInfrastructure()

			def get_managers(self):
				return {}

		class TestAdapter(TextualAdapter):
			async def _load_storekeeper(self, runtime_session, attributes):
				return {"content": "test content"}

		adapter = TestAdapter(FakeLoader(), None, None, None, LogBuffer())
		scope_files = {
			"application": ["src/application/main.py"],
			"framework": ["src/framework/core/flow.py"],
			"infrastructure": ["src/infrastructure/presentation/tui/textual.py"],
		}
		available_file_paths = []
		for files in scope_files.values():
			for source_file in files:
				stem = source_file.rsplit(".", 1)[0]
				available_file_paths.extend(
					[source_file, f"{stem}.test.dsl", f"{stem}.contract.json"]
				)

		def success(value):
			return {"output": {"is_success": True, "value": value}}

		terminal_context = {
			"files": success([{"relative_path": path} for path in available_file_paths]),
			"application_files": success(scope_files["application"]),
			"framework_files": success(scope_files["framework"]),
			"infrastructure_files": success(scope_files["infrastructure"]),
			"select": scope_files["framework"][0],
			"select_application": scope_files["application"][0],
			"select_framework": scope_files["framework"][0],
			"select_infrastructure": scope_files["infrastructure"][0],
		}

		await adapter.render_template(
			None,
			text=(
				'<Window type="page">'
				'<Group id="workspace-editors" type="tab" value="framework">'
				'<TerminalScopePanel scope="application" title="Applicazione" />'
				'<TerminalScopePanel scope="framework" title="Framework" />'
				'<TerminalScopePanel scope="infrastructure" title="Infrastruttura" />'
				'</Group>'
				'</Window>'
			),
			controller_context={"terminal": terminal_context},
		)

		for scope in ("application", "framework", "infrastructure"):
			with self.subTest(scope=scope):
				self.assertIsNotNone(adapter.widgets.get(f"{scope}-panel"))
				self.assertIsNotNone(adapter.widgets.get(f"{scope}-editors"))
				for sub_type in ("file", "test", "contract"):
					self.assertIsNotNone(
						adapter.widgets.get(f"{scope}-{sub_type}-editor")
					)

	async def test_custom_components_expand_and_keep_slotted_content(self):
		project_root = Path(__file__).resolve().parents[1]

		class FakeInfrastructure:
			jinja_environments = {}

			def resource(self, path):
				return (project_root / path).read_text(encoding="utf-8")

		class FakeLoader:
			infrastructure = FakeInfrastructure()

			def get_managers(self):
				return {}

		adapter = TextualAdapter(FakeLoader(), None, None, None, LogBuffer())
		await adapter.render_template(
			None,
			text=(
				'<Window type="page">'
				'<NewTaskButton id="new-task" />'
				'<NewTaskDialog id="new-task-dialog" default_file="src/app.py">'
				'<Option value="src/app.py" title="src/app.py" />'
				'</NewTaskDialog>'
				'<Navigation id="developer-command-palette" type="palette">'
				'<Action route="/ide"><Text>Open IDE</Text></Action>'
				'<Action route="/ide" click="terminal:select" value="src/app.py">'
				'<Text>Open source file</Text></Action>'
				'</Navigation>'
				'<KanbanTaskCard id="task-card" title="Fix task" description="Task description" file="src/app.py">'
				'<Action type="button" click="kanban:move_to_todo" value="task-1">'
				'<Text>Move</Text></Action>'
				'</KanbanTaskCard>'
				'</Window>'
			),
		)

		self.assertIn('route="#new-task-dialog"', adapter.node_get("new-task"))
		file_select = adapter.node_get("task-file")
		self.assertIn('value="src/app.py"', file_select)
		self.assertIn('title="src/app.py"', file_select)
		palette = adapter.widgets.get("developer-command-palette")
		commands = palette._dsl_palette_commands
		self.assertEqual([command.label for command in commands], ["Open IDE", "Open source file"])
		self.assertEqual(commands[0].route, "/ide")
		self.assertEqual(commands[1].click, "terminal:select")
		self.assertEqual(commands[1].value, "src/app.py")
		task_card = adapter.node_get("task-card")
		self.assertIn(">Fix task</Text>", task_card)
		self.assertIn("Task description", task_card)
		self.assertIn('id="task-card-ide"', task_card)
		self.assertIn('route="/ide"', task_card)
		self.assertIn('click="terminal:select"', task_card)
		self.assertIn('value="src/app.py"', task_card)
		self.assertIn('click="kanban:move_to_todo"', task_card)

	async def test_palette_provider_searches_and_dispatches_navigation_actions(self):
		command = PaletteCommand(
			label="Open src/app.py",
			route="/ide",
			click="terminal:select",
			value="src/app.py",
			has_value=True,
		)
		source = PaletteSource([command])

		class FakeApp:
			def __init__(self):
				self.activated = []

			async def activate_palette_command(self, selected_command):
				self.activated.append(selected_command)

		class FakeScreen:
			def __init__(self, app, palette_source):
				self.app = app
				self.palette_source = palette_source

			def query(self, widget_type):
				return [self.palette_source] if widget_type is PaletteSource else []

		app = FakeApp()
		provider = NavigationCommandProvider(FakeScreen(app, source))
		hits = [hit async for hit in provider.search("app.py")]

		self.assertEqual([hit.text for hit in hits], ["Open src/app.py"])
		await hits[0].command()
		self.assertEqual(app.activated, [command])

	async def test_group_tab_value_selects_the_initial_pane(self):
		adapter = TextualAdapter(None, None, None, None, LogBuffer())
		app = App()
		panes = [
			adapter.mount_tag(
				"option",
				{"title": scope, "value": scope},
				[Static(scope)],
			)
			for scope in ("application", "framework", "infrastructure")
		]
		workspace = adapter.mount_tag(
			"group",
			{"id": "workspace", "type": "tab", "value": "infrastructure"},
			panes,
		)

		async with app.run_test() as pilot:
			await app.screen.mount(workspace)
			await pilot.pause()
			self.assertEqual(workspace.active, "infrastructure")

	async def test_scope_rebuild_id_resolves_to_the_nested_column(self):
		adapter = TextualAdapter(None, None, None, None, LogBuffer())
		app = App()
		adapter.app = app
		column = adapter.mount_tag(
			"column",
			{"id": "framework-panel"},
			[Static("framework")],
		)
		workspace = _make_tabbed_content({
			"attrs": {"id": "workspace", "value": "framework"},
			"inner": [
				OptionValue("Framework", "framework", content=[column])
			],
		})

		async with app.run_test() as pilot:
			await app.screen.mount(workspace)
			await pilot.pause()
			self.assertIs(adapter.dom_get("framework-panel"), column)
			self.assertEqual(type(adapter.dom_get("framework")).__name__, "TabPane")

	async def test_reuses_same_widget_and_preserves_unchanged_input(self):
		adapter = TextualAdapter(None, None, None, None, LogBuffer())
		app = App()
		async with app.run_test():
			button = Button("prima", id="button")
			await app.screen.mount(button)
			adapter._register_node("button", button)

			self.assertTrue(
				await adapter._update_widget_in_place(
					button,
					Button("dopo", id="button"),
					{"id": "button"},
				)
			)
			self.assertEqual(button.label, "dopo")

			field = Input(value="iniziale", id="field")
			await app.screen.mount(field)
			adapter._register_node("field", field)
			field.value = "digitato"

			self.assertTrue(
				await adapter._update_widget_in_place(
					field,
					Input(value="iniziale", id="field"),
					{"id": "field"},
				)
			)
			self.assertEqual(field.value, "digitato")

			self.assertTrue(
				await adapter._update_widget_in_place(
					field,
					Input(value="aggiornato", id="field"),
					{"id": "field"},
				)
			)
			self.assertEqual(field.value, "aggiornato")
			self.assertFalse(
				await adapter._update_widget_in_place(
					button,
					Label("testo", id="button"),
					{"id": "button"},
				)
			)

			old_child = adapter.mount_tag("text", {"id": "nested"}, ["prima"])
			container = adapter.mount_tag(
				"container", {"id": "group"}, [old_child]
			)
			await app.screen.mount(container)
			new_child = adapter.mount_tag("text", {"id": "nested"}, ["dopo"])
			rendered_container = adapter.mount_tag(
				"container", {"id": "group"}, [new_child]
			)

			self.assertTrue(
				await adapter._update_widget_in_place(
					container,
					rendered_container,
					{"id": "group"},
				)
			)
			self.assertIs(container.query_one("#nested"), old_child)
			self.assertEqual(str(old_child.content), "dopo")

			rendered_button = adapter.mount_tag(
				"action", {"id": "nested"}, ["clicca"]
			)
			rendered_container = adapter.mount_tag(
				"container", {"id": "group"}, [rendered_button]
			)
			self.assertTrue(
				await adapter._update_widget_in_place(
					container,
					rendered_container,
					{"id": "group"},
				)
			)
			self.assertIsInstance(container.query_one("#nested"), Button)
			self.assertIsNot(container.query_one("#nested"), old_child)

			radio = RadioButton("prima", id="radio")
			await app.screen.mount(radio)
			adapter._register_node("radio", radio)
			self.assertTrue(
				await adapter._update_widget_in_place(
					radio,
					RadioButton("dopo", value=True, id="radio"),
					{"id": "radio"},
				)
			)
			self.assertTrue(radio.value)

			link = Link("prima", url="https://old.test", id="link")
			await app.screen.mount(link)
			adapter._register_node("link", link)
			self.assertTrue(
				await adapter._update_widget_in_place(
					link,
					Link("dopo", url="https://new.test", id="link"),
					{"id": "link"},
				)
			)
			self.assertEqual(link.url, "https://new.test")

			old_id_child = adapter.mount_tag(
				"text", {"id": "old-id"}, ["prima"]
			)
			id_container = adapter.mount_tag(
				"container", {"id": "id-group"}, [old_id_child]
			)
			await app.screen.mount(id_container)
			new_id_child = adapter.mount_tag(
				"text", {"id": "new-id"}, ["dopo"]
			)
			rendered_id_container = adapter.mount_tag(
				"container", {"id": "id-group"}, [new_id_child]
			)
			self.assertTrue(
				await adapter._update_widget_in_place(
					id_container,
					rendered_id_container,
					{"id": "id-group"},
				)
			)
			self.assertIsNone(old_id_child.parent)
			self.assertIs(id_container.query_one("#new-id"), new_id_child)

	async def test_reconciles_child_order_and_removes_stale_nodes(self):
		adapter = TextualAdapter(None, None, None, None, LogBuffer())
		app = App()
		children = [
			adapter.mount_tag("text", {"id": node_id}, [initial_text])
			for node_id, initial_text in (
				("first", "First"),
				("second", "Second"),
				("third", "Third"),
			)
		]
		container = adapter.mount_tag("container", {"id": "parent"}, children)

		async with app.run_test():
			await app.screen.mount(container)
			await adapter._reconcile_widget_children(
				container,
				[
					adapter.mount_tag("text", {"id": "third"}, ["Third updated"]),
					adapter.mount_tag("text", {"id": "first"}, ["First updated"]),
					adapter.mount_tag("text", {"id": "fourth"}, ["Fourth"]),
				],
			)

			self.assertEqual(
				[getattr(child, "_dsl_node_id", None) for child in container.children],
				["third", "first", "fourth"],
			)
			self.assertIs(container.children[0], children[2])
			self.assertIs(container.children[1], children[0])
			self.assertEqual(str(children[2].content), "Third updated")
			self.assertEqual(str(children[0].content), "First updated")
			self.assertIsNone(children[1].parent)
			self.assertIsNone(adapter.widgets.get("second"))
