import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from infrastructure.presentation.adapter import Adapter as PresentationAdapter
from infrastructure.presentation.tui.textual import Adapter as TuiAdapter
from infrastructure.presentation.tui.textual import AppDinamica
from infrastructure.presentation.tui.widgets import PaletteCommand
from framework.service import dom as dom_service
from textual.binding import Binding
from textual.widgets import Button


class AdapterSpy:
    def __init__(self):
        self.navigated = []
        self.history_actions = []
        self.calls = []

    def node_get(self, node_id):
        return None

    async def navigate_to(self, url):
        self.navigated.append(url)
        self.calls.append(("navigate", url))

    async def navigate_back(self):
        self.history_actions.append("back")

    async def navigate_forward(self):
        self.history_actions.append("forward")


class TuiActionNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_only_button_without_dsl_node_navigates(self):
        adapter = AdapterSpy()
        app = AppDinamica(adapter)
        button = Button("Open")
        button._dsl_route = "/ide"

        await app.on_button_pressed(Button.Pressed(button))

        self.assertEqual(adapter.navigated, ["/ide"])

    async def test_route_action_selects_file_after_navigation(self):
        adapter = AdapterSpy()
        app = AppDinamica(adapter)
        button = Button("Open")
        button._dsl_route = "/ide"
        button._dsl_click = "terminal:select"
        button._dsl_value = "src/application/view/page/kanban.xml"

        async def send_event(event_name, message):
            adapter.calls.append(("event", event_name, message))

        with patch.object(
            app,
            "_send_dsl_event",
            new=AsyncMock(side_effect=send_event),
        ) as dispatch:
            await app.on_button_pressed(Button.Pressed(button))

        dispatch.assert_awaited_once_with(
            "terminal:select",
            "src/application/view/page/kanban.xml",
        )
        self.assertEqual(
            adapter.calls,
            [
                ("navigate", "/ide"),
                ("event", "terminal:select", "src/application/view/page/kanban.xml"),
            ],
        )

    async def test_palette_route_command_selects_file_after_navigation(self):
        adapter = AdapterSpy()
        app = AppDinamica(adapter)
        selected_file = "src/application/view/page/kanban.xml"

        async def send_event(event_name, message):
            adapter.calls.append(("event", event_name, message))

        with patch.object(
            app,
            "_send_dsl_event",
            new=AsyncMock(side_effect=send_event),
        ) as dispatch:
            await app.activate_palette_command(
                PaletteCommand(
                    label="Open Kanban source",
                    route="/ide",
                    click="terminal:select",
                    value=selected_file,
                    has_value=True,
                )
            )

        dispatch.assert_awaited_once_with("terminal:select", selected_file)
        self.assertEqual(
            adapter.calls,
            [("navigate", "/ide"), ("event", "terminal:select", selected_file)],
        )

    async def test_stale_select_change_does_not_clear_programmatic_selection(self):
        messenger = AsyncMock()
        selected_file = "src/application/view/page/kanban.xml"
        default_file = "src/infrastructure/presentation/tui/textual.py"
        adapter = SimpleNamespace(
            messenger=messenger,
            session=object(),
            node_get=lambda _node_id: dom_service.parse(
                f'<Input id="select" value="{selected_file}" change="terminal:select"/>'
            ),
        )
        app = AppDinamica(adapter)
        app._programmatic_select_changes["select"] = selected_file

        await app.on_select_changed(
            SimpleNamespace(
                select=SimpleNamespace(id="select", value=selected_file),
                value=default_file,
            )
        )

        messenger.send.assert_not_awaited()
        self.assertEqual(app._programmatic_select_changes["select"], selected_file)

    async def test_current_user_select_change_is_dispatched(self):
        messenger = AsyncMock()
        selected_file = "src/application/view/page/kanban.xml"
        user_selected_file = "src/application/view/page/terminal.xml"
        session = object()
        adapter = SimpleNamespace(
            messenger=messenger,
            session=session,
            node_get=lambda _node_id: dom_service.parse(
                f'<Input id="select" value="{selected_file}" change="terminal:select"/>'
            ),
        )
        app = AppDinamica(adapter)
        app._programmatic_select_changes["select"] = selected_file

        await app.on_select_changed(
            SimpleNamespace(
                select=SimpleNamespace(id="select", value=user_selected_file),
                value=user_selected_file,
            )
        )

        messenger.send.assert_awaited_once_with(
            session,
            adapter="dsl",
            receiver="terminal",
            domain="select",
            message=user_selected_file,
        )

    async def test_global_shortcuts_invoke_history_actions(self):
        adapter = AdapterSpy()
        app = AppDinamica(adapter)

        await app.action_navigate_back()
        await app.action_navigate_forward()

        self.assertEqual(adapter.history_actions, ["back", "forward"])
        bindings = {
            binding.key: binding
            for binding in AppDinamica.BINDINGS
            if isinstance(binding, Binding)
        }
        self.assertEqual(bindings["ctrl+left"].action, "navigate_back")
        self.assertEqual(bindings["ctrl+right"].action, "navigate_forward")
        self.assertTrue(bindings["ctrl+left"].priority)
        self.assertTrue(bindings["ctrl+right"].priority)

    async def test_navigation_history_supports_back_and_forward(self):
        adapter = object.__new__(TuiAdapter)
        adapter._navigation_history = []
        adapter._navigation_index = -1
        adapter.url = "/"

        with patch.object(
            PresentationAdapter,
            "navigate_to",
            new=AsyncMock(return_value=None),
        ) as navigate:
            await adapter.navigate_to("/ide")
            self.assertEqual(adapter._navigation_history, ["/", "/ide"])
            await adapter.navigate_back()
            self.assertEqual(adapter._navigation_index, 0)
            await adapter.navigate_forward()

        self.assertEqual(adapter._navigation_index, 1)
        self.assertEqual(
            [call.args[-1] for call in navigate.await_args_list],
            ["/ide", "/", "/ide"],
        )

    def test_new_navigation_discards_forward_history(self):
        adapter = object.__new__(TuiAdapter)
        adapter._navigation_history = ["/", "/ide", "/chat"]
        adapter._navigation_index = 1

        adapter._record_navigation("/profile")

        self.assertEqual(adapter._navigation_history, ["/", "/ide", "/profile"])
        self.assertEqual(adapter._navigation_index, 2)


if __name__ == "__main__":
    unittest.main()