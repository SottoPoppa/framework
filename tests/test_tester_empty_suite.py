import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from framework.core.interpreter import Interpreter
from framework.manager.tester import Manager as Tester


class EmptyTestSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_suite_is_rejected_without_recording_test_count(self):
        interpreter = Interpreter()
        await interpreter.load_file("empty-suite.test.dsl", "tuple:test_suite := ();")

        tester = object.__new__(Tester)
        tester.loader = SimpleNamespace(
            app=None,
            resource=lambda path: "",
            import_module=lambda path: None,
            get_managers=lambda: {},
        )
        log_scope = Mock()
        message = "test_suite vuota: deve contenere almeno un test valido."

        outcome = await Tester._execute_dsl(
            tester,
            interpreter,
            "empty-suite.test.dsl",
            log_scope,
            session_data={},
        )

        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["data"]["error"], message)
        self.assertNotIn("total", outcome["data"])
        log_scope.error.assert_called_once_with(message)


if __name__ == "__main__":
    unittest.main()