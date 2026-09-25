import asyncio
import unittest
from types import SimpleNamespace

from infrastructure.message.stub import Adapter


class MessageStubTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_waits_until_a_message_is_posted(self):
        adapter = Adapter()
        session = SimpleNamespace(id="stub-reader")
        read_task = asyncio.create_task(adapter.read(session, domain="chat"))

        try:
            await asyncio.sleep(0)
            self.assertFalse(read_task.done())
            await adapter.post(domain="chat", message="pong")
            result = await asyncio.wait_for(read_task, timeout=1)
        finally:
            if not read_task.done():
                read_task.cancel()

        self.assertTrue(result.is_success)
        self.assertEqual(len(adapter.messages), 1)
        self.assertEqual(result.output.value["message"], "pong")
        self.assertEqual(result.output.value["domain"], "chat")