import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import framework.core.flow as flow
from framework.core.runner import DagRunner
from framework.core.session import NodeState


class RunnerSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_source_result_fails_without_publishing_or_triggering_event(self):
        runner = DagRunner()
        source_node = SimpleNamespace(
            action=object(),
            metadata={"on_event": "handle_message"},
        )
        dag = SimpleNamespace(
            nodes={"source": source_node, "handle_message": object()},
            get=Mock(return_value=source_node),
        )
        session = SimpleNamespace(
            id="source-test",
            context=object(),
            errors={},
            mark=Mock(),
        )
        runner.evaluator = SimpleNamespace(evaluate=AsyncMock(return_value=None))
        runner._publish = Mock()
        runner._bind_event = Mock()
        runner._run_node = AsyncMock()

        await runner._run_source(dag, session, "source")

        runner.evaluator.evaluate.assert_awaited_once()
        self.assertIsInstance(session.errors["source"], ValueError)
        self.assertEqual(session.mark.call_args.args, ("source", NodeState.FAILED))
        runner._publish.assert_not_called()
        runner._bind_event.assert_not_called()
        runner._run_node.assert_not_awaited()

    async def test_failed_source_result_stops_without_republishing(self):
        runner = DagRunner()
        source_node = SimpleNamespace(
            action=object(),
            metadata={"on_event": "handle_message"},
        )
        dag = SimpleNamespace(
            nodes={"source": source_node, "handle_message": object()},
            get=Mock(return_value=source_node),
        )
        session = SimpleNamespace(
            id="source-error-test",
            context=object(),
            errors={},
            mark=Mock(),
        )
        failed_result = flow.error("No provider available")
        runner.evaluator = SimpleNamespace(
            evaluate=AsyncMock(return_value=failed_result)
        )
        runner._publish = Mock()
        runner._bind_event = Mock()
        runner._run_node = AsyncMock()

        await runner._run_source(dag, session, "source")

        runner.evaluator.evaluate.assert_awaited_once()
        self.assertIs(session.errors["source"], failed_result)
        self.assertEqual(session.mark.call_args.args, ("source", NodeState.FAILED))
        runner._publish.assert_not_called()
        runner._bind_event.assert_not_called()
        runner._run_node.assert_not_awaited()