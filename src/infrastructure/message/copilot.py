import asyncio
import inspect
import os
from collections import defaultdict
from typing import Any

import framework.core.flow as flow
import framework.port.message as message


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
        self._sessions: dict[str, Any] = {}
        self._queues: defaultdict[tuple[str, str], asyncio.Queue[Any]] = defaultdict(
            asyncio.Queue
        )
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
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
        copilot_session = await self._get_session(session_id, client)
        prompt = constants.get("message", constants.get("prompt"))
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Copilot message must be a non-empty string")

        task = asyncio.create_task(
            self._receive_response(
                copilot_session,
                session_id,
                prompt,
                self._queue_domain(constants.get("domain")),
            )
        )
        self._response_tasks.add(task)
        task.add_done_callback(self._response_tasks.discard)

    async def _receive_response(
        self,
        session: Any,
        session_id: str,
        prompt: str,
        domain: str,
    ) -> None:
        async with self._response_locks[session_id]:
            try:
                response = await session.send_and_wait(
                    {"prompt": prompt},
                    timeout=self.config.get("timeout", 120.0),
                )
                content = self._response_content(response)
            except Exception as exc:
                flow._dev_log("copilot.response.error type=%s error=%r", type(exc).__name__, exc)
                content = f"Copilot error: {exc}"
        if content is not None:
            item = {
                "domain": domain,
                "message": content,
                "session_id": session_id,
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
        options = {
            "github_token": token,
            "cwd": self.config.get("working_directory"),
        }
        self._client = CopilotClient(options)
        return self._client

    def _github_token(self) -> str | None:
        configured = self.config.get("token", self.config.get("github_token"))
        if not isinstance(configured, str):
            return configured
        if configured.startswith("{{env.") and configured.endswith("}}"):
            return os.environ.get(configured[6:-2])
        return configured or None

    async def _get_session(self, session_id: str, client: Any) -> Any:
        if session_id in self._sessions:
            return self._sessions[session_id]
        async with self._locks[session_id]:
            if session_id in self._sessions:
                return self._sessions[session_id]
            start = getattr(client, "start", None)
            if start is not None:
                result = start()
                if inspect.isawaitable(result):
                    await result
            create_session = getattr(client, "create_session")
            kwargs: dict[str, Any] = {
                "model": self.config.get("model", "auto"),
                "streaming": False,
                "system_message": {
                    "mode": "append",
                    "content": (
                        "All workspace and terminal changes must be performed "
                        "through the OmniPort terminal tool."
                    ),
                },
            }
            tools = self._terminal_tools()
            if tools:
                kwargs["tools"] = tools
            if self.config.get("available_tools") is not None:
                kwargs["available_tools"] = self.config["available_tools"]
            session = create_session(config=kwargs)
            if inspect.isawaitable(session):
                session = await session
            self._sessions[session_id] = session
            return session

    def _terminal_tools(self) -> list[Any]:
        executor = self.config.get("terminal_executor")
        if not self.config.get("enable_terminal", False) or executor is None:
            return []
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
            result = executor(command, arguments.get("working_directory"))
            if inspect.isawaitable(result):
                result = await result
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
            is_terminal=True,
        )]

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
        return str(getattr(session, "id", None) or fallback or "default")

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