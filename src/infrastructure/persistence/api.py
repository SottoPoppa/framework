import time
from urllib.parse import urljoin
from collections.abc import Mapping

import aiohttp

import framework.port.persistence as persistence
import framework.port.authentication as authentication
import framework.service.flow as flow


class Adapter(persistence.Port):
    """
    Generic HTTP/API adapter.

    Questo adapter non conosce nessun provider specifico.
    Può essere utilizzato per REST API, JSON API e servizi HTTP
    che utilizzano i normali metodi HTTP.

    Configurazione:
        provider
        url
        token
        authorization
        accept
        content_type
        timeout
        verify_ssl
        headers
    """

    def __init__(self, authentications: list[authentication.Port], **constants):
        self.name = constants.get("provider", "api")
        self.config = constants
        self.auth_name = constants.get("auth")
        self.authentications = authentications

        self.base_url = (
            constants.get("url")
            or constants.get("base_url")
            or ""
        ).rstrip("/") + "/"

        self.token = constants.get("token")
        self.app_token = constants.get("app_token")
        self.authorization = constants.get(
            "authorization",
            "Bearer"
        )
        self.accept = constants.get(
            "accept",
            "application/json"
        )

        self.content_type = constants.get(
            "content_type",
            "application/json"
        )

        self.timeout = float(
            constants.get("timeout", 30)
        )

        self.verify_ssl = constants.get(
            "verify_ssl",
            True
        )

        self.headers = dict(
            constants.get("headers", {})
        )

    # ------------------------------------------------------------------
    # URL
    # ------------------------------------------------------------------

    def _url(self, location=""):
        """
        Costruisce l'URL finale.

        location:
            /Computer
            /Computer/42
            users
            /api/v2/users
        """

        location = str(location or "").lstrip("/")

        return urljoin(
            self.base_url,
            location
        )

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _headers(self, headers=None):
        result = {
            "Accept": self.accept,
            "Content-Type": self.content_type,
        }

        result.update(self.headers)

        if self.token:
            authorization = str(
                self.authorization or ""
            ).strip()

            if authorization:
                result["Authorization"] = (
                    f"{authorization} {self.token}"
                )
            else:
                result["Authorization"] = self.token

        if self.app_token:
            result["App-Token"] = self.app_token

        if headers:
            result.update(headers)

        return result

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------

    @flow.result(safe_kwargs=True)
    async def request(self, session=None, storekeeper=None, **constants):
        """
        Esegue una richiesta HTTP generica.

        Parametri:

            method
            location
            payload
            params
            headers
            timeout
            verify_ssl
        """

        if storekeeper:
            constants = {
                **storekeeper,
                **constants,
            }

        method = str(
            constants.get("method", "GET")
        ).upper()

        location = constants.get(
            "location",
            ""
        )

        payload = constants.get(
            "payload"
        )

        params = constants.get(
            "params"
        )

        headers = self._headers()
        if self.auth_name:
            if not isinstance(session, Mapping):
                raise RuntimeError(
                    "Una sessione è necessaria per usare l'autenticazione OAuth."
                )
            providers = session.get("providers", {})
            provider = next(
                (
                    value
                    for key, value in providers.items()
                    if key == self.auth_name
                ),
                {},
            )
            tokens = provider.get("tokens", {})
            access_token = tokens.get("access_token")
            expires_at = tokens.get("expires_at")
            auth_provider = next(
                (
                    candidate
                    for candidate in self.authentications
                    if getattr(candidate, "name", None) == self.auth_name
                ),
                None,
            )

            if access_token and (
                expires_at is None or time.time() < float(expires_at)
            ):
                scheme = tokens.get("token_type", self.authorization)
                auth_header = tokens.get("auth_header", "Authorization")
                headers[auth_header] = (
                    f"{scheme} {access_token}"
                    if scheme
                    else access_token
                )
            elif auth_provider is not None:
                headers.update(await auth_provider.get_headers())
            elif not access_token:
                raise RuntimeError(
                    f"Token assente nella sessione per '{self.auth_name}' "
                    "e provider OAuth non disponibile."
                )
            else:
                raise RuntimeError(
                    f"Token scaduto nella sessione per '{self.auth_name}' "
                    "e provider OAuth non disponibile."
                )

        if constants.get("headers"):
            headers.update(constants["headers"])

        timeout = aiohttp.ClientTimeout(
            total=float(
                constants.get(
                    "timeout",
                    self.timeout
                )
            )
        )

        verify_ssl = constants.get(
            "verify_ssl",
            self.verify_ssl
        )

        url = self._url(location)
        request_kwargs = {
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "ssl": verify_ssl,
        }
        if method not in {"GET", "HEAD"} and payload is not None:
            request_kwargs["json"] = payload

        try:
            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                async with session.request(
                    **request_kwargs,
                ) as response:

                    status = response.status

                    content_type = (
                        response.headers.get(
                            "Content-Type",
                            ""
                        )
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

                    if 200 <= status < 300:
                        return flow.success(data)

                    return flow.error(
                        f"HTTP request failed: "
                        f"{method} {url} "
                        f"({status}) {data}"
                    )

        except aiohttp.ClientError as exc:
            return flow.error(
                f"HTTP connection error: {exc}"
            )

        except TimeoutError:
            return flow.error(
                f"HTTP request timeout: "
                f"{method} {url}"
            )

        except Exception as exc:
            return flow.error(
                f"API adapter error: {exc}"
            )

    # ------------------------------------------------------------------
    # CRUD-like operations
    # ------------------------------------------------------------------

    async def create(self, session, storekeeper):
        return await self.request(
            session=session,
            storekeeper={**storekeeper, "method": "POST"},
        )

    async def read(self, session, storekeeper):
        return await self.request(
            session=session,
            storekeeper={**storekeeper, "method": "GET"},
        )

    async def update(self, session, storekeeper):
        return await self.request(
            session=session,
            storekeeper={**storekeeper, "method": "PUT"},
        )

    async def delete(self, session, storekeeper):
        return await self.request(
            session=session,
            storekeeper={**storekeeper, "method": "DELETE"},
        )

    async def query(self, session, storekeeper):
        return await self.request(
            session=session,
            storekeeper={**storekeeper, "method": "GET"},
        )

    async def view(self, session, storekeeper):
        return await self.request(
            session=session,
            storekeeper={**storekeeper, "method": "GET"},
        )