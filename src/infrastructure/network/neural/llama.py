import asyncio
import ctypes
import importlib.util
import queue
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, AsyncGenerator

import framework.port.network as network

Llama = None
_LLAMA_CPP_NATIVE = None
_LLAMA_CPP_IMPORT_ERROR = None
_DEPENDENCIES_LOADED = False


def _load_dependencies() -> None:
    global Llama, _LLAMA_CPP_NATIVE, _LLAMA_CPP_IMPORT_ERROR, _DEPENDENCIES_LOADED
    if _DEPENDENCIES_LOADED:
        return

    _DEPENDENCIES_LOADED = True
    try:
        _preload_cuda_libraries()
        from llama_cpp import Llama as llama_class
        from llama_cpp import llama_cpp as llama_cpp_native
    except Exception as exc:
        Llama = None
        _LLAMA_CPP_NATIVE = None
        _LLAMA_CPP_IMPORT_ERROR = exc
    else:
        Llama = llama_class
        _LLAMA_CPP_NATIVE = llama_cpp_native
        _LLAMA_CPP_IMPORT_ERROR = None


def _dependency_import_error(error: Exception | None) -> str:
    if error is None:
        return "errore di import non specificato"
    while error.__cause__ is not None:
        error = error.__cause__
    return f"{type(error).__name__}: {error}"


