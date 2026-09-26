import unittest
from pathlib import Path

from framework.core.interpreter import Interpreter


class PresenterSpy:
    def __init__(self):
        self.targets = []

    async def rebuild(self, session, node_id, context=None):
        self.targets.append(node_id)


class TerminalControllerSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_selection_only_updates_its_current_scope(self):
        project_root = Path(__file__).resolve().parents[1]
        source = (project_root / "src/application/controller/terminal.dsl").read_text()
        interpreter = Interpreter()
        interpreter.load("terminal", source)
        session = interpreter.open_session()
        presenter = PresenterSpy()
        session.registry.register("presenter", presenter)

        await session.run("terminal")
        selections = (
            (
                "application",
                "src/application/controller/terminal.dsl",
                "src/application/view/page/terminal.xml",
            ),
            (
                "framework",
                "src/framework/core/flow.py",
                "src/framework/manager/presenter.py",
            ),
            (
                "infrastructure",
                "src/infrastructure/presentation/tui/textual.py",
                "src/infrastructure/presentation/tui/widgets.py",
            ),
        )

        for scope, current_path, navigation_path in selections:
            previous_rebuild_count = len(presenter.targets)
            await session.dispatch_controller_event("terminal", "select", current_path)
            context = session.controller_context("terminal")

            self.assertEqual(context.get("selected"), current_path)
            self.assertIn(current_path, context.get(f"{scope}_files", ()))
            self.assertGreater(len(presenter.targets), previous_rebuild_count)
            self.assertEqual(presenter.targets[-1], "workspace-editors")

            previous_rebuild_count = len(presenter.targets)
            await session.dispatch_controller_event(
                "terminal",
                f"select_{scope}",
                navigation_path,
            )
            context = session.controller_context("terminal")

            self.assertEqual(context.get("selected"), current_path)
            self.assertEqual(context.get("selected_scope"), scope)
            self.assertEqual(context.get(f"selected_{scope}"), navigation_path)
            self.assertGreater(len(presenter.targets), previous_rebuild_count)
            self.assertEqual(presenter.targets[-1], scope)


if __name__ == "__main__":
    unittest.main()