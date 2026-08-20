import asyncio
import time
from typing import Any

import aiohttp

from infrastructure.persistence.api import Adapter as APIAdapter


class Adapter(APIAdapter):
    """API adapter autenticato con OAuth2 client credentials."""

    def __init__(self, **constants: Any):
        super().__init__(**constants)
        self.token_url = (
            constants.get("token_url")
            or constants.get("oauth2_token_url")
            or ""
        )
        self.client_id = constants.get("client_id")
        self.client_secret = constants.get("client_secret")
        self.scope = constants.get("scope")
        self.audience = constants.get("audience")
        self.auth_style = constants.get("auth_style", "basic")
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    def _token_is_valid(self) -> bool:
        return bool(self.token) and time.monotonic() < self._token_expires_at

    def _token_payload(self) -> dict[str, str]:
        payload = {"grant_type": "client_credentials"}
        if self.scope:
            payload["scope"] = str(self.scope)
        if self.audience:
            payload["audience"] = str(self.audience)
        if self.auth_style == "body":
            payload["client_id"] = str(self.client_id or "")
            payload["client_secret"] = str(self.client_secret or "")
        return payload

    async def _get_token(self) -> str:
        if not self.token_url:
            raise ValueError("OAuth2 token_url non configurato")
        if not self.client_id or not self.client_secret:
            raise ValueError("OAuth2 client_id e client_secret sono obbligatori")

        request_kwargs: dict[str, Any] = {
            "data": self._token_payload(),
            "timeout": aiohttp.ClientTimeout(total=self.timeout),
        }
        if self.auth_style == "basic":
            request_kwargs["auth"] = aiohttp.BasicAuth(
                str(self.client_id),
                str(self.client_secret),
            )
        elif self.auth_style != "body":
            raise ValueError("OAuth2 auth_style deve essere 'basic' o 'body'")

        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, **request_kwargs) as response:
                content_type = response.headers.get("Content-Type", "")
                data = (
                    await response.json(content_type=None)
                    if "json" in content_type.lower()
                    else await response.text()
                )
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(
                        f"OAuth2 token request failed ({response.status}): {data}"
                    )
                if not isinstance(data, dict) or not data.get("access_token"):
                    raise ValueError("Risposta OAuth2 senza access_token")

                expires_in = float(data.get("expires_in", 3600))
                self.token = str(data["access_token"])
                self._token_expires_at = time.monotonic() + max(
                    expires_in - 30,
                    0,
                )
                return self.token

    async def _ensure_token(self) -> str:
        if self._token_is_valid():
            return str(self.token)
        async with self._token_lock:
            if not self._token_is_valid():
                await self._get_token()
        return str(self.token)

    async def request(self, session=None, storekeeper=None, **constants):
        await self._ensure_token()
        return await super().request(
            session=session,
            storekeeper=storekeeper,
            **constants,
        )