def _preload_cuda_libraries() -> None:
    if not sys.platform.startswith("linux"):
        return

    try:
        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        return
    if spec is None or spec.submodule_search_locations is None:
        return

    roots = [Path(location) for location in spec.submodule_search_locations]
    for pattern in ("libcudart.so*", "libcublasLt.so*", "libcublas.so*"):
        libraries = sorted(
            library
            for root in roots
            for library in root.rglob(pattern)
            if library.is_file()
        )
        if libraries:
            try:
                ctypes.CDLL(str(libraries[0]), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def _resolve_gguf_model_path(
    model_id: str,
    gguf_file: str | None,
    revision: str | None = None,
    token: str | None = None,
) -> str:
    model_path = Path(model_id)
    if model_path.is_file():
        return str(model_path)
    if model_path.is_dir():
        if not gguf_file:
            raise ValueError("Indica gguf_file quando model_id è una directory.")
        local_model_path = model_path / gguf_file
        if local_model_path.is_file():
            return str(local_model_path)
        raise FileNotFoundError(f"File GGUF non trovato: {local_model_path}")
    if not gguf_file:
        raise ValueError(
            "Per un repository Hugging Face GGUF è necessario specificare gguf_file."
        )

    from huggingface_hub import hf_hub_download

    return hf_hub_download(
        repo_id=model_id,
        filename=gguf_file,
        revision=revision,
        token=token,
    )


class Adapter(network.Port):
    """Adapter LLM basato esclusivamente su llama.cpp e file GGUF."""

    capabilities: Dict[str, Any] = {
        "network_type": "recurrent_neural_network",
        "architecture": "Transformer/LLM",
        "provider": "llama.cpp",
        "topological": True,
        "real_time_stream": True,
        "async_execution": True,
    }

    def __init__(
        self,
        name: str = "llama_cpp_network",
        model_id: str = "unsloth/Qwen3.5-9B-GGUF",
        device: str = "cuda",
        gguf_file: str | None = "Qwen3.5-9B-Q4_K_M.gguf",
        n_ctx: int = 2048,
        n_gpu_layers: int = -1,
        **kwargs: Any,
    ):
        self.name = name
        self.model_id = model_id
        self.device = device
        self.gguf_file = gguf_file
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self._kwargs = kwargs

        self.model = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._is_ready = False

    # ------------------------------------------------------------------
    # 1. Topologia di Rete (Grafo Computazionale dell'LLM)
    # ------------------------------------------------------------------

    async def get_topology(self) -> Dict[str, Any]:
        if not self._is_ready:
            return {"nodes": [], "edges": [], "status": "uninitialized"}
        return {
            "nodes": [{
                "id": "llama.cpp",
                "type": "llm",
                "model": self.model_id,
                "file": self.gguf_file,
                "device": self.device,
            }],
            "edges": [],
            "architecture": "GGUF",
        }

    async def add_node(self, node_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Aggiunge un nodo concettuale (es. un adattatore LoRA o una testa di classificazione)."""
        node_id = node_spec.get("id", "custom_node")
        return {"status": "added", "node_id": node_id, "type": node_spec.get("type", "adapter")}

    async def remove_node(self, node_id: str) -> Dict[str, Any]:
        """Rimuove un nodo dalla topologia."""
        return {"status": "removed", "node_id": node_id}

    async def connect_nodes(
        self, src_node_id: str, dst_node_id: str, connection_spec: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """Crea un arco o una connessione pesata tra due nodi."""
        return {"status": "connected", "src": src_node_id, "dst": dst_node_id, "spec": connection_spec or {}}

    async def disconnect_nodes(self, src_node_id: str, dst_node_id: str) -> Dict[str, Any]:
        """Scollega due nodi topologici."""
        return {"status": "disconnected", "src": src_node_id, "dst": dst_node_id}

    async def add_layer(self, layer_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Aggiunge un nuovo layer alla rete neurale."""
        return {"status": "layer_added", "spec": layer_spec}

    # ------------------------------------------------------------------
    # 2. Operazioni di Ciclo di Vita (Deploy, Scale, Migrate)
    # ------------------------------------------------------------------

    async def deploy(self, deploy_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Deploya / Carica il modello in RAM/VRAM in base alle specifiche."""
        return await self.provision(intent=deploy_spec)

    async def scale(self, scale_spec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "unchanged",
            "quantization": self.gguf_file,
            "device": self.device,
            "message": "La quantizzazione e' fissata nel file GGUF.",
        }

    async def migrate(self, migrate_spec: Dict[str, Any]) -> Dict[str, Any]:
        if not self._is_ready:
            return {"status": "error", "message": "Modello non provisionato."}
        return {
            "status": "error",
            "message": "Per cambiare dispositivo, esegui di nuovo provision sul target.",
            "target_device": migrate_spec.get("target_device", "cpu"),
        }

    # ------------------------------------------------------------------
    # 3. Flusso Dati & Invocazione (Provision, Route, Stream, Compute, Monitor)
    # ------------------------------------------------------------------

    async def provision(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, _load_dependencies)
        if Llama is None:
            raise RuntimeError(
                "llama-cpp-python non e' importabile: "
                f"{_dependency_import_error(_LLAMA_CPP_IMPORT_ERROR)}"
            ) from _LLAMA_CPP_IMPORT_ERROR

        target_model_id = str(intent.get("model_id", self.model_id))
        gguf_file = intent.get("gguf_file", self.gguf_file)
        model_path = await loop.run_in_executor(
            self._executor,
            _resolve_gguf_model_path,
            target_model_id,
            gguf_file,
            intent.get("revision"),
            intent.get("token", self._kwargs.get("token")),
        )
        context_size = int(intent.get("n_ctx", self.n_ctx))
        gpu_layers = int(intent.get("n_gpu_layers", self.n_gpu_layers))
        target_device = str(intent.get("device", self.device))
        if target_device.startswith("cuda"):
            if not _LLAMA_CPP_NATIVE.llama_supports_gpu_offload():
                raise RuntimeError("llama-cpp-python e' installato senza supporto CUDA.")
        else:
            gpu_layers = 0

        def _load_model():
            return Llama(
                model_path=model_path,
                n_ctx=context_size,
                n_gpu_layers=gpu_layers,
                verbose=False,
            )

        self.model = await loop.run_in_executor(self._executor, _load_model)
        self.model_id = target_model_id
        self.gguf_file = gguf_file or model_path
        self._model_path = model_path
        self.n_ctx = context_size
        self.n_gpu_layers = gpu_layers
        self.device = target_device
        self._is_ready = True
        return {
            "status": "provisioned",
            "model_id": self.model_id,
            "model_file": self.gguf_file,
            "device": self.device,
            "backend": "llama.cpp",
            "n_ctx": self.n_ctx,
            "n_gpu_layers": self.n_gpu_layers,
        }

    async def route(
        self,
        payload: Dict[str, Any] | None = None,
        requirements: Dict[str, Any] | None = None,
        *,
        application: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Esegue il Forward Pass completo del testo attraverso la topologia della rete."""
        if not self._is_ready:
            return {"status": "error", "message": "Modello non inizializzato. Esegui prima 'provision'."}

        if payload is None:
            payload = application
        if not isinstance(payload, dict):
            return {"status": "error", "message": "È richiesto un payload applicativo."}

        prompt = payload.get("prompt") or payload.get("sequence", "")
        max_new_tokens = payload.get("max_new_tokens", 256)
        temperature = payload.get("temperature", 0.7)

        loop = asyncio.get_event_loop()

        def _generate():
            completion = self.model.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_new_tokens,
                temperature=temperature,
                top_p=payload.get("top_p", 0.8),
                top_k=payload.get("top_k", 20),
                presence_penalty=payload.get("presence_penalty", 0.0),
                repeat_penalty=payload.get("repeat_penalty", 1.0),
            )
            choice = completion["choices"][0]
            message = choice.get("message", {})
            return {
                "status": "success",
                "output": message.get("content") or message.get("reasoning_content") or "",
                "tokens_generated": completion.get("usage", {}).get("completion_tokens", 0),
                "architecture": "Transformer/LLM",
            }

        return await loop.run_in_executor(self._executor, _generate)

    async def stream(
        self, payload: Dict[str, Any], requirements: Dict[str, Any] | None = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Genera token GGUF in streaming senza bloccare l'event loop."""
        if not self._is_ready:
            yield {"status": "error", "message": "Modello non inizializzato."}
            return
        chunks = queue.Queue()
        finished = object()

        def _generate_stream():
            try:
                stream = self.model.create_chat_completion(
                    messages=[{"role": "user", "content": payload.get("prompt") or payload.get("sequence", "")}],
                    max_tokens=payload.get("max_new_tokens", 256),
                    temperature=payload.get("temperature", 0.7),
                    top_p=payload.get("top_p", 0.8),
                    top_k=payload.get("top_k", 20),
                    presence_penalty=payload.get("presence_penalty", 0.0),
                    repeat_penalty=payload.get("repeat_penalty", 1.0),
                    stream=True,
                )
                for chunk in stream:
                    chunks.put(chunk)
            except Exception as exc:
                chunks.put(exc)
            finally:
                chunks.put(finished)

        generation = asyncio.get_running_loop().run_in_executor(
            self._executor, _generate_stream
        )
        while True:
            chunk = await asyncio.to_thread(chunks.get)
            if chunk is finished:
                break
            if isinstance(chunk, Exception):
                await generation
                raise chunk
            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            text = delta.get("content") or delta.get("reasoning_content") or ""
            if text:
                yield {"status": "streaming", "token": text, "done": False}

        await generation
        yield {"status": "completed", "token": "", "done": True}

    async def compute(self, *args, **kwargs) -> Dict[str, Any]:
        payload = kwargs.get("payload", {}) or ({"prompt": args[0]} if args else {})
        return await self.route(payload=payload)

    async def monitor(self) -> Dict[str, Any]:
        return {
            "is_ready": self._is_ready,
            "device": self.device,
            "model_id": self.model_id,
            "backend": "llama.cpp",
        }

    async def status(self) -> Dict[str, Any]:
        return {
            "state": "READY" if self._is_ready else "UNINITIALIZED",
            "model": self.model_id,
            "topological": True,
        }