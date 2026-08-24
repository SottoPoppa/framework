from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

import framework.port.authentication as authentication
import framework.service.flow as flow


class Adapter(authentication.Port):
    """
    Generic OAuth2 authentication adapter.

    Supporta:

        - authorization_code
        - authorization_code + PKCE
        - refresh_token
        - password
        - client_credentials

    Il token può essere:

        1. mantenuto internamente per integrazioni machine-to-machine

        oppure

        2. salvato nella sessione dell'utente.

    Per integrazioni utente -> GLPI è consigliato:

        authorization_code + PKCE

    Esempio:

        auth = Adapter(
            provider="glpi",

            authorization_endpoint=(
                "https://glpi.example.com/"
                "api.php/v2.3/authorize"
            ),

            token_url=(
                "https://glpi.example.com/"
                "api.php/v2.3/token"
            ),

            client_id="...",
            client_secret="...",

            redirect_uri=(
                "https://app.example.com/"
                "auth/glpi/callback"
            ),

            grant_type="authorization_code",

            scope="api",

            auth_style="basic",
        )

    Il risultato di authorization_url():

        {
            "url": "...",
            "state": "...",
            "code_verifier": "...",
            "code_challenge": "..."
        }

    Il risultato di exchange_code():

        {
            "providers": {
                "glpi": {
                    "tokens": {
                        "access_token": "...",
                        "refresh_token": "...",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "expires_at": ...
                    }
                }
            }
        }

    La sessione utente può quindi contenere:

        {
            "providers": {
                "glpi": {
                    "tokens": {
                        ...
                    }
                }
            }
        }

    E il GLPI API adapter può semplicemente fare:

        headers = await auth.get_headers(session)

    ottenendo:

        {
            "Authorization": "Bearer ..."
        }
    """

    # ==================================================================
    # INIT
    # ==================================================================

    def __init__(self, **constants: Any):

        self.name = constants.get(
            "provider",
            constants.get(
                "name",
                "oauth",
            ),
        )

        self.config = dict(constants)

        # --------------------------------------------------------------
        # OAuth endpoints
        # --------------------------------------------------------------

        self.token_url = str(
            constants.get(
                "token_url",
                "",
            )
            or ""
        ).strip()

        self.authorization_endpoint = str(
            constants.get(
                "authorization_endpoint",
                "",
            )
            or ""
        ).strip()

        self.revoke_url = str(
            constants.get(
                "revoke_url",
                "",
            )
            or ""
        ).strip()

        self.redirect_uri = constants.get(
            "redirect_uri"
        )

        # --------------------------------------------------------------
        # OAuth client
        # --------------------------------------------------------------

        self.client_id = constants.get(
            "client_id"
        )

        self.client_secret = constants.get(
            "client_secret"
        )

        self.grant_type = str(
            constants.get(
                "grant_type",
                "client_credentials",
            )
            or "client_credentials"
        ).strip().lower()

        self.scope = constants.get(
            "scope"
        )

        self.audience = constants.get(
            "audience"
        )

        # --------------------------------------------------------------
        # Password grant
        # --------------------------------------------------------------

        self.username = constants.get(
            "username"
        )

        self.password = constants.get(
            "password"
        )

        # --------------------------------------------------------------
        # OAuth client authentication
        #
        # basic:
        #
        # Authorization: Basic ...
        #
        # body:
        #
        # client_id=...
        # client_secret=...
        #
        # none:
        #
        # public PKCE client
        # --------------------------------------------------------------

        self.client_auth = str(
            constants.get(
                "auth_style",
                constants.get(
                    "client_auth",
                    constants.get(
                        "token_auth_method",
                        "basic",
                    ),
                ),
            )
            or "basic"
        ).strip().lower()

        # --------------------------------------------------------------
        # Token response
        # --------------------------------------------------------------

        self.token_field = constants.get(
            "token_field",
            "access_token",
        )

        self.expires_field = constants.get(
            "expires_field",
            "expires_in",
        )

        self.refresh_token_field = constants.get(
            "refresh_token_field",
            "refresh_token",
        )

        self.token_type_field = constants.get(
            "token_type_field",
            "token_type",
        )

        # --------------------------------------------------------------
        # Authentication header
        # --------------------------------------------------------------

        self.auth_header = constants.get(
            "auth_header",
            "Authorization",
        )

        self.auth_scheme = constants.get(
            "auth_scheme",
            "Bearer",
        )

        # --------------------------------------------------------------
        # HTTP
        # --------------------------------------------------------------

        self.timeout = float(
            constants.get(
                "timeout",
                30,
            )
        )

        self.verify_ssl = self._bool(
            constants.get(
                "verify_ssl",
                True,
            )
        )

        # --------------------------------------------------------------
        # Token request parameters
        # --------------------------------------------------------------

        self.extra_token_params = dict(
            constants.get(
                "token_params",
                {},
            )
            or {}
        )

        # --------------------------------------------------------------
        # Runtime token
        #
        # Usato solo quando l'adapter viene usato senza sessione.
        #
        # Per utenti reali è preferibile session.
        # --------------------------------------------------------------

        self.access_token: str | None = None

        self.refresh_token_value: str | None = None

        self.token_type: str = (
            self.auth_scheme
        )

        self.token_expires_at: float = 0.0

        # --------------------------------------------------------------
        # OAuth synchronization
        # --------------------------------------------------------------

        self._token_lock = asyncio.Lock()

        # --------------------------------------------------------------
        # Pending PKCE
        #
        # Compatibilità con applicazioni single-process.
        #
        # In produzione è preferibile salvare
        # state/code_verifier nel session store.
        # --------------------------------------------------------------

        self._pending_states: dict[
            str,
            str,
        ] = {}

    # ==================================================================
    # BOOLEAN
    # ==================================================================

    @staticmethod
    def _bool(
        value: Any,
    ) -> bool:

        if isinstance(
            value,
            bool,
        ):
            return value

        if isinstance(
            value,
            str,
        ):
            return (
                value.strip().lower()
                in {
                    "true",
                    "1",
                    "yes",
                    "on",
                }
            )

        return bool(value)

    # ==================================================================
    # PKCE
    # ==================================================================

    @staticmethod
    def _pkce_challenge(
        code_verifier: str,
    ) -> str:

        digest = hashlib.sha256(
            code_verifier.encode(
                "ascii"
            )
        ).digest()

        return (
            base64.urlsafe_b64encode(
                digest
            )
            .rstrip(b"=")
            .decode("ascii")
        )

    # ==================================================================
    # CLIENT AUTH
    # ==================================================================

    def _client_auth(
        self,
        payload: dict[str, Any],
    ):

        if self.client_auth == "basic":

            if not self.client_id:
                raise RuntimeError(
                    "OAuth client_id is required"
                )

            if not self.client_secret:
                raise RuntimeError(
                    "OAuth client_secret is required "
                    "when auth_style=basic"
                )

            return aiohttp.BasicAuth(
                str(self.client_id),
                str(self.client_secret),
            )

        if self.client_auth == "body":

            if not self.client_id:
                raise RuntimeError(
                    "OAuth client_id is required"
                )

            if not self.client_secret:
                raise RuntimeError(
                    "OAuth client_secret is required "
                    "when auth_style=body"
                )

            payload.update(
                {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }
            )

            return None

        if self.client_auth in {
            "none",
            "public",
        }:

            if self.client_id:
                payload.setdefault(
                    "client_id",
                    self.client_id,
                )

            return None

        raise RuntimeError(
            "Unsupported OAuth auth_style: "
            f"{self.client_auth}"
        )

    # ==================================================================
    # TOKEN REQUEST
    # ==================================================================

    async def _request_token(
        self,
        payload: dict[str, Any],
        auth=None,
    ) -> dict[str, Any]:

        if not self.token_url:
            raise RuntimeError(
                "OAuth token_url is not configured"
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
        ) as http:

            try:

                async with http.post(
                    self.token_url,
                    data=payload,
                    headers=headers,
                    auth=auth,
                    ssl=self.verify_ssl,
                ) as response:

                    data = (
                        await self._read_response(
                            response
                        )
                    )

                    if not (
                        200
                        <= response.status
                        < 300
                    ):

                        raise RuntimeError(
                            "OAuth token request failed: "
                            f"HTTP {response.status} "
                            f"{data}"
                        )

                    if not isinstance(
                        data,
                        dict,
                    ):

                        raise RuntimeError(
                            "OAuth token response "
                            "is not JSON"
                        )

                    access_token = data.get(
                        self.token_field
                    )

                    if not access_token:

                        raise RuntimeError(
                            "OAuth response does not "
                            f"contain {self.token_field}"
                        )

                    return data

            except aiohttp.ClientError as exc:

                raise RuntimeError(
                    "OAuth token connection error: "
                    f"{exc}"
                ) from exc

            except asyncio.TimeoutError as exc:

                raise RuntimeError(
                    "OAuth token request timeout"
                ) from exc

    # ==================================================================
    # RESPONSE
    # ==================================================================

    async def _read_response(
        self,
        response: aiohttp.ClientResponse,
    ) -> Any:

        content_type = (
            response.headers.get(
                "Content-Type",
                "",
            )
            or ""
        ).lower()

        if "json" in content_type:

            try:

                return await response.json(
                    content_type=None
                )

            except Exception:
                pass

        text = await response.text()

        if not text:
            return None

        return text

    # ==================================================================
    # AUTHENTICATE
    # ==================================================================

    async def _authenticate(
        self,
        username=None,
        password=None,
    ):

        async with self._token_lock:

            return await (
                self._authenticate_unlocked(
                    username,
                    password,
                )
            )

    # ==================================================================
    # AUTHENTICATE UNLOCKED
    # ==================================================================

    async def _authenticate_unlocked(
        self,
        username=None,
        password=None,
    ):

        if not self.token_url:
            raise RuntimeError(
                "OAuth token_url is not configured"
            )

        if (
            self.grant_type
            in {
                "authorization_code",
                "password",
                "client_credentials",
            }
            and not self.client_id
        ):

            raise RuntimeError(
                "OAuth client_id is not configured"
            )

        payload = {
            "grant_type": self.grant_type,
            **self.extra_token_params,
        }

        if self.scope:
            payload["scope"] = self.scope

        if self.audience:
            payload["audience"] = self.audience

        # --------------------------------------------------------------
        # Password
        # --------------------------------------------------------------

        if self.grant_type == "password":

            username = (
                username
                or self.username
            )

            password = (
                password
                or self.password
            )

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

        # --------------------------------------------------------------
        # Client credentials
        # --------------------------------------------------------------

        elif (
            self.grant_type
            == "client_credentials"
        ):

            pass

        # --------------------------------------------------------------
        # Authorization code
        # --------------------------------------------------------------

        elif (
            self.grant_type
            == "authorization_code"
        ):

            raise RuntimeError(
                "authorization_code requires "
                "exchange_code()"
            )

        else:

            raise RuntimeError(
                "Unsupported OAuth grant_type: "
                f"{self.grant_type}"
            )

        auth = self._client_auth(
            payload
        )

        data = await self._request_token(
            payload,
            auth=auth,
        )

        self._store_runtime_token(
            data
        )

        return data

    # ==================================================================
    # RUNTIME TOKEN
    # ==================================================================

    def _store_runtime_token(
        self,
        data: dict[str, Any],
    ):

        access_token = data.get(
            self.token_field
        )

        if not access_token:
            raise RuntimeError(
                "OAuth access token is missing"
            )

        expires_in = int(
            data.get(
                self.expires_field,
                3600,
            )
            or 3600
        )

        token_type = str(
            data.get(
                self.token_type_field,
                self.auth_scheme,
            )
            or self.auth_scheme
        )

        self.access_token = str(
            access_token
        )

        self.token_type = token_type

        refresh_token = data.get(
            self.refresh_token_field
        )

        if refresh_token:

            self.refresh_token_value = (
                str(refresh_token)
            )

        self.token_expires_at = (
            time.monotonic()
            + max(
                expires_in - 60,
                1,
            )
        )

    # ==================================================================
    # AUTHORIZATION URL
    # ==================================================================

    async def authorization_url(
        self,
        state=None,
        code_verifier=None,
        **kwargs,
    ):

        if not self.authorization_endpoint:

            return flow.error(
                "OAuth authorization_endpoint "
                "is not configured"
            )

        if not self.client_id:

            return flow.error(
                "OAuth client_id is not configured"
            )

        if not self.redirect_uri:

            return flow.error(
                "OAuth redirect_uri is not configured"
            )

        state = (
            state
            or secrets.token_urlsafe(32)
        )

        code_verifier = (
            code_verifier
            or secrets.token_urlsafe(64)
        )

        code_challenge = (
            self._pkce_challenge(
                code_verifier
            )
        )

        self._pending_states[
            state
        ] = code_verifier

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

        if self.audience:

            params["audience"] = self.audience

        params.update(
            {
                key: value
                for key, value in kwargs.items()
                if value is not None
            }
        )

        params = {
            key: value
            for key, value in params.items()
            if value is not None
        }

        url = (
            f"{self.authorization_endpoint}"
            f"?{urlencode(params)}"
        )

        return flow.success(
            {
                "url": url,
                "state": state,
                "code_verifier": code_verifier,
                "code_challenge": code_challenge,
            }
        )

    # ==================================================================
    # EXCHANGE CODE
    # ==================================================================

    async def exchange_code(
        self,
        code,
        code_verifier,
        state=None,
        *,
        session=None,
    ):

        if not code:

            return flow.error(
                "OAuth authorization code is missing"
            )

        if not code_verifier:

            return flow.error(
                "OAuth PKCE code_verifier is missing"
            )

        # --------------------------------------------------------------
        # Validate state
        # --------------------------------------------------------------

        if state is not None:

            expected_verifier = (
                self._pending_states.pop(
                    state,
                    None,
                )
            )

            if (
                expected_verifier is not None
                and expected_verifier
                != code_verifier
            ):

                return flow.error(
                    "OAuth state or PKCE "
                    "verifier is invalid"
                )

        payload = {
            "grant_type": (
                "authorization_code"
            ),
            "code": code,
            "code_verifier": code_verifier,
        }

        if self.client_id:

            payload[
                "client_id"
            ] = self.client_id

        if self.redirect_uri:

            payload[
                "redirect_uri"
            ] = self.redirect_uri

        try:

            auth = self._client_auth(
                payload
            )

            data = await self._request_token(
                payload,
                auth=auth,
            )

            result = self._token_payload(
                data
            )

            if session is not None:

                self._store_session_tokens(
                    session,
                    result["providers"][
                        self.name
                    ]["tokens"],
                )

            else:

                self._store_runtime_token(
                    data
                )

            return flow.success(
                result
            )

        except Exception as exc:

            return flow.error(
                str(exc)
            )

    # ==================================================================
    # CALLBACK
    # ==================================================================

    async def callback(
        self,
        params,
        *,
        session=None,
        code_verifier=None,
    ):

        params = params or {}

        if params.get("error"):

            return flow.error(
                params.get(
                    "error_description",
                    params["error"],
                )
            )

        state = params.get(
            "state"
        )

        if not state:

            return flow.error(
                "OAuth state is missing"
            )

        code = params.get(
            "code"
        )

        if not code:

            return flow.error(
                "OAuth authorization code "
                "is missing"
            )

        # --------------------------------------------------------------
        # PKCE verifier
        #
        # Prefer session/server-side storage.
        # Fallback to in-memory state store.
        # --------------------------------------------------------------

        if not code_verifier:

            code_verifier = (
                self._get_pending_verifier(
                    state,
                    session,
                )
            )

        if not code_verifier:

            return flow.error(
                "OAuth PKCE code_verifier "
                "is missing"
            )

        return await self.exchange_code(
            code=code,
            code_verifier=code_verifier,
            state=state,
            session=session,
        )

    # ==================================================================
    # PENDING VERIFIER
    # ==================================================================

    def _get_pending_verifier(
        self,
        state,
        session=None,
    ):

        # --------------------------------------------------------------
        # Session first
        # --------------------------------------------------------------

        if session is not None:

            oauth_state = session.get(
                "_oauth",
                {},
            )

            provider_state = (
                oauth_state.get(
                    self.name,
                    {},
                )
            )

            verifier = provider_state.get(
                "code_verifier"
            )

            if verifier:

                return verifier

        # --------------------------------------------------------------
        # Memory fallback
        # --------------------------------------------------------------

        return self._pending_states.get(
            state
        )

    # ==================================================================
    # TOKEN PAYLOAD
    # ==================================================================

    def _token_payload(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        access_token = data.get(
            self.token_field
        )

        if not access_token:

            raise RuntimeError(
                "OAuth token response does not "
                f"contain {self.token_field}"
            )

        expires_in = int(
            data.get(
                self.expires_field,
                3600,
            )
            or 3600
        )

        token_type = data.get(
            self.token_type_field,
            self.auth_scheme,
        )

        tokens = {
            "access_token": str(
                access_token
            ),
            "token_type": str(
                token_type
                or self.auth_scheme
            ),
            "auth_header": self.auth_header,
            "expires_in": expires_in,
            "expires_at": (
                time.time()
                + max(
                    expires_in - 60,
                    1,
                )
            ),
        }

        refresh_token = data.get(
            self.refresh_token_field
        )

        if refresh_token:

            tokens[
                "refresh_token"
            ] = str(refresh_token)

        return {
            "providers": {
                self.name: {
                    "tokens": tokens,
                }
            }
        }

    # ==================================================================
    # STORE SESSION TOKENS
    # ==================================================================

    def _store_session_tokens(
        self,
        session,
        tokens,
    ):

        provider = (
            session.setdefault(
                "providers",
                {},
            )
            .setdefault(
                self.name,
                {},
            )
        )

        provider[
            "tokens"
        ] = dict(tokens)

    # ==================================================================
    # TOKEN EXPIRATION
    # ==================================================================

    @staticmethod
    def token_expired(
        tokens,
    ) -> bool:

        if not tokens:

            return True

        access_token = tokens.get(
            "access_token"
        )

        if not access_token:

            return True

        expires_at = tokens.get(
            "expires_at"
        )

        if expires_at is None:

            return False

        try:

            return (
                float(expires_at)
                <= time.time()
            )

        except (
            TypeError,
            ValueError,
        ):

            return True

    # ==================================================================
    # REFRESH
    # ==================================================================

    async def refresh(
        self,
        refresh_token=None,
        session=None,
    ):

        if session is not None:

            provider = (
                session
                .get("providers", {})
                .get(self.name)
            )

            if provider:

                tokens = provider.get(
                    "tokens",
                    {},
                )

                refresh_token = (
                    refresh_token
                    or tokens.get(
                        "refresh_token"
                    )
                )

        refresh_token = (
            refresh_token
            or self.refresh_token_value
        )

        if not refresh_token:

            return flow.error(
                "OAuth refresh_token "
                "is not available"
            )

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        if self.client_id:

            payload[
                "client_id"
            ] = self.client_id

        try:

            auth = self._client_auth(
                payload
            )

            data = await self._request_token(
                payload,
                auth=auth,
            )

            result = self._token_payload(
                data
            )

            if session is not None:

                self._store_session_tokens(
                    session,
                    result["providers"][
                        self.name
                    ]["tokens"],
                )

            else:

                self._store_runtime_token(
                    data
                )

            return flow.success(
                result
            )

        except Exception as exc:

            return flow.error(
                str(exc)
            )

    # ==================================================================
    # GET HEADERS
    # ==================================================================

    async def get_headers(
        self,
        session=None,
    ):

        # ==============================================================
        # USER SESSION
        # ==============================================================

        if session is not None:

            provider = (
                session
                .get("providers", {})
                .get(self.name)
            )

            if not provider:

                raise RuntimeError(
                    "OAuth provider "
                    f"'{self.name}' is not connected"
                )

            tokens = provider.get(
                "tokens",
                {},
            )

            access_token = tokens.get(
                "access_token"
            )

            if not access_token:

                raise RuntimeError(
                    "OAuth access_token is missing "
                    f"for provider '{self.name}'"
                )

            # ----------------------------------------------------------
            # Token ancora valido
            # ----------------------------------------------------------

            if not self.token_expired(
                tokens
            ):

                token_type = tokens.get(
                    "token_type",
                    self.auth_scheme,
                )

                return {
                    self.auth_header: (
                        f"{token_type} "
                        f"{access_token}"
                        if token_type
                        else access_token
                    )
                }

            # ----------------------------------------------------------
            # Token scaduto
            # ----------------------------------------------------------

            refresh_token = tokens.get(
                "refresh_token"
            )

            if not refresh_token:

                raise RuntimeError(
                    "OAuth access_token expired "
                    "and refresh_token is not available"
                )

            # ----------------------------------------------------------
            # Refresh
            # ----------------------------------------------------------

            result = await self.refresh(
                refresh_token=refresh_token,
                session=session,
            )

            if result is None:

                raise RuntimeError(
                    "OAuth token refresh failed"
                )

            # ----------------------------------------------------------
            # Recupera token aggiornato
            # ----------------------------------------------------------

            provider = (
                session
                .get("providers", {})
                .get(self.name)
            )

            tokens = provider.get(
                "tokens",
                {},
            )

            access_token = tokens.get(
                "access_token"
            )

            if not access_token:

                raise RuntimeError(
                    "OAuth refresh did not return "
                    "a valid access_token"
                )

            token_type = tokens.get(
                "token_type",
                self.auth_scheme,
            )

            return {
                self.auth_header: (
                    f"{token_type} "
                    f"{access_token}"
                    if token_type
                    else access_token
                )
            }

        # ==============================================================
        # RUNTIME / MACHINE TO MACHINE
        # ==============================================================

        if (
            not self.access_token
            or time.monotonic()
            >= self.token_expires_at
        ):

            await self._authenticate()

        return {
            self.auth_header: (
                f"{self.token_type} "
                f"{self.access_token}"
                if self.token_type
                else self.access_token
            )
        }

    # ==================================================================
    # REVOKE
    # ==================================================================

    async def revoke(
        self,
        token=None,
        token_type="access_token",
        session=None,
    ):

        if not self.revoke_url:

            return flow.error(
                "OAuth revoke_url "
                "is not configured"
            )

        if session is not None:

            provider = (
                session
                .get("providers", {})
                .get(self.name)
            )

            if provider:

                tokens = provider.get(
                    "tokens",
                    {},
                )

                token = (
                    token
                    or tokens.get(
                        "access_token"
                    )
                )

        token = (
            token
            or self.access_token
        )

        if not token:

            return flow.error(
                "OAuth token is not available"
            )

        payload = {
            "token": token,
            "token_type_hint": token_type,
        }

        try:

            timeout = aiohttp.ClientTimeout(
                total=self.timeout
            )

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as http:

                async with http.post(
                    self.revoke_url,
                    data=payload,
                    ssl=self.verify_ssl,
                ) as response:

                    if not (
                        200
                        <= response.status
                        < 300
                    ):

                        data = (
                            await self._read_response(
                                response
                            )
                        )

                        raise RuntimeError(
                            "OAuth revocation failed: "
                            f"HTTP {response.status} "
                            f"{data}"
                        )

            # ----------------------------------------------------------
            # Remove session credentials
            # ----------------------------------------------------------

            if session is not None:

                session.get(
                    "providers",
                    {},
                ).pop(
                    self.name,
                    None,
                )

            # ----------------------------------------------------------
            # Remove runtime credentials
            # ----------------------------------------------------------

            if token == self.access_token:

                self.access_token = None
                self.refresh_token_value = None
                self.token_expires_at = 0

            return flow.success(
                True
            )

        except Exception as exc:

            return flow.error(
                str(exc)
            )

    # ==================================================================
    # VALIDATE JWT
    # ==================================================================

    async def validate_token(
        self,
        token,
    ):

        try:

            import jwt

            jwks_url = self.config.get(
                "jwks_url"
            )

            jwt_secret = self.config.get(
                "jwt_secret"
            )

            algorithms = self.config.get(
                "jwt_algorithms",
                ["HS256"],
            )

            if isinstance(
                algorithms,
                str,
            ):

                algorithms = [
                    algorithms
                ]

            issuer = self.config.get(
                "jwt_issuer"
            )

            audience = self.config.get(
                "jwt_audience"
            )

            options = {
                "verify_exp": True,
            }

            kwargs = {}

            if issuer:
                kwargs["issuer"] = issuer

            if audience:
                kwargs["audience"] = audience

            # ----------------------------------------------------------
            # Shared secret
            # ----------------------------------------------------------

            if jwt_secret:

                claims = jwt.decode(
                    token,
                    jwt_secret,
                    algorithms=algorithms,
                    options=options,
                    **kwargs,
                )

                return flow.success(
                    claims
                )

            # ----------------------------------------------------------
            # JWKS
            # ----------------------------------------------------------

            if jwks_url:

                signing_key = (
                    jwt.PyJWKClient(
                        jwks_url
                    )
                    .get_signing_key_from_jwt(
                        token
                    )
                )

                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=algorithms,
                    options=options,
                    **kwargs,
                )

                return flow.success(
                    claims
                )

            return flow.error(
                "JWT validation key or "
                "jwks_url is not configured"
            )

        except Exception as exc:

            return flow.error(
                f"Invalid OAuth JWT: {exc}"
            )

    # ==================================================================
    # SIGN IN
    # ==================================================================

    async def sign_in(
        self,
        email,
        password,
    ):

        if self.grant_type != "password":

            return flow.error(
                "Il provider OAuth configurato "
                "non supporta il login password."
            )

        try:

            data = await self._authenticate(
                email,
                password,
            )

        except Exception as exc:

            return flow.error(
                str(exc)
            )

        result = self._token_payload(
            data
        )

        result[
            "providers"
        ][self.name][
            "user"
        ] = {
            "email": email,
        }

        result[
            "user"
        ] = {
            "email": email,
        }

        return flow.success(
            result
        )

    # ==================================================================
    # SIGN UP
    # ==================================================================

    async def sign_up(
        self,
        email,
        password,
    ):

        return flow.error(
            "OAuth non supporta la registrazione "
            "tramite questo provider."
        )

    # ==================================================================
    # SIGN OUT
    # ==================================================================

    async def sign_out(
        self,
        session,
    ):

        session.get(
            "providers",
            {},
        ).pop(
            self.name,
            None,
        )

        session.get(
            "_oauth",
            {},
        ).pop(
            self.name,
            None,
        )

        return flow.success(
            {
                "session": session
            }
        )

    # ==================================================================
    # GET USER
    # ==================================================================

    async def get_user(
        self,
        session,
    ):

        provider = (
            session
            .get("providers", {})
            .get(self.name)
        )

        if not provider:

            return flow.error(
                "Utente non autenticato."
            )

        return flow.success(
            provider.get(
                "user",
                {},
            )
        )

    # ==================================================================
    # GENERIC AUTH PORT OPERATIONS
    # ==================================================================

    async def sign_aid(
        self,
        **constants,
    ):

        return flow.error(
            "OAuth non supporta questa operazione."
        )
