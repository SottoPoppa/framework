import asyncio
import inspect
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import framework.core.flow as flow
import framework.port.message as message


# Alias comodi per i nomi "corti" -> id modello Copilot reale.
# Gli id esatti dei modelli su GitHub Copilot cambiano nel tempo (nuovi
# rilasci, ritiri, rinominazioni), quindi questa mappa è solo una comodità
# per errori di battitura / nomi colloquiali, NON una fonte di verità.
# Se un modello continua a non caricarsi, verifica l'id esatto restituito
# da GET https://api.githubcopilot.com/models oppure dal model picker
# dell'editor (VS Code / Copilot CLI / ecc.).
MODEL_ALIASES: dict[str, str] = {
    "luna": "gpt-5.6-luna",
    "gpt-luna": "gpt-5.6-luna",
    "gpt luna": "gpt-5.6-luna",
    "terra": "gpt-5.6-terra",
    "gpt-terra": "gpt-5.6-terra",
    "sol": "gpt-5.6-sol",
    "gpt-sol": "gpt-5.6-sol",
    "gpt-5.6": "gpt-5.6-sol",
}


class Adapter(message.Port):
    """Message adapter backed by the official GitHub Copilot SDK."""

    capabilities = {
        "tls": True,
        "encryption": True,
        "audit": True,
        "rate_limiting": False,
        "authentication": ["github-copilot"],
    }

    def __init__(self, **constants: Any) -> None:
        self.adapter = "copilot"
        self.config = constants
        self.name = constants.get("name", "copilot")
        self.processable = {"post", "read", "event"}
        self._client = constants.get("client")
        # Le sessioni ora sono cache-ate per (session_id, model): così
        # cambiare modello per la stessa conversazione apre una sessione
        # Copilot nuova, invece di restare bloccati sul modello con cui la
        # sessione era stata aperta la prima volta.
        self._sessions: dict[tuple[str, str], Any] = {}
        self._queues: defaultdict[tuple[str, str], asyncio.Queue[Any]] = defaultdict(
            asyncio.Queue
        )
        self._locks: defaultdict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._response_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._response_tasks: set[asyncio.Task[Any]] = set()

    def loader(self, config: dict[str, Any]) -> None:
        self.config.update(config)
        self.name = self.config.get("name", self.name)

    async def can(self, identity: str, action: str) -> bool:
        if action not in self.processable:
            return False
        if action == "post":
            return (
                self._client is not None
                or self.config.get("client_factory") is not None
                or self._github_token() is not None
            )
        return True

    async def post(self, session: Any, *services: Any, **constants: Any) -> None:
        client = await self._get_client()
        if client is None:
            raise RuntimeError("Copilot adapter requires an injected client or github-copilot-sdk")

        session_id = self._session_id(session, constants.get("session_id"))
        # Il modello si può passare per-chiamata (constants["model"]),
        # altrimenti si usa quello configurato sull'adapter, altrimenti "auto".
        model = self._resolve_model(constants.get("model"))
        copilot_session = await self._get_session(session_id, model, client)
        prompt = constants.get("message", constants.get("prompt"))
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Copilot message must be a non-empty string")

        await self._receive_response(
            copilot_session,
            session_id,
            model,
            prompt,
            self._queue_domain(constants.get("domain")),
        )

    async def _receive_response(
        self,
        session: Any,
        session_id: str,
        model: str,
        prompt: str,
        domain: str,
    ) -> None:
        async with self._response_locks[session_id]:
            try:
                # send_and_wait vuole il prompt come stringa semplice, non
                # incapsulato in un dict.
                response = await session.send_and_wait(
                    prompt,
                    timeout=self.config.get("timeout", 120.0),
                )
                content = self._response_content(response)
            except Exception as exc:
                flow._dev_log(
                    "copilot.response.error model=%s type=%s error=%r",
                    model,
                    type(exc).__name__,
                    exc,
                )
                content = self._friendly_error(model, exc)
        if content is not None:
            item = {
                "domain": domain,
                "message": content,
                "session_id": session_id,
                "model": model,
            }
            await self._queues[(session_id, self._queue_domain(domain))].put(item)
            if domain != "*":
                await self._queues[(session_id, "*")].put(item)

    async def read(self, session: Any, *services: Any, **constants: Any) -> Any:
        pattern = constants.get("domain") or "general"
        session_id = self._session_id(session)
        normalized_pattern = self._queue_domain(pattern)
        queue = self._queues[(session_id, normalized_pattern)]
        if self.config.get("test_mode") and queue.empty():
            return None
        while True:
            item = await queue.get()
            if self._matches(pattern, item.get("domain", "general")):
                return item

    async def close(self) -> None:
        for task in self._response_tasks:
            task.cancel()
        if self._response_tasks:
            await asyncio.gather(*self._response_tasks, return_exceptions=True)
        self._response_tasks.clear()
        self._queues.clear()
        for session in list(self._sessions.values()):
            disconnect = getattr(session, "disconnect", None)
            if disconnect is not None:
                result = disconnect()
                if inspect.isawaitable(result):
                    await result
        self._sessions.clear()
        if self._client is not None:
            stop = getattr(self._client, "stop", None)
            if stop is not None:
                result = stop()
                if inspect.isawaitable(result):
                    await result

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        factory = self.config.get("client_factory")
        if factory is not None:
            self._client = factory()
            if inspect.isawaitable(self._client):
                self._client = await self._client
            return self._client
        token = self._github_token()
        if token is None:
            raise RuntimeError(
                "Copilot SDK requires COPILOT_GITHUB_TOKEN or an injected client"
            )
        try:
            from copilot import CopilotClient
        except ImportError:
            return None
        # CopilotClient.__init__ nella SDK reale (github-copilot-sdk) è
        # keyword-only: niente dict posizionale, e il parametro si chiama
        # "working_directory", non "cwd".
        self._client = CopilotClient(
            github_token=token,
            working_directory=self.config.get("working_directory"),
        )
        return self._client

    def _github_token(self) -> str | None:
        configured = self.config.get("token", self.config.get("github_token"))
        if not isinstance(configured, str):
            return configured
        if configured.startswith("{{env.") and configured.endswith("}}"):
            return os.environ.get(configured[6:-2])
        return configured or None

    def _resolve_model(self, override: Any = None) -> str:
        """Risolve l'id modello da richiedere, espandendo alias e variabili
        d'ambiente. Precedenza: override per-chiamata > config adapter > "auto".
        """
        raw = override if isinstance(override, str) and override.strip() else self.config.get("model", "auto")
        if not isinstance(raw, str):
            return "auto"
        raw = raw.strip()
        if raw.startswith("{{env.") and raw.endswith("}}"):
            raw = os.environ.get(raw[6:-2], "auto")
        return MODEL_ALIASES.get(raw.lower().strip(), raw)

    async def _get_session(self, session_id: str, model: str, client: Any) -> Any:
        cache_key = (session_id, model)
        if cache_key in self._sessions:
            return self._sessions[cache_key]
        async with self._locks[cache_key]:
            if cache_key in self._sessions:
                return self._sessions[cache_key]
            start = getattr(client, "start", None)
            if start is not None:
                result = start()
                if inspect.isawaitable(result):
                    await result
            # Controllo proattivo: la SDK reale espone client.list_models(),
            # con lo stato di policy di ogni modello ("enabled"/"disabled"/
            # "unconfigured"). Se il modello richiesto non è abilitato per
            # l'account/org, meglio fallire qui con un messaggio chiaro che
            # dentro un TypeError/RPC error criptico da create_session.
            await self._check_model_policy(client, model)
            create_session = getattr(client, "create_session", None)
            if create_session is None:
                raise RuntimeError(
                    "Injected Copilot client is missing create_session(); "
                    "check the client/client_factory you provided to the adapter"
                )
            # create_session nella SDK reale è keyword-only con parametri
            # individuali (model, streaming, system_message, tools,
            # available_tools, ...): NON accetta un unico dict "config=".
            kwargs: dict[str, Any] = {
                "model": model,
                "streaming": False,
                "system_message": {
                    "mode": "append",
                    "content": (
                        "You are an implementation agent, not a consultant. "
                        "You MUST use the omniport_terminal tool to inspect and "
                        "modify the workspace. Do not only describe a solution. "
                        "Start by running pwd and reading SKILL.md, then inspect "
                        "the relevant files, implement the requested task, run "
                        "tests, and fix failures before reporting completion. "
                        "All workspace and terminal changes must be performed "
                        "through the OmniPort terminal tool."
                    ),
                },
            }
            tools = self._terminal_tools()
            try:
                from copilot.session import PermissionHandler
            except ImportError:
                PermissionHandler = None
            if PermissionHandler is not None:
                kwargs["on_permission_request"] = PermissionHandler.approve_all
            flow._dev_log(
                "copilot.session.tools terminal_enabled=%s tool_count=%s",
                self.config.get("enable_terminal", False),
                len(tools),
            )
            if tools:
                kwargs["tools"] = tools
            if self.config.get("available_tools") is not None:
                kwargs["available_tools"] = self.config["available_tools"]
            try:
                session = create_session(**kwargs)
                if inspect.isawaitable(session):
                    session = await session
            except Exception as exc:
                flow._dev_log(
                    "copilot.session.create_error model=%s error=%r", model, exc
                )
                raise RuntimeError(
                    f"Failed to open a Copilot session for model {model!r}: {exc}. "
                    "If this is a newly released model, confirm (1) the id matches "
                    "exactly what client.list_models() reports, and (2) it's enabled "
                    "in your Copilot Business/Enterprise admin policy (new models "
                    "default to off)."
                ) from exc
            self._sessions[cache_key] = session
            return session

    async def _check_model_policy(self, client: Any, model: str) -> None:
        """Verifica (best-effort) che `model` sia abilitato per l'account/org
        prima di provare ad aprire la sessione, usando client.list_models().
        Non fallisce mai per errori di rete/permessi su list_models stesso:
        in quel caso lascia che sia create_session a dare l'errore reale.
        """
        list_models = getattr(client, "list_models", None)
        if list_models is None:
            return
        try:
            models = await list_models()
        except Exception as exc:
            flow._dev_log("copilot.list_models.warn model=%s error=%r", model, exc)
            return
        info = next((m for m in models if getattr(m, "id", None) == model), None)
        if info is None:
            # Id non trovato nella lista corrente: potrebbe essere un modello
            # nuovo non ancora propagato, o un typo. Non blocchiamo qui,
            # ce lo dirà create_session con un errore più specifico.
            return
        policy = getattr(info, "policy", None)
        state = getattr(policy, "state", None) if policy is not None else None
        if state in ("disabled", "unconfigured"):
            raise RuntimeError(
                f"Model {model!r} risulta {state!r} per questo account/organizzazione "
                "(da client.list_models()). Un admin Copilot Business/Enterprise deve "
                "abilitarlo in Copilot Settings > Models prima che sia utilizzabile."
            )

    def _terminal_tools(self) -> list[Any]:
        if not self.config.get("enable_terminal", False):
            return []
        executor = self.config.get("terminal_executor") or self._default_terminal_executor
        try:
            from copilot.tools import Tool, ToolInvocation, ToolResult
        except ImportError:
            raise RuntimeError("Terminal tools require github-copilot-sdk") from None

        async def execute(invocation: ToolInvocation) -> ToolResult:
            arguments = invocation.arguments or {}
            command = arguments.get("command")
            if not isinstance(command, str) or not command.strip():
                return ToolResult(
                    text_result_for_llm="command is required",
                    result_type="failure",
                    error="command is required",
                )
            flow._dev_log(
                "copilot.terminal.start command=%s working_directory=%s",
                command,
                arguments.get("working_directory"),
            )
            result = executor(command, arguments.get("working_directory"))
            if inspect.isawaitable(result):
                result = await result
            flow._dev_log(
                "copilot.terminal.end command=%s result=%s",
                command,
                result,
            )
            return ToolResult(text_result_for_llm=str(result), result_type="success")

        return [Tool(
            name="omniport_terminal",
            description="Execute one approved command through the OmniPort terminal.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "working_directory": {"type": "string"},
                },
                "required": ["command"],
            },
            handler=execute,
        )]

    async def _default_terminal_executor(
        self,
        command: str,
        working_directory: str | None = None,
    ) -> str:
        root = Path(self.config.get("working_directory") or os.getcwd()).resolve()
        requested = Path(working_directory or root).expanduser()
        if not requested.is_absolute():
            requested = root / requested
        cwd = requested.resolve()
        if cwd != root and root not in cwd.parents:
            return "terminal rejected: working directory is outside the workspace"

        blocked = (
            "sudo ", "rm -rf", "git reset --hard", "git clean -fd",
            "mkfs", "shutdown", "reboot", ":(){", "> /dev/",
        )
        normalized = command.casefold()
        if any(token in normalized for token in blocked):
            return "terminal rejected: command is not permitted"

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=os.environ.copy(),
            )
            output, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=float(self.config.get("terminal_timeout", 120.0)),
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return "terminal failed: command timed out"
        except OSError as error:
            return f"terminal failed: {error}"

        text = output.decode("utf-8", errors="replace")
        if process.returncode:
            return f"exit code {process.returncode}\n{text}"
        return text or "command completed successfully"

    @staticmethod
    def _friendly_error(model: str, exc: Exception) -> str:
        text = str(exc).lower()
        if "not accessible" in text or "not supported" in text or "model_not_supported" in text:
            return (
                f"Copilot error: model {model!r} non è ancora richiedibile da questa "
                "interfaccia (alcuni modelli appena rilasciati funzionano solo via "
                "endpoint /responses, non /chat/completions). Riprova più tardi o "
                "usa un altro modello."
            )
        if "policy" in text or "not enabled" in text or "forbidden" in text or "403" in text:
            return (
                f"Copilot error: il modello {model!r} risulta disabilitato per "
                "questo account/organizzazione. Un admin Copilot Business/Enterprise "
                "deve abilitarlo nelle impostazioni Copilot (i modelli nuovi sono "
                "disattivati di default)."
            )
        return f"Copilot error: {exc}"

    @staticmethod
    def _matches(pattern: str, domain: str) -> bool:
        if pattern == "*":
            return True
        return pattern == domain

    @staticmethod
    def _queue_domain(domain: Any) -> str:
        return domain.strip() if isinstance(domain, str) and domain.strip() else "general"

    @staticmethod
    def _session_id(session: Any, fallback: Any = None) -> str:
        # L'oggetto CopilotSession reale espone .session_id, non .id.
        # Teniamo .id come fallback per compatibilità con mock/test doubles.
        return str(
            getattr(session, "session_id", None)
            or getattr(session, "id", None)
            or fallback
            or "default"
        )

    @staticmethod
    def _response_content(response: Any) -> str | None:
        if response is None:
            return None

        def find_content(value: Any, depth: int = 0) -> Any:
            if value is None or depth > 3:
                return None
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                for key in ("content", "message", "reply", "text"):
                    if key in value and value[key] is not None:
                        found = find_content(value[key], depth + 1)
                        if found is not None:
                            return found
                return None
            for key in ("content", "message", "reply", "text", "data"):
                nested = getattr(value, key, None)
                if nested is not None:
                    found = find_content(nested, depth + 1)
                    if found is not None:
                        return found
            return None

        content = find_content(response)
        return str(content) if content is not None else None