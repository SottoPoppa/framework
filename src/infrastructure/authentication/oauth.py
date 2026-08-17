import time
import aiohttp

import framework.port.persistence as persistence


class Adapter(persistence.Port):
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
            "client_auth",
            constants.get("token_auth_method", "basic"),
        )

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

    async def _authenticate(self):
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

        if self.grant_type == "password":
            if not self.username:
                raise RuntimeError(
                    "OAuth username is not configured"
                )

            if not self.password:
                raise RuntimeError(
                    "OAuth password is not configured"
                )

            payload["username"] = self.username
            payload["password"] = self.password

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
                self.token_expires_at = (
                    time.time() + expires_in
                )

    async def get_headers(self):
        if (
            not self.access_token
            or time.time() >= self.token_expires_at
        ):
            await self._authenticate()

        return {
            self.auth_header: (
                f"{self.auth_scheme} {self.access_token}"
                if self.auth_scheme
                else self.access_token
            )
        }

    async def refresh(self):
        self.access_token = None
        self.token_expires_at = 0
        await self._authenticate()