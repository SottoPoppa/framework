import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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


class PresentationTextualRebuildTests(unittest.IsolatedAsyncioTestCase):
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
