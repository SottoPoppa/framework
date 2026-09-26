import sys
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import Button, Input, Label, Link, RadioButton, Static

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from infrastructure.presentation.tui.textual import Adapter as TextualAdapter
from infrastructure.presentation.tui.textual import LogBuffer
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
