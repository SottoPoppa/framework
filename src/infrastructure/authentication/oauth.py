import asyncio
import time
import aiohttp

import framework.port.authentication as authentication
import framework.service.flow as flow


class Adapter(authentication.Port):
    """
    Generic OAuth2 authentication adapter.

    Supports:
        - client_credentials
        - password

    The adapter exposes:
        async def get_headers() -> dict

    so it can be plugged into a generic API adapter.
    """

    def __init__(self, **constants):
        self.name = constants.get("provider", constants.get("name", "oauth"))
        self.config = constants

        self.token_url = str(
            constants.get("token_url", "")
        ).strip()

        self.grant_type = constants.get(
            "grant_type",
            "client_credentials",
        )

        self.client_id = constants.get("client_id")
        self.client_secret = constants.get("client_secret")

        self.username = constants.get("username")
        self.password = constants.get("password")

        self.scope = constants.get("scope")

        self.client_auth = constants.get(
            "auth_style",
            constants.get(
                "client_auth",
                constants.get("token_auth_method", "basic"),
            ),
        )
        self.audience = constants.get("audience")

        self.token_field = constants.get(
            "token_field",
            "access_token",
        )

        self.expires_field = constants.get(
            "expires_field",
            "expires_in",
        )

        self.auth_header = constants.get(
            "auth_header",
            "Authorization",
        )

        self.auth_scheme = constants.get(
            "auth_scheme",
            "Bearer",
        )

        self.timeout = float(constants.get("timeout", 30))
        self.verify_ssl = self._bool(
            constants.get("verify_ssl", True)
        )

        self.extra_token_params = dict(
            constants.get("token_params", {})
        )

        self.access_token = None
        self.token_expires_at = 0
        self._token_lock = asyncio.Lock()

    @staticmethod
    def _bool(value):
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        return bool(value)

    async def _authenticate(self, username=None, password=None):
        async with self._token_lock:
            return await self._authenticate_unlocked(username, password)

    async def _authenticate_unlocked(self, username=None, password=None):
        if not self.token_url:
            raise RuntimeError(
                "OAuth token_url is not configured"
            )

        if not self.client_id:
            raise RuntimeError(
                "OAuth client_id is not configured"
            )

        if not self.client_secret:
            raise RuntimeError(
                "OAuth client_secret is not configured"
            )

        payload = {
            "grant_type": self.grant_type,
            **self.extra_token_params,
        }

        if self.scope:
            payload["scope"] = self.scope
        if self.audience:
            payload["audience"] = self.audience

        if self.grant_type == "password":
            username = username or self.username
            password = password or self.password
            if not username:
                raise RuntimeError(
                    "OAuth username is not configured"
                )

            if not password:
                raise RuntimeError(
                    "OAuth password is not configured"
                )

            payload["username"] = username
            payload["password"] = password

        auth = None

        if self.client_auth == "basic":
            auth = aiohttp.BasicAuth(
                self.client_id,
                self.client_secret,
            )

        elif self.client_auth == "body":
            payload["client_id"] = self.client_id
            payload["client_secret"] = self.client_secret

        else:
            raise RuntimeError(
                "Unsupported OAuth client_auth: "
                f"{self.client_auth}"
            )

        timeout = aiohttp.ClientTimeout(
            total=self.timeout
        )

        headers = {
            "Accept": "application/json",
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
        }

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.post(
                self.token_url,
                data=payload,
                headers=headers,
                auth=auth,
                ssl=self.verify_ssl,
            ) as response:

                content_type = response.headers.get(
                    "Content-Type",
                    "",
                )

                if "json" in content_type.lower():
                    try:
                        data = await response.json(
                            content_type=None
                        )
                    except Exception:
                        data = await response.text()
                else:
                    data = await response.text()

                if not 200 <= response.status < 300:
                    raise RuntimeError(
                        "OAuth authentication failed: "
                        f"HTTP {response.status} {data}"
                    )

                if not isinstance(data, dict):
                    raise RuntimeError(
                        "OAuth token response is not JSON"
                    )

                access_token = data.get(self.token_field)

                if not access_token:
                    raise RuntimeError(
                        "OAuth response does not contain "
                        f"{self.token_field}"
                    )

                expires_in = int(
                    data.get(self.expires_field, 3600)
                )

                # Renew one minute before expiration.
                expires_in = max(expires_in - 60, 1)

                self.access_token = access_token
                self.token_expires_at = time.monotonic() + expires_in
                return data

    async def sign_in(self, email, password):
        if self.grant_type != "password":
            return flow.error(
                "Il provider OAuth configurato non supporta il login password."
            )

        try:
            data = await self._authenticate(email, password)
        except Exception as exc:
            return flow.error(str(exc))

        tokens = {
            "access_token": str(data[self.token_field]),
            "token_type": data.get("token_type", self.auth_scheme),
            "expires_in": int(data.get(self.expires_field, 3600)),
        }
        tokens["expires_at"] = time.time() + max(
            tokens["expires_in"] - 60,
            1,
        )
        if data.get("refresh_token"):
            tokens["refresh_token"] = str(data["refresh_token"])

        return flow.success({
            "providers": {
                self.name: {
                    "tokens": tokens,
                    "user": {"email": email},
                }
            },
            "user": {"email": email},
        })

    async def sign_up(self, email, password):
        return flow.error("OAuth non supporta la registrazione tramite questo provider.")

    async def sign_out(self, session):
        session.get("providers", {}).pop(self.name, None)
        return flow.success({"session": session})

    async def sign_aid(self, **constants):
        return flow.error("OAuth non supporta questa operazione.")

    async def get_user(self, session):
        provider = session.get("providers", {}).get(self.name)
        if not provider:
            return flow.error("Utente non autenticato.")
        return flow.success(provider.get("user", {}))

    async def get_headers(self, session=None):
        if session is not None:
            provider = session.get("providers", {}).get(self.name)
            tokens = provider.get("tokens", {}) if provider else {}
            access_token = tokens.get("access_token")
            if not access_token:
                raise RuntimeError(
                    f"Token OAuth assente nella sessione per '{self.name}'."
                )
            auth_scheme = tokens.get("token_type", self.auth_scheme)
        else:
            if (
                not self.access_token
                or time.monotonic() >= self.token_expires_at
            ):
                await self._authenticate()
            access_token = self.access_token
            auth_scheme = self.auth_scheme

        return {
            self.auth_header: (
                f"{auth_scheme} {access_token}"
                if auth_scheme
                else access_token
            )
        }

    async def refresh(self):
        self.access_token = None
        self.token_expires_at = 0
        await self._authenticate()