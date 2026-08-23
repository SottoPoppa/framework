import asyncio
import base64
import hashlib
import secrets
import time
import aiohttp
import jwt
from urllib.parse import urlencode

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
        self.authorization_endpoint = str(
            constants.get("authorization_endpoint", "")
        ).strip()
        self.revoke_url = str(constants.get("revoke_url", "")).strip()
        self.redirect_uri = constants.get("redirect_uri")
        self.jwks_url = constants.get("jwks_url")
        self.jwt_secret = constants.get("jwt_secret")
        self.jwt_algorithms = constants.get("jwt_algorithms", ["HS256"])
        if isinstance(self.jwt_algorithms, str):
            self.jwt_algorithms = [self.jwt_algorithms]
        self.jwt_issuer = constants.get("jwt_issuer")
        self.jwt_audience = constants.get("jwt_audience")

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
        self._pending_states = {}

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

        return await self._request_token(payload, auth=auth)

    async def _request_token(self, payload, auth=None):
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.token_url,
                data=payload,
                headers=headers,
                auth=auth,
                ssl=self.verify_ssl,
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                if "json" in content_type.lower():
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        data = await response.text()
                else:
                    data = await response.text()
                if not 200 <= response.status < 300:
                    raise RuntimeError(
                        f"OAuth token request failed: HTTP {response.status} {data}"
                    )
                if not isinstance(data, dict):
                    raise RuntimeError("OAuth token response is not JSON")
                access_token = data.get(self.token_field)
                if not access_token:
                    raise RuntimeError(
                        f"OAuth response does not contain {self.token_field}"
                    )
                expires_in = int(data.get(self.expires_field, 3600))
                self.access_token = str(access_token)
                self.token_expires_at = time.monotonic() + max(expires_in - 60, 1)
                return data

    def _client_auth(self, payload):
        if self.client_auth == "basic":
            return aiohttp.BasicAuth(self.client_id, self.client_secret)
        if self.client_auth == "body":
            payload.update({
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            })
            return None
        raise RuntimeError(f"Unsupported OAuth client_auth: {self.client_auth}")

    @staticmethod
    def _pkce_challenge(code_verifier):
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    async def authorization_url(self, state=None, code_verifier=None, **kwargs):
        if not self.authorization_endpoint:
            return flow.error("OAuth authorization_endpoint is not configured")
        state = state or secrets.token_urlsafe(32)
        code_verifier = code_verifier or secrets.token_urlsafe(64)
        self._pending_states[state] = code_verifier
        code_challenge = self._pkce_challenge(code_verifier)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if self.scope:
            params["scope"] = self.scope
        params.update({key: value for key, value in kwargs.items() if value is not None})
        params = {key: value for key, value in params.items() if value is not None}
        return flow.success({
            "url": f"{self.authorization_endpoint}?{urlencode(params)}",
            "state": state,
            "code_verifier": code_verifier,
            "code_challenge": code_challenge,
        })

    async def exchange_code(self, code, code_verifier, state=None):
        if state is not None:
            expected_verifier = self._pending_states.pop(state, None)
            if expected_verifier is None or expected_verifier != code_verifier:
                return flow.error("OAuth state or PKCE verifier is invalid")
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
        }
        if self.redirect_uri:
            payload["redirect_uri"] = self.redirect_uri
        try:
            data = await self._request_token(payload, auth=self._client_auth(payload))
            return flow.success(self._token_payload(data))
        except Exception as exc:
            return flow.error(str(exc))

    async def callback(self, params):
        if params.get("error"):
            return flow.error(params.get("error_description", params["error"]))
        if not params.get("state"):
            return flow.error("OAuth state is missing")
        return await self.exchange_code(
            params.get("code"),
            self._pending_states.get(params.get("state"), ""),
            params.get("state"),
        )

    def _token_payload(self, data):
        expires_in = int(data.get(self.expires_field, 3600))
        tokens = {
            "access_token": str(data[self.token_field]),
            "token_type": data.get("token_type", self.auth_scheme),
            "auth_header": self.auth_header,
            "expires_in": expires_in,
            "expires_at": time.time() + max(expires_in - 60, 1),
        }
        if data.get("refresh_token"):
            tokens["refresh_token"] = str(data["refresh_token"])
        return {"providers": {self.name: {"tokens": tokens}}}

    @staticmethod
    def token_expired(tokens):
        if not tokens or not tokens.get("access_token"):
            return True
        expires_at = tokens.get("expires_at")
        return expires_at is not None and float(expires_at) <= time.time()

    async def refresh(self, refresh_token=None, session=None):
        if session is not None:
            refresh_token = session.get("providers", {}).get(self.name, {}).get("tokens", {}).get("refresh_token")
        if not refresh_token:
            return flow.error("OAuth refresh_token is not available")
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        try:
            data = await self._request_token(payload, auth=self._client_auth(payload))
            result = self._token_payload(data)
            if session is not None:
                session.setdefault("providers", {})[self.name] = result["providers"][self.name]
            return flow.success(result)
        except Exception as exc:
            return flow.error(str(exc))

    async def revoke(self, token=None, token_type="access_token"):
        if not self.revoke_url:
            return flow.error("OAuth revoke_url is not configured")
        if not token:
            token = self.access_token
        if not token:
            return flow.error("OAuth token is not available")
        payload = {"token": token, "token_type_hint": token_type}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(self.revoke_url, data=payload, ssl=self.verify_ssl) as response:
                    if not 200 <= response.status < 300:
                        raise RuntimeError(f"OAuth revocation failed: HTTP {response.status}")
            if token == self.access_token:
                self.access_token = None
                self.token_expires_at = 0
            return flow.success(True)
        except Exception as exc:
            return flow.error(str(exc))

    async def validate_token(self, token):
        if not token:
            return flow.error("OAuth access_token is not available")
        try:
            options = {"verify_exp": True}
            kwargs = {}
            if self.jwt_issuer:
                kwargs["issuer"] = self.jwt_issuer
            if self.jwt_audience:
                kwargs["audience"] = self.jwt_audience
            if self.jwt_secret:
                claims = jwt.decode(token, self.jwt_secret, algorithms=self.jwt_algorithms, options=options, **kwargs)
            elif self.jwks_url:
                signing_key = jwt.PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token)
                claims = jwt.decode(token, signing_key.key, algorithms=self.jwt_algorithms, options=options, **kwargs)
            else:
                return flow.error("JWT validation key or jwks_url is not configured")
            return flow.success(claims)
        except Exception as exc:
            return flow.error(f"Invalid OAuth JWT: {exc}")

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
            "auth_header": self.auth_header,
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
            if self.token_expired(tokens):
                raise RuntimeError(
                    f"Token OAuth scaduto nella sessione per '{self.name}'."
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
