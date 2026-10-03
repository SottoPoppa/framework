import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import framework.core.flow as flow
from infrastructure.actuation.audio.voice import Adapter as VoiceAdapter
from infrastructure.actuation.function.framework import Adapter as FunctionAdapter


class ActuationPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_state_and_feature_accept_manager_arguments(self):
        adapter = VoiceAdapter(announce_start=False)
        session = object()

        state_result = await adapter.set_state(session, {"ready": True})
        self.assertTrue(flow.is_result(state_result))
        self.assertIsNone(flow.unwrap(state_result))

        state = flow.unwrap(await adapter.get_state(session))
        self.assertTrue(state["ready"])

        toggle_result = await adapter.toggle_feature(session, "speech", False)
        self.assertTrue(flow.is_result(toggle_result))
        self.assertFalse(flow.unwrap(toggle_result))

        legacy_toggle_result = await adapter.toggle_feature(
            feature="speech",
            enabled=True,
        )
        self.assertTrue(flow.unwrap(legacy_toggle_result))

    async def test_function_adapter_applies_positional_state_and_feature(self):
        adapter = FunctionAdapter()
        session = object()
        requested_state = {"ready": True}

        state_result = await adapter.set_state(session, requested_state)
        self.assertEqual(
            flow.unwrap(state_result),
            {"status": "updated", "state": requested_state},
        )

        feature_result = await adapter.toggle_feature(
            session,
            "speech",
            False,
        )
        self.assertEqual(
            flow.unwrap(feature_result),
            {"feature": "speech", "enabled": False},
        )