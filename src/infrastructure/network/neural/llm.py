import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, AsyncGenerator

import framework.core.flow as flow
import framework.port.network as network

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
except ImportError:
    torch = None
    AutoModelForCausalLM = None
    AutoTokenizer = None
    TextIteratorStreamer = None


class Adapter(network.Port):
    """Adapter topologico per LLM / Reti Recorrenti su Hugging Face.
    
    Implementa la porta astratta `network.Port` mappando l'architettura
    del Transformer su nodi, layer e connessioni topologiche.
    """

    capabilities: Dict[str, Any] = {
        "network_type": "recurrent_neural_network",
        "architecture": "Transformer/LLM",
        "provider": "huggingface",
        "topological": True,
        "real_time_stream": True,
        "async_execution": True,
    }

    def __init__(
        self,
        name = "hf_llm_network",
        model_id = "Qwen/Qwen2.5-1.5B-Instruct",
        device = "cuda",
        load_in_8bit = False,
        **kwargs
    ):
        self.name = name
        self.model_id = model_id
        self.device = device if (torch and torch.cuda.is_available()) else "cpu"
        self.load_in_8bit = load_in_8bit
        self._kwargs = kwargs

        self.tokenizer = None
        self.model = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._is_ready = False

    # ------------------------------------------------------------------
    # 1. Topologia di Rete (Grafo Computazionale dell'LLM)
    # ------------------------------------------------------------------

    async def get_topology(self) -> Dict[str, Any]:
        """Estrae la topologia interna del Transformer in forma di Grafo G = (V, E)."""
        if not self._is_ready or self.model is None:
            return {"nodes": [], "edges": [], "status": "uninitialized"}

        nodes = [
            {"id": "input_tokens", "type": "input", "label": "Token Embedding Layer"},
        ]
        edges = []

        # Estrazione topologica dei Layer (Attention & FeedForward Blocks)
        try:
            # Trova la lista dei blocchi Transformer principali (es. model.layers o model.h)
            model_core = getattr(self.model, "model", self.model)
            layers = getattr(model_core, "layers", getattr(model_core, "h", []))
            
            prev_node = "input_tokens"
            for idx, layer in enumerate(layers):
                node_id = f"transformer_layer_{idx}"
                nodes.append({
                    "id": node_id,
                    "type": "neural_layer",
                    "class": layer.__class__.__name__,
                    "device": str(next(layer.parameters()).device) if list(layer.parameters()) else self.device
                })
                edges.append({"src": prev_node, "dst": node_id, "type": "residual_connection"})
                prev_node = node_id

            # Nodo di Output
            nodes.append({"id": "lm_head", "type": "output", "label": "Language Model Output Head"})
            edges.append({"src": prev_node, "dst": "lm_head", "type": "logits_projection"})

        except Exception as e:
            nodes.append({"id": "model_core", "type": "blackbox", "error": str(e)})

        return {"nodes": nodes, "edges": edges, "architecture": self.model.__class__.__name__}

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
        """Scala la risorsa applicando quantizzazione o modificando il contesto libero."""
        target_quant = scale_spec.get("quantization")
        if target_quant == "8bit":
            self.load_in_8bit = True
        return {"status": "scaled", "quantization": target_quant, "device": self.device}

    async def migrate(self, migrate_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Migra i tensori del modello tra hardware diversi (es. CPU -> CUDA / GPU -> CPU)."""
        new_device = migrate_spec.get("target_device", "cpu")
        if self.model and torch:
            loop = asyncio.get_event_loop()
            def _move():
                self.model.to(new_device)
                self.device = new_device
            await loop.run_in_executor(self._executor, _move)
            return {"status": "migrated", "from_device": self.device, "to_device": new_device}
        return {"status": "error", "message": "Modello non pronto per la migrazione"}

    # ------------------------------------------------------------------
    # 3. Flusso Dati & Invocazione (Provision, Route, Stream, Compute, Monitor)
    # ------------------------------------------------------------------

    @flow.result(inputs=("intent",), outputs=("deployment",))
    async def provision(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        """Carica il Tokenizer e i Pesi del modello da Hugging Face."""
        if AutoModelForCausalLM is None:
            raise RuntimeError("Installa le dipendenze: 'pip install transformers torch'")

        target_model_id = intent.get("model_id", self.model_id)
        loop = asyncio.get_event_loop()

        def _load():
            self.tokenizer = AutoTokenizer.from_pretrained(target_model_id)
            kwargs = {"torch_dtype": torch.float16 if self.device == "cuda" else torch.float32}
            if self.load_in_8bit and self.device == "cuda":
                kwargs["load_in_8bit"] = True

            self.model = AutoModelForCausalLM.from_pretrained(
                target_model_id,
                device_map="auto" if self.device == "cuda" else None,
                **kwargs
            )
            if self.device != "cuda":
                self.model.to(self.device)

            self._is_ready = True
            return target_model_id

        loaded_id = await loop.run_in_executor(self._executor, _load)
        return {
            "status": "provisioned",
            "model_id": loaded_id,
            "device": self.device,
            "vocab_size": getattr(self.tokenizer, "vocab_size", None),
        }

    @flow.result(
        inputs=("payload", "requirements"),
        outputs=("route",),
    )
    async def route(
        self,
        payload: Dict[str, Any],
        requirements: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Esegue il Forward Pass completo del testo attraverso la topologia della rete."""
        if not self._is_ready:
            return {"status": "error", "message": "Modello non inizializzato. Esegui prima 'provision'."}

        prompt = payload.get("prompt") or payload.get("sequence", "")
        max_new_tokens = payload.get("max_new_tokens", 256)
        temperature = payload.get("temperature", 0.7)

        loop = asyncio.get_event_loop()

        def _generate():
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature if temperature > 0 else 1.0,
                    do_sample=True if temperature > 0 else False,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            generated_tokens = outputs[0][inputs.input_ids.shape[-1]:]
            output_text = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)
            return output_text, len(generated_tokens)

        output_text, tokens_generated = await loop.run_in_executor(self._executor, _generate)
        return {
            "status": "success",
            "output": output_text,
            "tokens_generated": tokens_generated,
            "architecture": "Transformer/LLM",
        }

    async def stream(
        self, payload: Dict[str, Any], requirements: Dict[str, Any] | None = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Genera e invia i token in tempo reale sequenzialmente tramite streamer."""
        if not self._is_ready:
            yield {"status": "error", "message": "Modello non inizializzato."}
            return

        prompt = payload.get("prompt") or payload.get("sequence", "")
        max_new_tokens = payload.get("max_new_tokens", 256)
        
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        
        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=max_new_tokens,
            pad_token_id=self.tokenizer.eos_token_id,
        )

        # Avvia la generazione in un thread separato per consentire lo streaming asincrono
        loop = asyncio.get_event_loop()
        loop.run_in_executor(self._executor, lambda: self.model.generate(**generation_kwargs))

        for new_text in streamer:
            yield {"status": "streaming", "token": new_text, "done": False}
        
        yield {"status": "completed", "token": "", "done": True}

    async def compute(self, *args, **kwargs) -> Dict[str, Any]:
        """Invocazione diretta di calcolo/inferenza batch."""
        payload = kwargs.get("payload", {}) or ({"prompt": args[0]} if args else {})
        return await self.route(payload=payload)

    @flow.result(outputs=("status",))
    async def monitor(self) -> Dict[str, Any]:
        """Monitoraggio telemetrico della VRAM e dello stato topologico."""
        metrics = {
            "is_ready": self._is_ready,
            "device": self.device,
            "model_id": self.model_id,
        }
        if torch and torch.cuda.is_available() and self.device == "cuda":
            metrics["vram_allocated_mb"] = torch.cuda.memory_allocated() / (1024 ** 2)
            metrics["vram_reserved_mb"] = torch.cuda.memory_reserved() / (1024 ** 2)
        return metrics

    @flow.result(outputs=("status",))
    async def status(self) -> Dict[str, Any]:
        return {
            "state": "READY" if self._is_ready else "UNINITIALIZED",
            "model": self.model_id,
            "topological": True,
        }