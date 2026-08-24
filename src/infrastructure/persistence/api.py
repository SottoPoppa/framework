from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin

import aiohttp

import framework.port.persistence as persistence
import framework.service.flow as flow


# ======================================================================
# OAuth token
# ======================================================================


@dataclass(slots=True)
class OAuthToken:
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: float = 0.0

    @property
    def valid(self) -> bool:
        if not self.access_token:
            return False

        # Safety margin.
        return time.time() < (
            self.expires_at - 30
        )

    def clear(self):
        self.access_token = None
        self.refresh_token = None
        self.token_type = "Bearer"
        self.expires_at = 0.0


# ======================================================================
# Adapter
# ======================================================================


class Adapter(persistence.Port):
    """
    GLPI 11 HL/API V2 adapter.

    API:

        /api.php/v2.3/

    Authentication:

        OAuth2

    Supported grant types:

        password
        authorization_code
        refresh_token

    Token resolution order:

        1. Explicit adapter configuration
        2. Session provider tokens
        3. OAuth authentication / refresh

    Expected session structure:

        session = {
            "id": "...",

            "user": {
                "email": "utente@example.com"
            },

            "providers": {
                "glpi": {
                    "tokens": {
                        "access_token": "...",
                        "refresh_token": "...",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "expires_at": 178...
                    },

                    "user": {
                        "email": "utente@example.com"
                    }
                }
            }
        }

    Example:

        adapter = Adapter(
            provider="glpi",
            url="https://glpi.example.com",

            api_version="v2.3",

            grant_type="password",

            client_id="CLIENT_ID",
            client_secret="CLIENT_SECRET",

            username="glpi-user",
            password="glpi-password",

            scope="api",
        )

    API examples:

        await adapter.get(
            "Assistance/Ticket"
        )

        await adapter.get(
            "Assistance/Ticket",
            123
        )

        await adapter.create(
            "Assistance/Ticket",
            {
                "name": "Test",
                "content": "Test ticket",
            }
        )

        await adapter.update(
            "Assistance/Ticket",
            123,
            {
                "name": "Updated",
            }
        )

        await adapter.delete(
            "Assistance/Ticket",
            123
        )

    IMPORTANT:

        This adapter is for the GLPI 11 HL/API.

        Do NOT use:

            apirest.php/Ticket

        The V2 URL is:

            /api.php/v2.3/...

    """

    # ==================================================================
    # INIT
    # ==================================================================

    def __init__(
        self,
        **constants: Any,
    ):
        self.name = constants.get(
            "provider",
            "glpi",
        )

        self.config = dict(
            constants
        )

        # --------------------------------------------------------------
        # URL
        # --------------------------------------------------------------

        self.base_url = str(
            constants.get(
                "url",
                constants.get(
                    "base_url",
                    "",
                ),
            )
        ).rstrip("/") + "/"

        if not self.base_url.strip("/"):
            raise ValueError(
                "GLPI 'url' is required"
            )

        # --------------------------------------------------------------
        # API version
        # --------------------------------------------------------------

        self.api_version = str(
            constants.get(
                "api_version",
                "v2.3",
            )
        ).strip("/")

        self.api_base_url = (
            f"{self.base_url}"
            f"api.php/"
            f"{self.api_version}/"
        )

        # --------------------------------------------------------------
        # OAuth endpoints
        #
        # IMPORTANT:
        #
        # OAuth lives under:
        #
        #     /api.php/token
        #
        # and NOT:
        #
        #     /api.php/v2.3/token
        # --------------------------------------------------------------

        self.oauth_base_url = (
            f"{self.base_url}"
            "api.php/"
        )

        self.token_url = (
            f"{self.oauth_base_url}"
            "token"
        )

        self.authorize_url = (
            f"{self.oauth_base_url}"
            "authorize"
        )

        # --------------------------------------------------------------
        # OAuth configuration
        # --------------------------------------------------------------

        self.grant_type = str(
            constants.get(
                "grant_type",
                "password",
            )
        ).lower()

        self.client_id = constants.get(
            "client_id"
        )

        self.client_secret = constants.get(
            "client_secret"
        )

        self.username = constants.get(
            "username"
        )

        self.password = constants.get(
            "password"
        )

        self.scope = constants.get(
            "scope",
            "api",
        )

        self.authorization_code = (
            constants.get(
                "authorization_code"
            )
        )

        # --------------------------------------------------------------
        # Explicit OAuth token configuration
        #
        # These tokens have priority over tokens coming from session.
        # --------------------------------------------------------------

        explicit_access_token = (
            constants.get(
                "access_token"
            )
        )

        explicit_refresh_token = (
            constants.get(
                "refresh_token"
            )
        )

        explicit_token_type = str(
            constants.get(
                "token_type",
                "Bearer",
            )
        )

        explicit_expires_at = (
            constants.get(
                "expires_at"
            )
        )

        explicit_expires_in = (
            constants.get(
                "expires_in"
            )
        )

        # --------------------------------------------------------------
        # Calculate explicit expiration.
        # --------------------------------------------------------------

        expires_at = 0.0

        if explicit_expires_at is not None:

            try:

                expires_at = float(
                    explicit_expires_at
                )

            except (
                TypeError,
                ValueError,
            ):

                expires_at = 0.0

        elif explicit_expires_in is not None:

            try:

                expires_at = (
                    time.time()
                    + float(
                        explicit_expires_in
                    )
                )

            except (
                TypeError,
                ValueError,
            ):

                expires_at = 0.0

        # --------------------------------------------------------------
        # OAuth runtime state
        # --------------------------------------------------------------

        self.oauth = OAuthToken(
            access_token=(
                str(explicit_access_token)
                if explicit_access_token
                else None
            ),
            refresh_token=(
                str(explicit_refresh_token)
                if explicit_refresh_token
                else None
            ),
            token_type=explicit_token_type,
            expires_at=expires_at,
        )

        # Explicit access token must never be replaced by session token.
        self._explicit_access_token = bool(
            explicit_access_token
        )

        self._explicit_refresh_token = bool(
            explicit_refresh_token
        )

        self._auth_lock = asyncio.Lock()

        # --------------------------------------------------------------
        # HTTP
        # --------------------------------------------------------------

        self.timeout = float(
            constants.get(
                "timeout",
                30,
            )
        )

        self.verify_ssl = bool(
            constants.get(
                "verify_ssl",
                True,
            )
        )

        self.accept = str(
            constants.get(
                "accept",
                "application/json",
            )
        )

        self.headers = dict(
            constants.get(
                "headers",
                {},
            )
        )

        # --------------------------------------------------------------
        # Retry
        # --------------------------------------------------------------

        self.retry_enabled = bool(
            constants.get(
                "retry_enabled",
                True,
            )
        )

        self.retry_attempts = max(
            1,
            int(
                constants.get(
                    "retry_attempts",
                    3,
                )
            ),
        )

        self.retry_backoff = float(
            constants.get(
                "retry_backoff",
                0.5,
            )
        )

        self.retry_status_codes = {
            int(code)
            for code in constants.get(
                "retry_status_codes",
                (
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                ),
            )
        }

        # --------------------------------------------------------------
        # HTTP session
        # --------------------------------------------------------------

        self._http: (
            aiohttp.ClientSession | None
        ) = None

        self._http_lock = asyncio.Lock()

    # ==================================================================
    # SESSION TOKENS
    # ==================================================================

    def _session_tokens(
        self,
        session: Any,
    ) -> Mapping[str, Any] | None:
        """
        Return provider tokens from framework session.

        Expected:

            session["providers"][self.name]["tokens"]
        """

        if not isinstance(
            session,
            Mapping,
        ):
            return None

        providers = session.get(
            "providers"
        )

        if not isinstance(
            providers,
            Mapping,
        ):
            return None

        provider = providers.get(
            self.name
        )

        if not isinstance(
            provider,
            Mapping,
        ):
            return None

        tokens = provider.get(
            "tokens"
        )

        if not isinstance(
            tokens,
            Mapping,
        ):
            return None

        return tokens

    # ==================================================================
    # LOAD SESSION TOKENS
    # ==================================================================

    def _load_tokens_from_session(
        self,
        session: Any,
    ) -> bool:
        """
        Load OAuth tokens from the framework session.

        Explicit adapter tokens always have priority.

        Returns:

            True
                if a valid access token was loaded.

            False
                if no usable token was found.
        """

        # --------------------------------------------------------------
        # Explicit access token wins.
        # --------------------------------------------------------------

        if self._explicit_access_token:

            return self.oauth.valid

        tokens = self._session_tokens(
            session
        )

        if not tokens:
            return False

        access_token = tokens.get(
            "access_token"
        )

        if not access_token:
            return False

        # --------------------------------------------------------------
        # Access token
        # --------------------------------------------------------------

        self.oauth.access_token = str(
            access_token
        )

        # --------------------------------------------------------------
        # Token type
        # --------------------------------------------------------------

        self.oauth.token_type = str(
            tokens.get(
                "token_type",
                "Bearer",
            )
        )

        # --------------------------------------------------------------
        # Refresh token
        #
        # Explicit refresh token has priority.
        # --------------------------------------------------------------

        if not self._explicit_refresh_token:

            refresh_token = tokens.get(
                "refresh_token"
            )

            if refresh_token:

                self.oauth.refresh_token = str(
                    refresh_token
                )

        # --------------------------------------------------------------
        # Expiration
        # --------------------------------------------------------------

        expires_at = tokens.get(
            "expires_at"
        )

        if expires_at is not None:

            try:

                self.oauth.expires_at = float(
                    expires_at
                )

            except (
                TypeError,
                ValueError,
            ):

                self.oauth.expires_at = 0.0

        else:

            expires_in = tokens.get(
                "expires_in"
            )

            if expires_in is not None:

                try:

                    self.oauth.expires_at = (
                        time.time()
                        + float(
                            expires_in
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    self.oauth.expires_at = 0.0

            else:

                self.oauth.expires_at = 0.0

        return self.oauth.valid

    # ==================================================================
    # SAVE TOKENS TO SESSION
    # ==================================================================

    def _save_tokens_to_session(
        self,
        session: Any,
    ):
        """
        Save current OAuth tokens into the framework session.

        Expected session structure:

            session["providers"][self.name]["tokens"]

        This method intentionally does nothing if the session is not
        mutable or if its expected structure is unavailable.
        """

        if not isinstance(
            session,
            dict,
        ):
            return

        providers = session.setdefault(
            "providers",
            {},
        )

        if not isinstance(
            providers,
            dict,
        ):
            return

        provider = providers.setdefault(
            self.name,
            {},
        )

        if not isinstance(
            provider,
            dict,
        ):
            return

        tokens = provider.setdefault(
            "tokens",
            {},
        )

        if not isinstance(
            tokens,
            dict,
        ):
            tokens = {}
            provider["tokens"] = tokens

        # --------------------------------------------------------------
        # Access token
        # --------------------------------------------------------------

        if self.oauth.access_token:

            tokens["access_token"] = (
                self.oauth.access_token
            )

        # --------------------------------------------------------------
        # Refresh token
        # --------------------------------------------------------------

        if self.oauth.refresh_token:

            tokens["refresh_token"] = (
                self.oauth.refresh_token
            )

        # --------------------------------------------------------------
        # Token type
        # --------------------------------------------------------------

        tokens["token_type"] = (
            self.oauth.token_type
        )

        # --------------------------------------------------------------
        # Absolute expiration
        # --------------------------------------------------------------

        tokens["expires_at"] = (
            self.oauth.expires_at
        )

        # --------------------------------------------------------------
        # Relative expiration
        #
        # Keep it useful for consumers expecting expires_in.
        # --------------------------------------------------------------

        remaining = max(
            0,
            int(
                self.oauth.expires_at
                - time.time()
            ),
        )

        tokens["expires_in"] = remaining

    # ==================================================================
    # HTTP SESSION
    # ==================================================================

    async def _get_http(
        self,
    ) -> aiohttp.ClientSession:

        if (
            self._http is not None
            and not self._http.closed
        ):
            return self._http

        async with self._http_lock:

            if (
                self._http is not None
                and not self._http.closed
            ):
                return self._http

            timeout = aiohttp.ClientTimeout(
                total=self.timeout
            )

            self._http = (
                aiohttp.ClientSession(
                    timeout=timeout
                )
            )

            return self._http

    # ==================================================================
    # CLOSE
    # ==================================================================

    async def close(self):

        if (
            self._http is not None
            and not self._http.closed
        ):
            await self._http.close()

        self._http = None

        self.oauth.clear()

    # ==================================================================
    # URL
    # ==================================================================

    def _api_url(
        self,
        location: str = "",
    ) -> str:
        """
        Build GLPI V2 URL.

        Example:

            Assistance/Ticket

        ->

            https://glpi.example.com/
            api.php/v2.3/Assistance/Ticket
        """

        location = str(
            location or ""
        ).strip("/")

        return urljoin(
            self.api_base_url,
            location,
        )

    # ==================================================================
    # HEADERS
    # ==================================================================

    def _headers(
        self,
        headers: Mapping[str, str] | None = None,
        *,
        authenticated: bool = True,
        has_body: bool = False,
        body_type: str = "json",
    ) -> dict[str, str]:
        """
        Build request headers.

        IMPORTANT:

        Content-Type is NOT automatically sent for GET/HEAD.

        GLPI V2 can reject a GET containing:

            Content-Type: application/json

        with:

            Invalid JSON body
        """

        result = {
            "Accept": self.accept,
        }

        # --------------------------------------------------------------
        # Content-Type
        # --------------------------------------------------------------

        if has_body:

            if body_type == "json":

                result[
                    "Content-Type"
                ] = "application/json"

            elif body_type == "form":

                result[
                    "Content-Type"
                ] = (
                    "application/x-www-form-urlencoded"
                )

            elif body_type == "text":

                result[
                    "Content-Type"
                ] = "text/plain"

        # --------------------------------------------------------------
        # Static headers
        # --------------------------------------------------------------

        result.update(
            self.headers
        )

        # --------------------------------------------------------------
        # OAuth
        # --------------------------------------------------------------

        if (
            authenticated
            and self.oauth.access_token
        ):

            result[
                "Authorization"
            ] = (
                f"{self.oauth.token_type} "
                f"{self.oauth.access_token}"
            )

        # --------------------------------------------------------------
        # Request headers
        # --------------------------------------------------------------

        if headers:
            result.update(
                headers
            )

        return result

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
            ).lower()
        )

        if "json" in content_type:

            try:

                return await response.json(
                    content_type=None
                )

            except (
                ValueError,
                aiohttp.ContentTypeError,
            ):
                pass

        text = await response.text()

        if not text:
            return None

        return text

    # ==================================================================
    # OAUTH CONFIG
    # ==================================================================

    def _validate_oauth_config(self):

        missing = []

        if not self.client_id:
            missing.append(
                "client_id"
            )

        if not self.client_secret:
            missing.append(
                "client_secret"
            )

        if self.grant_type == "password":

            if not self.username:
                missing.append(
                    "username"
                )

            if not self.password:
                missing.append(
                    "password"
                )

        elif (
            self.grant_type
            == "authorization_code"
        ):

            if (
                not self.authorization_code
                and not self.oauth.refresh_token
            ):
                missing.append(
                    "authorization_code"
                )

        if missing:

            raise RuntimeError(
                "Missing GLPI OAuth configuration: "
                + ", ".join(missing)
            )

    # ==================================================================
    # AUTHENTICATE
    # ==================================================================

    async def authenticate(
        self,
        force: bool = False,
        session=None,
    ) -> OAuthToken:

        # --------------------------------------------------------------
        # If not forced, try current token.
        # --------------------------------------------------------------

        if (
            self.oauth.valid
            and not force
        ):
            return self.oauth

        async with self._auth_lock:

            # ----------------------------------------------------------
            # Double check after acquiring lock.
            # ----------------------------------------------------------

            if (
                self.oauth.valid
                and not force
            ):
                return self.oauth

            # ----------------------------------------------------------
            # Refresh token
            #
            # Authorization-code flow supports refresh.
            # ----------------------------------------------------------

            if (
                self.grant_type
                == "authorization_code"
                and self.oauth.refresh_token
            ):

                try:

                    token = await (
                        self._refresh_token()
                    )

                    self._save_tokens_to_session(
                        session
                    )

                    return token

                except Exception:

                    # If refresh fails, clear only runtime state.
                    #
                    # We intentionally don't immediately destroy
                    # the session here because the caller may still
                    # need it for another authentication strategy.

                    self.oauth.access_token = None
                    self.oauth.expires_at = 0.0

            # ----------------------------------------------------------
            # Validate
            # ----------------------------------------------------------

            self._validate_oauth_config()

            # ----------------------------------------------------------
            # Password
            # ----------------------------------------------------------

            if self.grant_type == "password":

                token = await (
                    self._password_grant()
                )

                self._save_tokens_to_session(
                    session
                )

                return token

            # ----------------------------------------------------------
            # Authorization code
            # ----------------------------------------------------------

            if (
                self.grant_type
                == "authorization_code"
            ):

                token = await (
                    self._authorization_code_grant()
                )

                self._save_tokens_to_session(
                    session
                )

                return token

            raise RuntimeError(
                "Unsupported GLPI OAuth grant type: "
                f"{self.grant_type}"
            )

    # ==================================================================
    # PASSWORD GRANT
    # ==================================================================

    async def _password_grant(
        self,
    ) -> OAuthToken:

        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }

        if self.scope:
            payload["scope"] = self.scope

        return await self._request_token(
            payload
        )

    # ==================================================================
    # AUTHORIZATION CODE
    # ==================================================================

    async def _authorization_code_grant(
        self,
    ) -> OAuthToken:

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": self.authorization_code,
        }

        if self.scope:
            payload["scope"] = self.scope

        return await self._request_token(
            payload
        )

    # ==================================================================
    # REFRESH TOKEN
    # ==================================================================

    async def _refresh_token(
        self,
    ) -> OAuthToken:

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.oauth.refresh_token,
        }

        if self.scope:
            payload["scope"] = self.scope

        return await self._request_token(
            payload
        )

    # ==================================================================
    # TOKEN REQUEST
    # ==================================================================

    async def _request_token(
        self,
        payload: Mapping[str, Any],
    ) -> OAuthToken:

        http = await self._get_http()

        headers = {
            "Accept": "application/json",
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
        }

        try:

            async with http.post(
                self.token_url,
                data=payload,
                headers=headers,
                ssl=self.verify_ssl,
                timeout=aiohttp.ClientTimeout(
                    total=self.timeout
                ),
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
                        "GLPI OAuth authentication "
                        "failed: "
                        f"{response.status} "
                        f"{data}"
                    )

                if not isinstance(
                    data,
                    Mapping,
                ):

                    raise RuntimeError(
                        "GLPI OAuth token endpoint "
                        "returned invalid response: "
                        f"{data}"
                    )

                access_token = data.get(
                    "access_token"
                )

                if not access_token:

                    raise RuntimeError(
                        "GLPI OAuth response does "
                        "not contain access_token"
                    )

                expires_in = int(
                    data.get(
                        "expires_in",
                        3600,
                    )
                )

                self.oauth.access_token = (
                    str(access_token)
                )

                self.oauth.token_type = str(
                    data.get(
                        "token_type",
                        "Bearer",
                    )
                )

                refresh_token = data.get(
                    "refresh_token"
                )

                if refresh_token:

                    self.oauth.refresh_token = (
                        str(refresh_token)
                    )

                self.oauth.expires_at = (
                    time.time()
                    + expires_in
                )

                return self.oauth

        except aiohttp.ClientError as exc:

            raise RuntimeError(
                "GLPI OAuth connection error: "
                f"{exc}"
            ) from exc

        except asyncio.TimeoutError as exc:

            raise RuntimeError(
                "GLPI OAuth timeout"
            ) from exc

    # ==================================================================
    # AUTHORIZATION URL
    # ==================================================================

    def authorization_url(
        self,
    ) -> str:

        if not self.client_id:

            raise RuntimeError(
                "client_id is required"
            )

        params = {
            "response_type": "code",
            "client_id": self.client_id,
        }

        if self.scope:
            params["scope"] = self.scope

        return (
            f"{self.authorize_url}?"
            f"{urlencode(params)}"
        )

    # ==================================================================
    # RETRY DELAY
    # ==================================================================

    async def _retry_delay(
        self,
        attempt: int,
    ):

        delay = (
            self.retry_backoff
            * (
                2
                ** (
                    attempt - 1
                )
            )
        )

        await asyncio.sleep(
            delay
        )

    # ==================================================================
    # RAW REQUEST
    # ==================================================================

    async def _raw_request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        params=None,
        payload=None,
        body_type: str = "json",
        timeout: float | None = None,
        verify_ssl: bool | None = None,
    ):
        """
        Execute low-level HTTP request.

        Important:

        GET/HEAD without payload never receive
        Content-Type: application/json.
        """

        method = str(
            method
        ).upper()

        http = await self._get_http()

        has_body = (
            payload is not None
            and method not in {
                "GET",
                "HEAD",
            }
        )

        request_headers = dict(
            headers
        )

        # --------------------------------------------------------------
        # Prevent invalid GLPI GET body
        # --------------------------------------------------------------

        if not has_body:

            request_headers.pop(
                "Content-Type",
                None,
            )

        else:

            if body_type == "json":

                request_headers[
                    "Content-Type"
                ] = "application/json"

            elif body_type == "form":

                request_headers[
                    "Content-Type"
                ] = (
                    "application/x-www-form-urlencoded"
                )

            elif body_type == "text":

                request_headers[
                    "Content-Type"
                ] = "text/plain"

        # --------------------------------------------------------------
        # Request kwargs
        # --------------------------------------------------------------

        request_kwargs = {
            "method": method,
            "url": url,
            "headers": request_headers,
            "params": params,
            "ssl": (
                self.verify_ssl
                if verify_ssl is None
                else verify_ssl
            ),
            "timeout": aiohttp.ClientTimeout(
                total=(
                    self.timeout
                    if timeout is None
                    else float(timeout)
                )
            ),
        }

        # --------------------------------------------------------------
        # Body
        # --------------------------------------------------------------

        if has_body:

            if body_type == "json":

                request_kwargs[
                    "json"
                ] = payload

            elif body_type == "form":

                request_kwargs[
                    "data"
                ] = payload

            elif body_type == "text":

                request_kwargs[
                    "data"
                ] = str(payload)

            else:

                request_kwargs[
                    "data"
                ] = payload

        # --------------------------------------------------------------
        # Retry
        # --------------------------------------------------------------

        attempts = (
            self.retry_attempts
            if self.retry_enabled
            else 1
        )

        for attempt in range(
            1,
            attempts + 1,
        ):

            try:

                async with http.request(
                    **request_kwargs
                ) as response:

                    status = response.status

                    data = (
                        await self._read_response(
                            response
                        )
                    )

                    # --------------------------------------------------
                    # Retry HTTP statuses
                    # --------------------------------------------------

                    if (
                        status
                        in self.retry_status_codes
                        and attempt < attempts
                    ):

                        retry_after = (
                            response.headers.get(
                                "Retry-After"
                            )
                        )

                        if retry_after:

                            try:

                                delay = float(
                                    retry_after
                                )

                            except ValueError:

                                delay = (
                                    self.retry_backoff
                                    * (
                                        2
                                        ** (
                                            attempt - 1
                                        )
                                    )
                                )

                            await asyncio.sleep(
                                delay
                            )

                        else:

                            await self._retry_delay(
                                attempt
                            )

                        continue

                    return status, data

            except (
                aiohttp.ClientConnectionError,
                aiohttp.ServerDisconnectedError,
                aiohttp.ClientPayloadError,
            ):

                if attempt >= attempts:
                    raise

                await self._retry_delay(
                    attempt
                )

            except asyncio.TimeoutError:

                if attempt >= attempts:
                    raise

                await self._retry_delay(
                    attempt
                )

        raise RuntimeError(
            "GLPI HTTP request failed"
        )

    # ==================================================================
    # REQUEST
    # ==================================================================

    @flow.result(safe_kwargs=True)
    async def request(
        self,
        session=None,
        storekeeper=None,
        **constants: Any,
    ):
        """
        Generic GLPI API request.

        Session token resolution:

            1. Explicit Adapter access_token
            2. session["providers"][provider]["tokens"]
            3. OAuth authentication
        """

        # --------------------------------------------------------------
        # Storekeeper
        # --------------------------------------------------------------

        if storekeeper:

            constants = {
                **storekeeper,
                **constants,
            }

        method = str(
            constants.get(
                "method",
                "GET",
            )
        ).upper()

        location = str(
            constants.get(
                "location",
                "",
            )
        )

        params = constants.get(
            "params"
        )

        payload = constants.get(
            "payload"
        )

        body_type = str(
            constants.get(
                "body_type",
                "json",
            )
        ).lower()

        custom_headers = constants.get(
            "headers"
        )

        timeout = constants.get(
            "timeout"
        )

        verify_ssl = constants.get(
            "verify_ssl"
        )

        # --------------------------------------------------------------
        # Safety check:
        #
        # Do not allow accidental legacy API path.
        # --------------------------------------------------------------

        if location.lower().startswith(
            "apirest.php"
        ):

            return flow.error(
                "Invalid GLPI V2 location: "
                f"{location}. "
                "Do not use 'apirest.php'. "
                "Use V2 locations such as "
                "'Assistance/Ticket'."
            )

        # --------------------------------------------------------------
        # Authentication
        #
        # First load tokens from session if an explicit token was not
        # configured in the Adapter.
        # --------------------------------------------------------------

        self._load_tokens_from_session(
            session
        )

        try:

            await self.authenticate(
                session=session
            )

        except Exception as exc:

            return flow.error(
                str(exc)
            )

        # --------------------------------------------------------------
        # URL
        # --------------------------------------------------------------

        url = self._api_url(
            location
        )

        # --------------------------------------------------------------
        # Headers
        # --------------------------------------------------------------

        has_body = (
            payload is not None
            and method not in {
                "GET",
                "HEAD",
            }
        )

        request_headers = self._headers(
            custom_headers,
            has_body=has_body,
            body_type=body_type,
        )

        # --------------------------------------------------------------
        # Execute
        # --------------------------------------------------------------

        try:

            status, data = (
                await self._raw_request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    params=params,
                    payload=payload,
                    body_type=body_type,
                    timeout=timeout,
                    verify_ssl=verify_ssl,
                )
            )

        except aiohttp.ClientError as exc:

            return flow.error(
                "GLPI HTTP connection error: "
                f"{exc}"
            )

        except asyncio.TimeoutError:

            return flow.error(
                "GLPI HTTP timeout: "
                f"{method} {url}"
            )

        except Exception as exc:

            return flow.error(
                "GLPI adapter error: "
                f"{exc}"
            )

        # --------------------------------------------------------------
        # Authentication expired
        # --------------------------------------------------------------

        if status == 401:

            try:

                # Force OAuth refresh/re-authentication.
                await self.authenticate(
                    force=True,
                    session=session,
                )

                # Save refreshed token to session.
                self._save_tokens_to_session(
                    session
                )

                retry_headers = self._headers(
                    custom_headers,
                    has_body=has_body,
                    body_type=body_type,
                )

                status, data = (
                    await self._raw_request(
                        method=method,
                        url=url,
                        headers=retry_headers,
                        params=params,
                        payload=payload,
                        body_type=body_type,
                        timeout=timeout,
                        verify_ssl=verify_ssl,
                    )
                )

            except Exception as exc:

                return flow.error(
                    "GLPI authentication retry "
                    f"failed: {exc}"
                )

        # --------------------------------------------------------------
        # Success
        # --------------------------------------------------------------

        if (
            200
            <= status
            < 300
        ):

            return flow.success(
                data
            )

        # --------------------------------------------------------------
        # Error
        # --------------------------------------------------------------

        return flow.error(
            "GLPI API request failed: "
            f"{method} {url} "
            f"({status}) "
            f"{data}"
        )

    # ==================================================================
    # RESOURCE LOCATION
    # ==================================================================

    @staticmethod
    def _resource_location(
        resource: str,
        item_id: Any | None = None,
    ) -> str:

        resource = str(
            resource
        ).strip("/")

        # Explicitly prevent accidental legacy API usage.
        if resource.lower().startswith(
            "apirest.php"
        ):
            raise ValueError(
                "GLPI V2 does not use "
                "'apirest.php'. "
                "Use e.g. 'Assistance/Ticket'."
            )

        if item_id is None:

            return resource

        return (
            f"{resource}/"
            f"{item_id}"
        )

    # ==================================================================
    # GET
    # ==================================================================

    async def get(
        self,
        resource: str,
        item_id: Any | None = None,
        *,
        session=None,
        params=None,
        headers=None,
    ):

        return await self.request(
            session=session,
            method="GET",
            location=self._resource_location(
                resource,
                item_id,
            ),
            params=params,
            headers=headers,
        )

    # ==================================================================
    # LIST
    # ==================================================================

    async def list(
        self,
        resource: str,
        *,
        session=None,
        params=None,
        headers=None,
    ):

        return await self.request(
            session=session,
            method="GET",
            location=self._resource_location(
                resource
            ),
            params=params,
            headers=headers,
        )

    # ==================================================================
    # QUERY
    # ==================================================================

    async def query(
        self,
        resource: str,
        *,
        session=None,
        params=None,
        headers=None,
    ):

        return await self.list(
            resource,
            session=session,
            params=params,
            headers=headers,
        )

    # ==================================================================
    # CREATE
    # ==================================================================

    async def create(
        self,
        resource: str,
        payload: Mapping[str, Any],
        *,
        session=None,
        headers=None,
    ):

        return await self.request(
            session=session,
            method="POST",
            location=self._resource_location(
                resource
            ),
            payload=dict(payload),
            body_type="json",
            headers=headers,
        )

    # ==================================================================
    # UPDATE
    # ==================================================================

    async def update(
        self,
        resource: str,
        item_id: Any,
        payload: Mapping[str, Any],
        *,
        session=None,
        headers=None,
    ):

        return await self.request(
            session=session,
            method="PATCH",
            location=self._resource_location(
                resource,
                item_id,
            ),
            payload=dict(payload),
            body_type="json",
            headers=headers,
        )

    # ==================================================================
    # PUT
    # ==================================================================

    async def put(
        self,
        resource: str,
        item_id: Any,
        payload: Mapping[str, Any],
        *,
        session=None,
        headers=None,
    ):

        return await self.request(
            session=session,
            method="PUT",
            location=self._resource_location(
                resource,
                item_id,
            ),
            payload=dict(payload),
            body_type="json",
            headers=headers,
        )

    # ==================================================================
    # DELETE
    # ==================================================================

    async def delete(
        self,
        resource: str,
        item_id: Any,
        *,
        session=None,
        params=None,
        headers=None,
    ):

        return await self.request(
            session=session,
            method="DELETE",
            location=self._resource_location(
                resource,
                item_id,
            ),
            params=params,
            headers=headers,
        )

    # ==================================================================
    # PERSISTENCE PORT
    # ==================================================================

    async def read(
        self,
        session,
        storekeeper,
    ):

        return await self.request(
            session=session,
            storekeeper={
                **storekeeper,
                "method": "GET",
            },
        )

    async def view(
        self,
        session,
        storekeeper,
    ):

        return await self.request(
            session=session,
            storekeeper={
                **storekeeper,
                "method": "GET",
            },
        )

    async def query_port(
        self,
        session,
        storekeeper,
    ):

        return await self.request(
            session=session,
            storekeeper={
                **storekeeper,
                "method": "GET",
            },
        )

    async def create_item(
        self,
        session,
        storekeeper,
    ):

        return await self.request(
            session=session,
            storekeeper={
                **storekeeper,
                "method": "POST",
            },
        )

    async def update_item(
        self,
        session,
        storekeeper,
    ):

        return await self.request(
            session=session,
            storekeeper={
                **storekeeper,
                "method": "PATCH",
            },
        )

    async def delete_item(
        self,
        session,
        storekeeper,
    ):

        return await self.request(
            session=session,
            storekeeper={
                **storekeeper,
                "method": "DELETE",
            },
        )

    # ==================================================================
    # LEGACY COMPATIBILITY
    # ==================================================================

    async def persistence_query(
        self,
        session,
        storekeeper,
    ):

        return await self.request(
            session=session,
            storekeeper={
                **storekeeper,
                "method": "GET",
            },
        )
