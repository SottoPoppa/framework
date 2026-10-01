import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import framework.core.flow as flow
from framework.manager.networker import Manager as Networker
import infrastructure.network.neural.llm as llm_module
from infrastructure.network.neural.llm import Adapter


class FakeLlama:
    def __init__(self, delay=0, stream_error=False, **kwargs):
        self.kwargs = kwargs
        self.delay = delay
        self.stream_error = stream_error

    def create_chat_completion(self, messages, **kwargs):
        if kwargs.get("stream"):
            def generate_chunks():
                if self.stream_error:
                    raise RuntimeError("stream failed")
                if self.delay:
                    time.sleep(self.delay)
                yield {"choices": [{"delta": {"content": "risposta "}}]}
                yield {"choices": [{"delta": {"content": "GGUF"}}]}

            return generate_chunks()
        return {
            "choices": [{"message": {"content": "risposta GGUF"}}],
            "usage": {"completion_tokens": 2},
        }


class LLMAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_importing_adapter_does_not_load_llama_cpp(self):
        self.assertFalse(llm_module._DEPENDENCIES_LOADED)
        self.assertIsNone(llm_module.Llama)

    async def test_gguf_backend_provisions_routes_and_streams(self):
        instances = []

        class FakeLlama:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                instances.append(self)

            def create_chat_completion(self, messages, **kwargs):
                if kwargs.get("stream"):
                    return iter([
                        {"choices": [{"delta": {"content": "risposta "}}]},
                        {"choices": [{"delta": {"content": "GGUF"}}]},
                    ])
                return {
                    "choices": [{"message": {"content": "risposta GGUF"}}],
                    "usage": {"completion_tokens": 2},
                }

        adapter = Adapter(
            model_id="unsloth/Qwen3.5-9B-GGUF",
            device="cuda",
            gguf_file="Qwen3.5-9B-Q4_K_M.gguf",
            n_ctx=1024,
            n_gpu_layers=-1,
        )
        fake_native = SimpleNamespace(llama_supports_gpu_offload=lambda: True)

        try:
            with (
                patch.object(llm_module, "_load_dependencies"),
                patch.object(llm_module, "_resolve_gguf_model_path", return_value="/cache/model.gguf"),
                patch.object(llm_module, "Llama", FakeLlama),
                patch.object(llm_module, "_LLAMA_CPP_NATIVE", fake_native),
            ):
                provision = await adapter.provision({})
                self.assertTrue(flow.check(provision), flow.output(provision))
                self.assertEqual(flow.output(provision)["backend"], "llama.cpp")
                self.assertEqual(instances[0].kwargs["n_ctx"], 1024)
                self.assertEqual(instances[0].kwargs["n_gpu_layers"], -1)

                response = await adapter.route({"prompt": "ciao", "max_new_tokens": 4})
                self.assertTrue(flow.check(response), flow.output(response))
                self.assertEqual(flow.output(response)["output"], "risposta GGUF")
                self.assertEqual(flow.output(response)["tokens_generated"], 2)

                chunks = [
                    chunk
                    async for chunk in adapter.stream(
                        {"prompt": "ciao", "max_new_tokens": 4}
                    )
                ]
                self.assertEqual(chunks[0]["token"], "risposta ")
                self.assertTrue(chunks[-1]["done"])
        finally:
            adapter._executor.shutdown(wait=True)

    async def test_networker_routes_prompt_to_provisioned_llm(self):
        adapter = Adapter(device="cpu")
        adapter._is_ready = True
        adapter.model = FakeLlama()
        framework = SimpleNamespace(get_logger=lambda _name: Mock())
        networker = Networker([adapter], None, framework)

        try:
            result = await networker.route(
                object(),
                application={"prompt": "ciao"},
                requirements={"network_type": "recurrent_neural_network"},
            )

            self.assertTrue(flow.check(result), flow.output(result))
            self.assertEqual(flow.output(result)["output"], "risposta GGUF")
        finally:
            adapter._executor.shutdown(wait=True)

    async def test_stream_does_not_block_the_event_loop(self):
        adapter = Adapter(device="cpu")
        adapter._is_ready = True
        adapter.model = FakeLlama(delay=0.1)

        async def collect():
            return [chunk async for chunk in adapter.stream({"prompt": "ciao"})]

        try:
            started = asyncio.get_running_loop().time()
            stream_task = asyncio.create_task(collect())
            await asyncio.sleep(0)
            await asyncio.sleep(0.01)
            elapsed = asyncio.get_running_loop().time() - started
            chunks = await stream_task

            self.assertLess(elapsed, 0.05)
            self.assertEqual(chunks[0]["token"], "risposta ")
            self.assertTrue(chunks[-1]["done"])
        finally:
            adapter._executor.shutdown(wait=True)

    async def test_stream_propagates_generation_failure_without_hanging(self):
        adapter = Adapter(device="cpu")
        adapter._is_ready = True
        adapter.model = FakeLlama(stream_error=True)

        try:
            with self.assertRaisesRegex(RuntimeError, "stream failed"):
                await asyncio.wait_for(
                    self._collect_stream(adapter),
                    timeout=1,
                )
        finally:
            adapter._executor.shutdown(wait=True)

    async def _collect_stream(self, adapter):
        return [chunk async for chunk in adapter.stream({"prompt": "ciao"})]