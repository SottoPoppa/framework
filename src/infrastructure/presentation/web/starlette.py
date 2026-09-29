import uuid
import asyncio
import hashlib
import hmac
from html import escape
import re
import json
import logging
import ssl
from http.cookies import SimpleCookie
from datetime import datetime
from urllib.parse import urlsplit, urlunparse, ParseResult,parse_qs
import xml.etree.ElementTree as ET
import htpy
from markupsafe import Markup
import secrets

import framework.port.presentation as presentation
import framework.core.flow as flow
import framework.service.route as route
from infrastructure.presentation.adapter import Adapter as PresentationAdapter
from framework.service.diagnostic import get_logger
from framework.service.route import split_url
from framework.manager.defender import Manager as Defender
from framework.manager.messenger import Manager as Messenger
from framework.manager.authenticator import Manager as Authenticator
from framework.manager.storekeeper import Manager as Storekeeper
from framework.manager.loader import Loader

logger = get_logger("presentation.web")


class _FrameworkLogHandler(logging.Handler):
    def __init__(self, framework_logger):
        super().__init__()
        self.framework_logger = framework_logger

    def emit(self, record):
        try:
            method_name = {
                logging.DEBUG: "debug",
                logging.INFO: "info",
                logging.WARNING: "warning",
                logging.ERROR: "error",
                logging.CRITICAL: "critical",
            }.get(record.levelno, "info")
            metadata = {"source_logger": record.name}
            if record.exc_info:
                metadata["exception"] = record.exc_info[1]
            getattr(self.framework_logger, method_name)(
                record.getMessage(), **metadata
            )
        except Exception:
            self.handleError(record)


def _uvicorn_log_config():
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
        },
        "handlers": {
            "framework": {
                "()": _FrameworkLogHandler,
                "framework_logger": logger,
            }
        },
        "loggers": {
            name: {
                "handlers": ["framework"],
                "level": "INFO",
                "propagate": False,
            }
            for name in (
                "uvicorn",
                "uvicorn.error",
                "uvicorn.access",
                "uvicorn.asgi",
                "starlette",
            )
        },
    }

try:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse,HTMLResponse,RedirectResponse
    from starlette.routing import Route,Mount,WebSocketRoute
    from starlette.middleware import Middleware
    from starlette.websockets import WebSocket, WebSocketDisconnect
    from starlette.middleware.cors import CORSMiddleware
    #from starlette.middleware.csrf import CSRFMiddleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.exceptions import HTTPException
    from starlette.staticfiles import StaticFiles

    import os
    import uuid
    #import uvicorn
    from uvicorn import Config, Server

    # Auth 
    #from starlette.middleware.sessions import SessionMiddleware
    from datetime import timedelta
    #from starlette_login.middleware import AuthenticationMiddleware

    #
    from starlette.requests import HTTPConnection
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from starlette.datastructures import MutableHeaders
    import http.cookies
    import markupsafe
    from bs4 import BeautifulSoup
    import paramiko
    import asyncio

    '''class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["Server"] = "Starlette-Test"
            return response'''

except Exception as e:
    #import starlette
    import markupsafe
    from bs4 import BeautifulSoup
    
    import xml.etree.ElementTree as ET
    from xml.sax.saxutils import escape

class ServerSessionMiddleware(BaseHTTPMiddleware):
    """Mantiene i dati di sessione sul server e nel cookie conserva solo un riferimento opaco."""

    def __init__(self, app, secret_key, storekeeper, cookie_name="session_state", secure=False):
        super().__init__(app)
        self.secret_key = secret_key.encode("utf-8")
        self.storekeeper = storekeeper
        self.cookie_name = cookie_name
        self.secure = secure

    def _signature(self, session_id):
        return hmac.new(self.secret_key, session_id.encode(), hashlib.sha256).hexdigest()

    def _session_id(self, cookie):
        if not cookie:
            return None, False
        session_id, separator, signature = cookie.partition(".")
        try:
            uuid.UUID(session_id)
        except (ValueError, AttributeError):
            return None, False
        if not separator or not hmac.compare_digest(signature, self._signature(session_id)):
            return None, False
        return session_id, True

    @staticmethod
    def _new_session_id():
        return str(uuid.uuid4())

    async def _load_session(self, session_id, verified):
        session = {"id": session_id}
        if not verified:
            return session

        result = await self.storekeeper.gather(
            session,
            repository="sessions",
            filter={"eq": {"id": session_id}},
        )
        if not flow.check(result):
            raise RuntimeError(f"Impossibile leggere la sessione: {flow.output(result)}")
        stored = flow.output(result)
        if isinstance(stored, dict):
            content = stored.get("content", "")
            if isinstance(content, str) and content:
                try:
                    loaded = json.loads(content)
                except json.JSONDecodeError as error:
                    raise RuntimeError("Sessione persistita non valida") from error
                if isinstance(loaded, dict):
                    session.update(loaded)
        session["id"] = session_id
        return session

    async def _save_session(self, session):
        result = await self.storekeeper.change(
            session,
            repository="sessions",
            filter={"eq": {"id": session["id"]}},
            payload={"content": json.dumps(session)},
        )
        if not flow.check(result):
            raise RuntimeError(f"Impossibile salvare la sessione: {flow.output(result)}")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "websocket":
            return await super().__call__(scope, receive, send)

        cookies = SimpleCookie()
        for name, value in scope.get("headers", []):
            if name.lower() == b"cookie":
                cookies.load(value.decode("latin-1"))
                break
        cookie = cookies.get(self.cookie_name)
        session_id, verified = self._session_id(cookie.value if cookie else None)
        session_id = session_id or self._new_session_id()
        session = await self._load_session(session_id, verified)
        scope["session"] = session
        try:
            await self.app(scope, receive, send)
        finally:
            await self._save_session(session)

    async def dispatch(self, request, call_next):
        session_id, verified = self._session_id(request.cookies.get(self.cookie_name))
        session_id = session_id or self._new_session_id()
        session = await self._load_session(session_id, verified)
        request.scope["session"] = session
        response = await call_next(request)
        await self._save_session(session)
        response.set_cookie(
            self.cookie_name,
            f"{session_id}.{self._signature(session_id)}",
            httponly=True,
            secure=self.secure,
            samesite="lax",
            path="/",
        )
        return response


class DefenderMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, defender, routes):
        super().__init__(app)
        self.defender = defender
        self.routes = routes
    

    async def dispatch(self, request, call_next):
        configuration = self.defender.get_configuration("presentation") or {}
        security = configuration.get("security_and_waf", {})
        authentication = configuration.get("authentication_guards", {})
        tls_required = security.get("tls_enabled", True)
        if tls_required and request.url.scheme != "https":
            return HTMLResponse(status_code=400, content="HTTPS required")

        # Esempio: decidiamo se accettare la richiesta in base al path
        request.session["ip"] = request.client.host
        if security.get("csrf_protection", True):
            request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
        #print(request.session)
        #request.session["user"] = await self.defender.whoami(session_id=request.session["id"],ip=request.session["ip"])
        
        path = request.url.path
        method = request.method

        if path.startswith("/static/"):
            return await call_next(request)
        
        data = route.resolve_route(self.routes, path, method)

        if not data:
            # Rifiutiamo la richiesta con un 403 Forbidden o 404
            return HTMLResponse(status_code=404)
        request.state.metadata = data.get('metadata', {})
        request.state.url = request.state.metadata.get('url_details', {})
        request.state.params = data.get('params', {})
        route_type = request.state.metadata.get("type")
        anonymous_route = route_type in {"authenticate", "activate", "reinstate"}
        authentication_data = request.session.get("authentication")
        user = (
            authentication_data.get("user", {})
            if isinstance(authentication_data, dict)
            else request.session.get("user", {})
        )
        authenticated = isinstance(user, dict) and bool(user.get("id"))
        if authentication.get("auth_required") and not authenticated and not anonymous_route:
            return HTMLResponse(status_code=401, content="Authentication required")

        csrf_required = security.get("csrf_protection", True)
        if csrf_required and method in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_token = request.headers.get("x-csrf-token")
            if not csrf_token and request.headers.get("content-type", "").startswith(
                "application/x-www-form-urlencoded"
            ):
                body = await request.body()
                fields = parse_qs(body.decode("utf-8", errors="replace"))
                csrf_token = fields.get("csrf_token", [None])[0]
            if not csrf_token or not hmac.compare_digest(
                csrf_token, request.session.get("csrf_token", "")
            ):
                return HTMLResponse(status_code=403, content="CSRF validation failed")
        # Logica di decisione (senza scomodare il resolve del router)
        authorized = await self.defender.authorized('presentation', session=request.session, action=method, resource=request.state.metadata.get('view'), location=request.state.metadata.get('path'))
                    
        if not authorized:
            # Rifiutiamo la richiesta con un 403 Forbidden o 404
            return HTMLResponse(status_code=404)

        # Se va bene, procediamo
        response = await call_next(request)
        if security.get("enable_hsts", tls_required) and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if csrf_required:
            response.headers["X-CSRF-Token"] = request.session["csrf_token"]
        content_security_policy = security.get("content_security_policy")
        if content_security_policy:
            response.headers["Content-Security-Policy"] = content_security_policy
        return response

# --- Configurazione Programmatica Attributi ---

def _fractional_flex(value, minimum_size):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)fr", str(value))
    if match is None:
        return ""
    factor = match.group(1)
    flex = "flex-1" if factor == "1" else f"flex-[{factor}]"
    return f"{flex} {minimum_size}"


mapping_attributes = {
    presentation.Attribute.WIDTH.value: lambda x: {
        "full": "w-full",
        "1/2": "w-1/2",
        "1/3": "w-1/3",
        "1/4": "w-1/4",
        "auto": "w-auto",
        True:f"w-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, "") or _fractional_flex(x, "min-w-40"),
    presentation.Attribute.HEIGHT.value: lambda x: {
        "full": "h-full",
        "1/2": "h-1/2",
        "1/3": "h-1/3",
        "1/4": "h-1/4",
        "auto": "h-auto",
        True:f"h-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, "") or _fractional_flex(x, "min-h-0"),
    presentation.Attribute.MAX_HEIGHT.value: lambda x: {
        True:f"max-h-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.MIN_HEIGHT.value: lambda x: {
        True:f"min-h-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.MAX_WIDTH.value: lambda x: {
        True:f"max-w-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.MIN_WIDTH.value: lambda x: {
        True:f"min-w-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.PADDING.value: lambda x: {
        False:f"p-[{x}]",
        True:" ".join(f"{p}-[{v}]" for p, v in zip(['pt','pb','pl','pr'] if len(x.split(',')) > 2 else ['py', 'px'], x.split(',')))
    }.get(True if ',' in x else False, ""),
    presentation.Attribute.MARGIN.value: lambda x: {
        False:f"m-[{x}]",
        True:" ".join(f"{p}-[{v}]" for p, v in zip(['mt','mb','ml','mr'] if len(x.split(',')) > 2 else ['my', 'mx'], x.split(',')))
    }.get(True if ',' in x else False, ""),
    presentation.Attribute.EXPAND.value: lambda x: {
        "true":"flex-1",
        "false":""
    }.get(x, "false"),
    presentation.Attribute.OVERFLOW.value: lambda x: {
        "auto":"overflow-auto",
        "hidden":"overflow-hidden",
        "visible":"overflow-visible",
        "scroll":"overflow-scroll",
        "clip":"overflow-clip",
        "none":"overflow-hidden",
    }.get(x, ""),
    presentation.Attribute.COLOR.value: lambda x: {
        "primary":"text-primary",
        "secondary":"text-secondary",
        "success":"text-success",
        "danger":"text-danger",
        "warning":"text-warning",
        "info":"text-info",
        "light":"text-light",
        "dark":"text-dark",
        "white":"text-white",
        "black":"text-black",
        "transparent":"text-transparent",
        True:f"text-[{x}]"
    }.get(True if '#' in x else x, ""),
    "color.border": lambda x: f"border-[{x}]" if '#' in x else "",
    presentation.Attribute.SPACING.value: lambda x: {
        True:f"gap-[{x}]"
    }.get(True if '%' in x or 'px' in x else False, ""),
    presentation.Attribute.JUSTIFY.value: lambda x: {
        "start": "justify-start",
        "end": "justify-end",
        "center": "justify-center",
        "between": "justify-between",
        "around": "justify-around",
        "evenly": "justify-evenly",
    }.get(x, ""),
    presentation.Attribute.ALIGN.value: lambda x: {
        "start": "items-start",
        "end": "items-end",
        "center": "items-center",
        "stretch": "items-stretch",
    }.get(x, ""),
    presentation.Attribute.POSITION.value: lambda x: {
        "static": "static",
        "relative": "relative",
        "absolute": "absolute",
        "fixed": "fixed",
        "sticky": "sticky",
    }.get(x, ""),
    presentation.Attribute.RADIUS.value: lambda x: {
        "none":"rounded-none",
        "small":"rounded-sm",
        "medium":"rounded-md",
        "large":"rounded-lg",
        "full":"rounded-full",
    }.get(x, ""),
    presentation.Attribute.BORDER.value: lambda x: {
        "none":"border-none",
        False:f"border-[{x}]",
        True:" ".join(f"{p}-[{v}]" for p, v in zip(['border-t','border-b','border-l','border-r'] if len(x.split(',')) > 2 else ['border-y', 'border-x'], x.split(',')))
    }.get(True if ',' in x else False, ""),
    presentation.Attribute.SHADOW.value: lambda x: {
        "none":"shadow-none",
        "min":"shadow-sm",
        "medium":"shadow-md",
        "large":"shadow-lg",
        "max":"shadow-xl",
    }.get(x, ""),
    presentation.Attribute.BACKGROUND.value: lambda x: {
        "none":"bg-transparent",
        False:f"bg-gradient-to-r from-[{x.split(',')[0]}] to-[{x.split(',')[-1]}]",
        True:f"bg-[{x}]"
    }.get((False if ',' in x else True) if '#' in x else x, ""),
    presentation.Attribute.MATTER.value: lambda x: {
        "glass":"backdrop-blur-md",
        "glass-min":"backdrop-blur-sm",
        "glass-medium":"backdrop-blur-lg",
        "glass-max":"backdrop-blur-xl",
    }.get(x, ""),
    presentation.Attribute.POINTER.value: lambda x: {
        "auto":"cursor-auto",
        "default":"cursor-default",
        "pointer":"cursor-pointer",
        "wait":"cursor-wait",
        "text":"cursor-text",
        "move":"cursor-move",
        "not-allowed":"cursor-not-allowed",
        "help":"cursor-help",
        "crosshair":"cursor-crosshair",
        "zoom-in":"cursor-zoom-in",
        "zoom-out":"cursor-zoom-out",
        "grab":"cursor-grab",
        "grabbing":"cursor-grabbing",
        "col-resize":"cursor-col-resize",
        "row-resize":"cursor-row-resize",
        "n-resize":"cursor-n-resize",
        "s-resize":"cursor-s-resize",
        "e-resize":"cursor-e-resize",
        "w-resize":"cursor-w-resize",
        "ne-resize":"cursor-ne-resize",
        "nw-resize":"cursor-nw-resize",
        "se-resize":"cursor-se-resize",
        "sw-resize":"cursor-sw-resize",
    }.get(x, ""),
    presentation.Attribute.TOP.value: lambda x: {
        True:f"top-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.BOTTOM.value: lambda x: {
        True:f"bottom-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.LEFT.value: lambda x: {
        True:f"left-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.RIGHT.value: lambda x: {
        True:f"right-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.SIZE.value: lambda x: {
        "min":"text-xs",
        "small":"text-sm",
        "medium":"text-base",
        "large":"text-lg",
        "max":"text-xl",
        True:f"text-[{x}]"
    }.get(True if '%' in x or 'px' in x or 'em' in x else x, ""),
    presentation.Attribute.UPPERCASE.value: lambda x: {
        "true":"uppercase",
        "false":""
    }.get(x, ""),
    presentation.Attribute.LOWERCASE.value: lambda x: {
        "true":"lowercase",
        "false":""
    }.get(x, ""),
    presentation.Attribute.TRUNCATE.value: lambda x: {
        "true":"truncate",
        "false":""
    }.get(x, ""),
    presentation.Attribute.FONT.value: lambda x: f"font-{x}",
    "spacing.text": lambda x: {
        "min":"tracking-tighter",
        "normal":"tracking-normal",
        "max":"tracking-wide",
        True:f"tracking-[{x}]"
    }.get(True if '%' in x or 'px' in x or 'em' in x else x, ""),
    "height.text": lambda x: f"leading-[{x}]", 
    "align.text": lambda x: {
        "left":"text-left",
        "center":"text-center",
        "right":"text-right",
    }.get(x, ""),
    presentation.Attribute.THICKNESS.value: lambda x: f"border-[{x}]" if '%' in x or 'px' in x else f"border-{x}" if 'px' in x else f"border-{x}",
}

_URL_SCHEMES = {
    "href": {"http", "https", "mailto", "tel"},
    "src": {"http", "https"},
    "action": {"http", "https"},
    "formaction": {"http", "https"},
    "xlink:href": {"http", "https"},
}


def _is_safe_url_attribute(name, value):
    normalized = re.sub(r"[\x00-\x20]+", "", str(value))
    scheme = urlsplit(normalized).scheme.casefold()
    return not scheme or scheme in _URL_SCHEMES.get(name, set())


def attrs(tag_key, input_data, classe=None):
    # 1. Prendi gli attributi grezzi passati dall'utente
    raw_attrs = dict(input_data.get("attrs", {}))
    if classe:
        raw_attrs["class"] = classe + " " + raw_attrs.get("class", "")
    
    classe = raw_attrs.get("class", "")


    if tag_key not in [presentation.Tag.TEXT.value] and (any(attr in raw_attrs for attr in [presentation.Attribute.JUSTIFY.value, presentation.Attribute.ALIGN.value,presentation.Attribute.EXPAND.value,presentation.Attribute.SPACING.value]) or tag_key in [presentation.Tag.ROW.value, presentation.Tag.COLUMN.value]):
        classe += " flex"

    if presentation.Attribute.COLOR.value in raw_attrs and presentation.Tag.DIVIDER.value == tag_key:
        raw_attrs["color.border"] = raw_attrs[presentation.Attribute.COLOR.value]
        raw_attrs.pop(presentation.Attribute.COLOR.value)

    '''if presentation.Attribute.THICKNESS.value in raw_attrs and tag_key == presentation.Tag.DIVIDER.value:
        tipo = raw_attrs.get(presentation.Attribute.TYPE.value, "horizontal")
        if tipo == "horizontal":
            raw_attrs[presentation.Attribute.HEIGHT.value] = raw_attrs[presentation.Attribute.THICKNESS.value]
        else:
            raw_attrs[presentation.Attribute.WIDTH.value] = raw_attrs[presentation.Attribute.THICKNESS.value]
        raw_attrs.pop(presentation.Attribute.THICKNESS.value)'''

    if presentation.Attribute.SPACING.value in raw_attrs and tag_key == presentation.Tag.TEXT.value:
        raw_attrs["spacing.text"] = raw_attrs[presentation.Attribute.SPACING.value]
        raw_attrs.pop(presentation.Attribute.SPACING.value)

    if presentation.Attribute.HEIGHT.value in raw_attrs and tag_key == presentation.Tag.TEXT.value:
        raw_attrs["height.text"] = raw_attrs[presentation.Attribute.HEIGHT.value]
        raw_attrs.pop(presentation.Attribute.HEIGHT.value)

    if presentation.Attribute.ALIGN.value in raw_attrs and tag_key == presentation.Tag.TEXT.value:
        raw_attrs["align.text"] = raw_attrs[presentation.Attribute.ALIGN.value]
        raw_attrs.pop(presentation.Attribute.ALIGN.value)

    is_svg = tag_key in [
        presentation.Tag.SVG.value, presentation.Tag.G.value, presentation.Tag.DEFS.value, presentation.Tag.RECT.value,
        presentation.Tag.CIRCLE.value, presentation.Tag.PATH.value, presentation.Tag.TEXT_SVG.value, presentation.Tag.TSPAN.value,
        presentation.Tag.STYLE_SVG.value, presentation.Tag.FILTER.value, presentation.Tag.FE_GAUSSIAN_BLUR.value,
        presentation.Tag.FE_OFFSET.value, presentation.Tag.FE_FLOOD.value, presentation.Tag.FE_COMPOSITE.value,
        presentation.Tag.FE_MERGE.value, presentation.Tag.FE_MERGE_NODE.value, presentation.Tag.ANIMATE.value,
        presentation.Tag.ANIMATE_TRANSFORM.value,
        presentation.Tag.STOP.value, presentation.Tag.POLYGON.value, presentation.Tag.LINE.value,
        presentation.Tag.FE_DROP_SHADOW.value, presentation.Tag.CLIP_PATH.value, presentation.Tag.PATTERN.value
    ]

    for attr in list(raw_attrs.keys()):
        if attr not in mapping_attributes:
            continue
        
        # In SVG we might want to keep width/height as attributes instead of classes
        if is_svg and attr in [presentation.Attribute.WIDTH.value, presentation.Attribute.HEIGHT.value]:
            continue

        valore = mapping_attributes[attr](raw_attrs[attr])
        if valore:
            classe += " " + valore
            raw_attrs.pop(attr)
    
    return {
        "class": classe,
        **{
            name: value
            for name, value in raw_attrs.items()
            if name != "class"
            and (
                name.casefold() not in _URL_SCHEMES
                or _is_safe_url_attribute(name.casefold(), value)
            )
        }
    }

def _html_children(inner):
    if isinstance(inner, (list, tuple)):
        return [
            child if isinstance(child, Markup) else markupsafe.escape(child)
            for child in inner
        ]
    if inner is None:
        return []
    return inner if isinstance(inner, Markup) else markupsafe.escape(inner)


def _render_select(x):
    attributes = attrs("input", x)
    selected_value = attributes.get("value")
    options = BeautifulSoup(
        "".join(str(child) for child in x.get("inner", [])),
        "html.parser",
    )
    for option in options.find_all("option"):
        value = option.get("value")
        if not option.get_text(strip=True) and not option.find(True):
            option.string = option.get("title") or value or ""
        if selected_value is not None:
            if value == str(selected_value):
                option["selected"] = ""
            else:
                option.attrs.pop("selected", None)
    attributes.pop("type", None)
    return htpy.select(**attributes)[Markup(str(options))]


def _render_editor(x):
    attributes = attrs("input", x, "w-full h-full resize-y font-mono")
    value = attributes.pop("value", None)
    content = BeautifulSoup(
        "".join(str(child) for child in x.get("inner", [])),
        "html.parser",
    ).get_text()
    return htpy.textarea(**attributes)[value if value is not None else content]


def _rendered_options(x):
    rendered = "".join(str(child) for child in x.get("inner", []))
    return BeautifulSoup(rendered, "html.parser").find_all("option", recursive=False)


def _render_tab_group(x):
    attributes = attrs("tab", x, "flex flex-col min-h-0")
    selected_value = attributes.pop("value", None)
    options = _rendered_options(x)
    if not options:
        return htpy.div(**attributes)[Markup("".join(str(child) for child in x.get("inner", [])))]

    group_id = attributes.get("id") or f"dsl-tabs-{uuid.uuid4().hex}"
    values = [option.get("value") or str(index) for index, option in enumerate(options)]
    if selected_value not in values:
        selected_value = values[0]
    attributes.update({"id": group_id, "data-tabs": "", "value": selected_value})

    tabs = []
    panels = []
    for index, (option, value) in enumerate(zip(options, values)):
        active = value == selected_value
        tab_id = f"{group_id}-tab-{index}"
        panel_id = f"{group_id}-panel-{index}"
        tab_class = (
            "border-blue-600 text-blue-700"
            if active
            else "border-transparent text-slate-600 hover:text-slate-900"
        )
        tabs.append(
            htpy.button(
                type="button",
                id=tab_id,
                role="tab",
                aria_selected=str(active).lower(),
                aria_controls=panel_id,
                data_tab_value=value,
                class_=f"border-b-2 px-3 py-2 text-sm {tab_class}",
            )[option.get("title") or option.get_text(" ", strip=True) or value]
        )
        content = Markup("".join(str(child) for child in option.contents))
        panels.append(
            htpy.div(
                id=panel_id,
                role="tabpanel",
                aria_labelledby=tab_id,
                data_tab_panel=value,
                hidden=not active,
                class_="flex-1 min-h-0 overflow-auto",
            )[content]
        )

    return htpy.div(**attributes)[
        htpy.div(role="tablist", class_="flex gap-2 border-b border-gray-200")[tabs],
        htpy.div(class_="flex-1 min-h-0")[panels],
    ]


def _render_navigation_tabs(x):
    attributes = attrs("navigation", x, "flex flex-wrap items-center gap-1 border-b border-gray-200")
    selected_value = attributes.pop("value", None)
    options = _rendered_options(x)
    if not options:
        return htpy.nav(**attributes)[Markup("".join(str(child) for child in x.get("inner", [])))]

    values = [option.get("value") or str(index) for index, option in enumerate(options)]
    if selected_value not in values:
        selected_value = values[0]
    attributes.update({"data-tab-list": "", "role": "tablist", "value": selected_value})

    tabs = []
    for index, (option, value) in enumerate(zip(options, values)):
        active = value == selected_value
        tab_class = (
            "border-blue-600 text-blue-700"
            if active
            else "border-transparent text-slate-600 hover:text-slate-900"
        )
        tab_attributes = {
            "type": "button",
            "role": "tab",
            "aria-selected": str(active).lower(),
            "data-tab-value": value,
            "value": value,
            "class": f"border-b-2 px-3 py-2 text-sm {tab_class}",
        }
        click = option.get("data-click")
        if click:
            tab_attributes["data-click"] = click
            tab_attributes["data-tab-event"] = ""
        tabs.append(
            htpy.button(**tab_attributes)[
                option.get("title") or option.get_text(" ", strip=True) or value
            ]
        )
    return htpy.nav(**attributes)[tabs]


def _render_modal_window(x):
    attrs = x.get("attrs", {})
    modal_id = attrs.get("id", "myModal")
    title_id = f"{modal_id}-title"
    return htpy.div(
        class_="dsl-modal fixed inset-0 z-50 hidden items-center justify-center p-4 target:flex",
        id=modal_id,
        role="dialog",
        aria_modal="true",
        aria_labelledby=title_id,
    )[
        htpy.a(
            href="#",
            class_="absolute inset-0 bg-black/50",
            aria_label="Chiudi finestra modale",
        ),
        htpy.div(
            class_="relative z-10 flex max-h-[90vh] w-full max-w-xl flex-col gap-4 overflow-y-auto rounded-md bg-white p-5 text-gray-900 shadow-xl"
        )[
            htpy.div(class_="flex items-center justify-between gap-4 border-b border-gray-200 pb-3")[(
                htpy.h2(class_="text-lg font-semibold", id=title_id)[attrs.get("title", "")],
                htpy.a(
                    href="#",
                    class_="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-100",
                    aria_label="Chiudi",
                )["Chiudi"],
            )],
            htpy.div(class_="min-h-0")[[Markup(i) for i in x["inner"]]],
        ],
    ]


def _render_navigation_palette(x):
    attrs = x.get("attrs", {})
    palette_id = attrs.get("id", "command-palette")
    title_id = f"{palette_id}-title"
    return htpy.div(class_="dsl-command-palette")[
        htpy.a(
            href=f"#{palette_id}",
            data_palette_open=palette_id,
            class_="fixed bottom-4 right-4 z-40 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-lg hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-400",
            aria_label="Apri i comandi",
        )["Comandi"],
        htpy.div(
            class_="dsl-modal fixed inset-0 z-50 hidden items-center justify-center p-4 target:flex",
            id=palette_id,
            role="dialog",
            aria_modal=True,
            aria_labelledby=title_id,
        )[
            htpy.a(
                href="#",
                class_="absolute inset-0 bg-black/50",
                aria_label="Chiudi palette",
            ),
            htpy.div(
                class_="relative z-10 flex max-h-[90vh] w-full max-w-xl flex-col gap-4 overflow-y-auto rounded-md bg-white p-5 text-gray-900 shadow-xl"
            )[
                htpy.div(class_="flex items-center justify-between gap-4 border-b border-gray-200 pb-3")[
                    htpy.h2(class_="text-lg font-semibold", id=title_id)["Comandi"],
                    htpy.a(
                        href="#",
                        class_="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-100",
                        aria_label="Chiudi",
                    )["Chiudi"],
                ],
                htpy.input(
                    type="search",
                    class_="w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm",
                    placeholder="Cerca comandi",
                    aria_label="Cerca comandi",
                    autocomplete="off",
                    data_palette_search="",
                ),
                htpy.div(
                    class_="flex max-h-[65vh] flex-col gap-1 overflow-y-auto",
                    data_palette_items="",
                )[[Markup(item) for item in x.get("inner", [])]],
                htpy.p(
                    class_="hidden text-sm text-slate-500",
                    data_palette_empty="",
                    hidden=True,
                )["Nessun comando trovato"],
            ],
        ],
    ]


class Adapter(PresentationAdapter):
    capabilities = {
        "tls": True,
        "min_tls_version": "TLSv1.2",
        "csrf": True,
        "authentication": ["session_cookie"],
        "rate_limiting": False,
    }

    # --- Configurazione Tag ---
    tags = {
        presentation.Tag.WINDOW.value: {
            "page": lambda x: htpy.html[
                htpy.head[
                    htpy.meta(charset="utf-8"),
                    htpy.meta(name="viewport", content="width=device-width, initial-scale=1"),
                    htpy.title[x.get("attrs", {}).get("title", "Today's menu")],
                    #htpy.link(rel="stylesheet", href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"),
                    htpy.link(rel="stylesheet", href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css"),
                    htpy.link(rel="stylesheet", href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css"),
                    htpy.script(src="https://cdn.tailwindcss.com"),
                ],
                htpy.body(**attrs(presentation.Tag.WINDOW.value, x, "h-screen"))[
                    [Markup(i) for i in x['inner']],
                    htpy.script(src="static/js/grid.js"),
                    htpy.script(src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"),
                    htpy.script(src="static/js/dsl.js"),

                    htpy.script[Markup("""
                        (function() {
                            const selectedScopeFor = (value) => {
                                if (value.startsWith('src/framework/')) return 'framework';
                                if (value.startsWith('src/infrastructure/')) return 'infrastructure';
                                return 'application';
                            };
                            const updateTabs = (root, value) => {
                                if (!root || !value) return;
                                root.setAttribute('value', value);
                                root.querySelectorAll('[role="tab"][data-tab-value]').forEach((tab) => {
                                    if (tab.closest('[data-tabs], [data-tab-list]') !== root) return;
                                    const active = tab.getAttribute('data-tab-value') === value;
                                    tab.setAttribute('aria-selected', String(active));
                                    tab.classList.toggle('border-blue-600', active);
                                    tab.classList.toggle('text-blue-700', active);
                                    tab.classList.toggle('border-transparent', !active);
                                    tab.classList.toggle('text-slate-600', !active);
                                });
                                root.querySelectorAll('[data-tab-panel]').forEach((panel) => {
                                    if (panel.closest('[data-tabs], [data-tab-list]') !== root) return;
                                    panel.hidden = panel.getAttribute('data-tab-panel') !== value;
                                });
                            };
                            const setWorkspaceScope = (scope) => {
                                const workspace = document.getElementById('workspace-editors');
                                if (!workspace || !['application', 'framework', 'infrastructure'].includes(scope)) return;
                                updateTabs(workspace, scope);
                            };
                            const syncTerminalSelection = (value) => {
                                if (typeof value !== 'string') return;
                                const select = document.getElementById('select');
                                const options = select ? Array.from(select.options) : [];
                                const selectedOption = options.find((option) => option.value === value);
                                if (selectedOption) {
                                    options.forEach((option) => {
                                        const selected = option === selectedOption;
                                        option.selected = selected;
                                        if (selected) option.setAttribute('selected', '');
                                        else option.removeAttribute('selected');
                                    });
                                    select.value = selectedOption.value;
                                    select.setAttribute('value', value);
                                }
                                setWorkspaceScope(selectedScopeFor(value));
                            };
                            const syncEventSelection = (event) => {
                                if (event.name !== 'terminal:select') return;
                                const value = event.payload ?? event.value;
                                syncTerminalSelection(typeof value === 'string' ? value : value?.value);
                            };
                            const initialSelect = document.getElementById('select');
                            const initialValue = initialSelect && (initialSelect.value || initialSelect.getAttribute('value'));
                            if (initialValue) {
                                syncTerminalSelection(initialValue);
                            } else {
                                const workspace = document.getElementById('workspace-editors');
                                if (workspace) setWorkspaceScope(workspace.getAttribute('value'));
                            }

                            const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/reactive`);
                            ws.addEventListener('open', () => {
                                const pendingEvent = sessionStorage.getItem('dsl-pending-palette-event');
                                if (!pendingEvent) return;
                                sessionStorage.removeItem('dsl-pending-palette-event');
                                syncEventSelection(JSON.parse(pendingEvent));
                                ws.send(pendingEvent);
                            });
                            ws.onmessage = (e) => {
                                console.log(e.data);
                                const data = JSON.parse(e.data);
                                if (data.type === 'update') {
                                    const el = document.getElementById(data.id);
                                    if (el) {
                                        el.outerHTML = data.html;
                                        const updated = document.getElementById(data.id);
                                        if (data.id === 'workspace-editors') {
                                            const select = document.getElementById('select');
                                            const selectedFile = select && select.value;
                                            setWorkspaceScope(
                                                selectedFile
                                                    ? selectedScopeFor(selectedFile)
                                                    : updated && updated.getAttribute('value'),
                                            );
                                        } else if (updated && updated.tagName === 'SELECT') {
                                            syncTerminalSelection(updated.getAttribute('value') || updated.value);
                                        }
                                    }
                                }
                            };

                            document.addEventListener('click', (e) => {
                                const tab = e.target.closest('[data-tab-value]');
                                if (!tab) return;
                                const root = tab.closest('[data-tabs], [data-tab-list]');
                                if (root) updateTabs(root, tab.getAttribute('data-tab-value'));
                            });

                            // Mappa eventi DOM -> attributo data-* sul nodo
                            const EVENT_ATTRS = {
                                'click':      'data-click',
                                'dblclick':   'data-dblclick',
                                'mouseover':  'data-mouseover',
                                'mouseout':   'data-mouseout',
                                'keydown':    'data-keydown',
                                'keyup':      'data-keyup',
                                'keypress':   'data-keypress',
                                'change':     'data-change',
                            };

                            const eventPayload = (el, domEvent) => {
                                if (el.hasAttribute('form')) {
                                    const payload = {};
                                    const form = document.getElementById(el.getAttribute('form'));
                                    if (form) {
                                        form.querySelectorAll('input[id], textarea[id], select[id]').forEach((field) => {
                                            payload[field.name || field.id] = field.value ?? '';
                                        });
                                    }
                                    return payload;
                                }
                                if (el.hasAttribute('data-tab-event')) {
                                    return el.getAttribute('value') || '';
                                }
                                if (domEvent === 'change' || (domEvent !== 'click' && 'value' in el)) {
                                    return el.value;
                                }
                                if (el.hasAttribute('value')) return {value: el.getAttribute('value')};
                                return el.id || '';
                            };

                            Object.entries(EVENT_ATTRS).forEach(([domEvent, dataAttr]) => {
                                document.addEventListener(domEvent, (e) => {
                                    const el = e.target.closest(`[${dataAttr}]`);
                                    if (!el || el.closest('[data-palette-items]')) return;
                                    const trigger = el.getAttribute(dataAttr);
                                    if (!trigger) return;

                                    if (domEvent === 'click') {
                                        const route = el.getAttribute('action') ||
                                            (el.tagName === 'A' ? el.getAttribute('href') : null);
                                        if (route) {
                                            if (route.startsWith('#')) return;
                                            if (trigger === 'terminal:select') {
                                                const value = el.hasAttribute('value')
                                                    ? el.getAttribute('value')
                                                    : el.textContent.trim();
                                                sessionStorage.setItem(
                                                    'dsl-pending-palette-event',
                                                    JSON.stringify({type: 'event', name: trigger, value}),
                                                );
                                            }
                                            e.preventDefault();
                                            location.assign(route);
                                            return;
                                        }
                                    }

                                    const payload = eventPayload(el, domEvent);
                                    if (trigger === 'terminal:select') {
                                        syncTerminalSelection(typeof payload === 'string' ? payload : payload?.value);
                                    }
                                    ws.send(JSON.stringify({
                                        type: 'event',
                                        name: trigger,
                                        payload,
                                    }));
                                });
                            });

                            document.addEventListener('click', (e) => {
                                const el = e.target.closest(
                                    'button[action^="#"], a[data-click][href^="#"]',
                                );
                                if (!el) return;
                                const route = el.getAttribute('action') || el.getAttribute('href');
                                const modal = document.getElementById(route.slice(1));
                                if (modal && modal.matches('.dsl-modal')) {
                                    e.preventDefault();
                                    location.hash = modal.id;
                                }
                            });

                            document.addEventListener('click', (e) => {
                                const el = e.target.closest('button[action]');
                                if (!el || el.hasAttribute('data-click') || el.closest('[data-palette-items]')) return;
                                const route = el.getAttribute('action');
                                if (!route || route.startsWith('#')) return;
                                e.preventDefault();
                                location.assign(route);
                            });

                            document.addEventListener('click', (e) => {
                                const command = e.target.closest('[data-palette-items] button');
                                if (!command) return;
                                const route = command.getAttribute('action') || command.getAttribute('route');
                                if (route && route.startsWith('#')) return;

                                const trigger = command.getAttribute('data-click');
                                const value = command.hasAttribute('value')
                                    ? command.getAttribute('value')
                                    : command.textContent.trim();
                                let event = null;
                                if (trigger && !route) {
                                    event = {
                                        type: 'event',
                                        name: trigger,
                                        payload: command.hasAttribute('value') ? {value} : value,
                                    };
                                } else if (trigger === 'terminal:select') {
                                    event = {type: 'event', name: trigger, value};
                                }
                                if (route) {
                                    if (event) {
                                        sessionStorage.setItem(
                                            'dsl-pending-palette-event',
                                            JSON.stringify(event),
                                        );
                                    }
                                    location.assign(route);
                                } else if (event) {
                                    syncEventSelection(event);
                                    ws.send(JSON.stringify(event));
                                }
                            });

                            document.addEventListener('click', (e) => {
                                const trigger = e.target.closest('[data-palette-open]');
                                if (!trigger) return;
                                const palette = document.getElementById(trigger.getAttribute('data-palette-open'));
                                const search = palette && palette.querySelector('[data-palette-search]');
                                if (search) window.requestAnimationFrame(() => search.focus());
                            });

                            document.addEventListener('input', (e) => {
                                const search = e.target.closest('[data-palette-search]');
                                if (!search) return;
                                const palette = search.closest('.dsl-modal');
                                const items = palette && palette.querySelector('[data-palette-items]');
                                if (!items) return;
                                const query = search.value.trim().toLocaleLowerCase();
                                let visibleCount = 0;
                                Array.from(items.children).forEach((item) => {
                                    item.hidden = !item.textContent.toLocaleLowerCase().includes(query);
                                    if (!item.hidden) visibleCount += 1;
                                });
                                const empty = palette.querySelector('[data-palette-empty]');
                                if (empty) empty.hidden = visibleCount > 0;
                            });

                            document.addEventListener('keydown', (e) => {
                                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                                    const trigger = document.querySelector('[data-palette-open]');
                                    if (trigger) {
                                        e.preventDefault();
                                        trigger.click();
                                    }
                                }
                                if (e.key === 'Escape' && document.querySelector('.dsl-modal:target')) {
                                    e.preventDefault();
                                    location.hash = '';
                                }
                            });
                        })();
                    """)]
                ]
            ],
            "modal": _render_modal_window,
            "dialog": _render_modal_window,
            "still": lambda x: htpy.div(class_=f"offcanvas offcanvas-{x.get('attrs', {}).get('alignment-content', 'start')}", tabindex="-1", id=x.get('attrs', {}).get('id', 'offcanvasMenu'), aria_labelledby=f"{x.get('attrs', {}).get('id', 'offcanvasMenu')}Label")[
                htpy.div(class_="offcanvas-header")[
                    htpy.h5(class_="offcanvas-title", id=f"{x.get('attrs', {}).get('id', 'offcanvasMenu')}Label")[x.get("attrs", {}).get("title", "")],
                    htpy.button(type="button", class_="btn-close", data_bs_dismiss="offcanvas", aria_label="Close")
                ],
                htpy.div(class_="offcanvas-body")[[Markup(i) for i in x['inner']]]
            ],
            "embed": lambda x: htpy.div(**attrs("embed", x))[[Markup(i) for i in x['inner']]],
        },
        presentation.Tag.GRID.value: {
            "grid": lambda x: htpy.div(**attrs("grid", x, "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3"))[[Markup(i) for i in x['inner']]],
        },
        presentation.Tag.OPTION.value: {
            "option": lambda x: htpy.option(**attrs("option", x))[[Markup(i) for i in x['inner']]],
        },
        presentation.Tag.TEXT.value: {
            "text": lambda x: htpy.span(**attrs("text", x,"text-xs"))[[Markup(i) for i in x['inner']]],
            "input": lambda x: htpy.span(**attrs("input", x, 'input-group-text'))[[Markup(i) for i in x['inner']]],
            "h1": lambda x: htpy.h1(**attrs("text", x, "text-6xl"))[[Markup(i) for i in x['inner']]],
            "h2": lambda x: htpy.h2(**attrs("text", x, "text-5xl"))[[Markup(i) for i in x['inner']]],
            "h3": lambda x: htpy.h3(**attrs("text", x, "text-4xl"))[[Markup(i) for i in x['inner']]],
            "h4": lambda x: htpy.h4(**attrs("text", x, "text-3xl"))[[Markup(i) for i in x['inner']]],
            "h5": lambda x: htpy.h5(**attrs("text", x, "text-2xl"))[[Markup(i) for i in x['inner']]],
            "h6": lambda x: htpy.h6(**attrs("text", x, "text-xl"))[[Markup(i) for i in x['inner']]],
            "p": lambda x: htpy.p(**attrs("text", x, "text-base"))[[Markup(i) for i in x['inner']]],
            "span": lambda x: htpy.span(**attrs("text", x, "text-transparent bg-clip-text"))[[Markup(i) for i in x['inner']]],
            "mark": lambda x: htpy.mark(**attrs("mark", x, "text-transparent bg-clip-text"))[[Markup(i) for i in x['inner']]],
            "code": lambda x: htpy.code(**attrs("code", x))[[Markup(i) for i in x['inner']]],
            "pre": lambda x: htpy.pre(**attrs("pre", x))[[Markup(i) for i in x['inner']]],
            "blockquote": lambda x: htpy.blockquote(**attrs("blockquote", x))[[Markup(i) for i in x['inner']]],
            "cite": lambda x: htpy.cite(**attrs("cite", x))[[Markup(i) for i in x['inner']]],
            "abbr": lambda x: htpy.abbr(**attrs("abbr", x))[[Markup(i) for i in x['inner']]],
            "time": lambda x: htpy.time(**attrs("time", x))[[Markup(i) for i in x['inner']]],
        },
        presentation.Tag.INPUT.value: {
            "input": lambda x: htpy.input(type="text", **attrs("input", x)),
            "select": _render_select,
            "editor": _render_editor,
            "textarea": lambda x: htpy.textarea(type="textarea", **attrs("input", x)),
            "text": lambda x: htpy.input(type="text", **attrs("input", x)), 
            "password": lambda x: htpy.input(type="password", **attrs("input", x)),
            "switch": lambda x: htpy.input(type="checkbox", **attrs("input", x)), 
            "checkbox": lambda x: htpy.input(type="checkbox", **attrs("input", x)),
            "radio": lambda x: htpy.input(type="radio", **attrs("input", x)), 
            "range": lambda x: htpy.input(type="range", **attrs("input", x)),
            "color": lambda x: htpy.input(type="color", **attrs("input", x)), 
            "date": lambda x: htpy.input(type="date", **attrs("input", x)), 
            "month": lambda x: htpy.input(type="month", **attrs("input", x)), 
            "week": lambda x: htpy.input(type="week", **attrs("input", x)), 
            "time": lambda x: htpy.input(type="time", **attrs("input", x)),
            "number": lambda x: htpy.input(type="number", **attrs("input", x)), 
            "email": lambda x: htpy.input(type="email", **attrs("input", x)), 
            "url": lambda x: htpy.input(type="url", **attrs("input", x)),
            "search": lambda x: htpy.input(type="search", **attrs("input", x)),
            "tel": lambda x: htpy.input(type="tel", **attrs("input", x)), 
            "dropdown": lambda x: htpy.select(**attrs("input", x)),
            "file": lambda x: htpy.input(type="file", **attrs("input", x)),
            "hidden": lambda x: htpy.input(type="hidden", **attrs("input", x)),
        },
        presentation.Tag.ACTION.value: {
            "form": lambda x: htpy.form(**attrs("form", x))[[Markup(i) for i in x['inner']]],
            "action": lambda x: htpy.button(**attrs("action", x, "px-4 py-2 hover:opacity-80 transition-opacity"))[[Markup(i) for i in x['inner']]], 
            "button": lambda x: htpy.button(**attrs("button", x, "px-4 py-2 hover:opacity-80 transition-opacity"))[[Markup(i) for i in x['inner']]], 
            "submit": lambda x: htpy.button(type="submit",**attrs("submit", x, "btn btn-primary"))[[Markup(i) for i in x['inner']]], 
            "reset": lambda x: htpy.button(type="reset",**attrs("reset", x, "btn btn-secondary"))[[Markup(i) for i in x['inner']]],
            "link": lambda x: htpy.a(
                **attrs("link", {**x, "attrs": {
                    **{k: v for k, v in x.get("attrs", {}).items() if k not in ("route", "action", "href")},
                    "href": x.get("attrs", {}).get("route") or x.get("attrs", {}).get("action") or x.get("attrs", {}).get("href", "#")
                }}, "btn link")
            )[[Markup(i) for i in x['inner']]],
        },
        presentation.Tag.MEDIA.value: {
            "media": lambda x: htpy.img(**attrs("media", x)), 
            "img": lambda x: htpy.img(**attrs("img", x)), 
            "video": lambda x: htpy.video(**attrs("video", x)), 
            "audio": lambda x: htpy.audio(**attrs("audio", x)), 
            "embed": lambda x: htpy.embed(**attrs("embed", x)),
            "carousel": lambda x: htpy.div(".carousel"), 
            "map": lambda x: htpy.div(".map"), 
            "icon": lambda x: htpy.i(".bi")
        },
        presentation.Tag.CONTAINER.value: {
            "container": lambda x: htpy.div(**attrs("container", x))[[Markup(i) for i in x['inner']]], 
            "fluid": lambda x: htpy.div(**attrs("fluid", x))[[Markup(i) for i in x['inner']]]
        },
        presentation.Tag.ROW.value: {
            "row": lambda x: htpy.div(**attrs("row", x, "flex-row"))[[Markup(i) for i in x['inner']]]
        },
        presentation.Tag.COLUMN.value: { 
            "column": lambda x: htpy.div(**attrs("column", x, "flex-col"))[[Markup(i) for i in x['inner']]]
        },
        presentation.Tag.STACK.value: { 
            "stack": lambda x: htpy.div(".position-relative")[[Markup(i) for i in x['inner']]]
        },
        presentation.Tag.DIVIDER.value: {
            "divider": lambda x: htpy.hr(**attrs(presentation.Tag.DIVIDER.value, x,"w-full border-left")),
            "vertical": lambda x: htpy.div(**attrs(presentation.Tag.DIVIDER.value, x,"h-full border-top")),
            "horizontal": lambda x: htpy.hr(**attrs(presentation.Tag.DIVIDER.value, x,"w-full border-left"))
        },
        presentation.Tag.ICON.value: { 
            "icon": lambda x: htpy.i(**attrs("icon", x)),
            "bi": lambda x: htpy.i(**attrs("icon", x)),
            "fa": lambda x: htpy.i(**attrs("icon", x)),
        },
        presentation.Tag.NAVIGATION.value: {
            "navigation": lambda x: htpy.nav(**attrs("navigation", x,""))[[Markup(i) for i in x['inner']]],
            "palette": _render_navigation_palette,
            "bar": lambda x: htpy.nav(**attrs("bar", x,"nav"))[[Markup(i) for i in x['inner']]],
            "app": lambda x: htpy.nav(**attrs("app", x,""))[[Markup(i) for i in x['inner']]],
            "breadcrumb": lambda x: htpy.nav(**attrs("breadcrumb", x,"breadcrumb"))[[Markup(i) for i in x['inner']]],
            "tab": _render_navigation_tabs,
            "tabs": _render_navigation_tabs,
        },
        presentation.Tag.GROUP.value: {
            "input": lambda x: htpy.div(**attrs("input", x,'input-group'))[[Markup(i) for i in x['inner']]],
            "action": lambda x: htpy.div(**attrs("button", x,'btn-group'))[[Markup(i) for i in x['inner']]],
            "card": lambda x: htpy.div(**attrs("card", x,'card-group'))[[Markup(i) for i in x['inner']]],
            "list": lambda x: htpy.ul(**attrs("group", x,'flex-col'))[[Markup(htpy.li[i]) for i in x['inner']]],
            "tab": _render_tab_group,
            "dropdown": lambda x: htpy.div(**attrs("dropdown", x,'dropdown'))[[Markup(i) for i in x['inner']]],
        },
        presentation.Tag.CANVAS.value: {
            "canvas": lambda x: htpy.canvas(**attrs("canvas", x))[[Markup(i) for i in x['inner']]]
        },
        presentation.Tag.SVG.value: {"svg": lambda x: htpy.Element("svg")(**attrs(presentation.Tag.SVG.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.G.value: {"g": lambda x: htpy.Element("g")(**attrs(presentation.Tag.G.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.DEFS.value: {"defs": lambda x: htpy.Element("defs")(**attrs(presentation.Tag.DEFS.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.STYLE_SVG.value: {
            "style_svg": lambda x: htpy.Element("style")(**attrs(presentation.Tag.STYLE_SVG.value, x))[[Markup(i) for i in x['inner']]],
            "text/css": lambda x: htpy.Element("style")(**attrs(presentation.Tag.STYLE_SVG.value, x))[[Markup(i) for i in x['inner']]]
        },
        presentation.Tag.RECT.value: {"rect": lambda x: htpy.Element("rect")(**attrs(presentation.Tag.RECT.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.CIRCLE.value: {"circle": lambda x: htpy.Element("circle")(**attrs(presentation.Tag.CIRCLE.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.PATH.value: {"path": lambda x: htpy.Element("path")(**attrs(presentation.Tag.PATH.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.TEXT_SVG.value: {"text_svg": lambda x: htpy.Element("text")(**attrs(presentation.Tag.TEXT_SVG.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.TSPAN.value: {"tspan": lambda x: htpy.Element("tspan")(**attrs(presentation.Tag.TSPAN.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FILTER.value: {"filter": lambda x: htpy.Element("filter")(**attrs(presentation.Tag.FILTER.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FE_GAUSSIAN_BLUR.value: {"fegaussianblur": lambda x: htpy.Element("feGaussianBlur")(**attrs(presentation.Tag.FE_GAUSSIAN_BLUR.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FE_OFFSET.value: {"feoffset": lambda x: htpy.Element("feOffset")(**attrs(presentation.Tag.FE_OFFSET.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FE_FLOOD.value: {"feflood": lambda x: htpy.Element("feFlood")(**attrs(presentation.Tag.FE_FLOOD.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FE_COMPOSITE.value: {"fecomposite": lambda x: htpy.Element("feComposite")(**attrs(presentation.Tag.FE_COMPOSITE.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FE_MERGE.value: {"femerge": lambda x: htpy.Element("feMerge")(**attrs(presentation.Tag.FE_MERGE.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FE_MERGE_NODE.value: {"femergenode": lambda x: htpy.Element("feMergeNode")(**attrs(presentation.Tag.FE_MERGE_NODE.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.ANIMATE.value: {"animate": lambda x: htpy.Element("animate")(**attrs(presentation.Tag.ANIMATE.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.ANIMATE_TRANSFORM.value: {"animatetransform": lambda x: htpy.Element("animateTransform")(**attrs(presentation.Tag.ANIMATE_TRANSFORM.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.STOP.value: {"stop": lambda x: htpy.Element("stop")(**attrs(presentation.Tag.STOP.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.LINEAR_GRADIENT.value: {"lineargradient": lambda x: htpy.Element("linearGradient")(**attrs(presentation.Tag.LINEAR_GRADIENT.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.RADIAL_GRADIENT.value: {"radialgradient": lambda x: htpy.Element("radialGradient")(**attrs(presentation.Tag.RADIAL_GRADIENT.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.POLYGON.value: {"polygon": lambda x: htpy.Element("polygon")(**attrs(presentation.Tag.POLYGON.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.LINE.value: {"line": lambda x: htpy.Element("line")(**attrs(presentation.Tag.LINE.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.FE_DROP_SHADOW.value: {"fedropshadow": lambda x: htpy.Element("feDropShadow")(**attrs(presentation.Tag.FE_DROP_SHADOW.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.CLIP_PATH.value: {"clippath": lambda x: htpy.Element("clipPath")(**attrs(presentation.Tag.CLIP_PATH.value, x))[[Markup(i) for i in x['inner']]]},
        presentation.Tag.PATTERN.value: {"pattern": lambda x: htpy.Element("pattern")(**attrs(presentation.Tag.PATTERN.value, x))[[Markup(i) for i in x['inner']]]},
    }

    def __init__(self, loader: Loader, defender: Defender, messenger: Messenger, authenticator: Authenticator, storekeeper: Storekeeper, **constants):
        super().__init__(loader, defender, messenger, authenticator, **constants)
        self.storekeeper = storekeeper
        self.ssh = {}
        cwd = os.getcwd()
        self.routes_static=[
            Mount('/static', app=StaticFiles(directory=f'{cwd}/public/'), name="static"),
            #WebSocketRoute("/messenger", self.websocket, name="messenger"),
            #WebSocketRoute("/ssh", self.websocketssh, name="ssh"),
        ]

        presentation_configuration = {}
        if self.defender is not None and hasattr(self.defender, "get_configuration"):
            presentation_configuration = self.defender.get_configuration("presentation") or {}
        security_configuration = presentation_configuration.get("security_and_waf", {})
        tls_required = security_configuration.get("tls_enabled", True)
        
        self.middleware_static = [
            Middleware(
                ServerSessionMiddleware,
                cookie_name="session_state",
                secret_key=self._session_secret(),
                storekeeper=self.storekeeper,
                secure=bool(tls_required or self.config.get("ssl_certfile")),
            ),
            Middleware(
                CORSMiddleware,
                allow_origins=self.config.get('cors_origins', []),
                allow_methods=self.config.get('cors_methods', ['GET', 'POST', 'OPTIONS']),
                allow_headers=self.config.get('cors_headers', ['Content-Type']),
                allow_credentials=bool(self.config.get('cors_credentials', False)),
            ),
            Middleware(DefenderMiddleware, defender=self.defender,routes=self.routes),
            #Middleware(NoCacheMiddleware),
            #Middleware(CSRFMiddleware, secret=self._session_secret()),
        ]
        self.active_websockets = {} # sid -> [websocket]
        self._session_controllers = {}
        self._session_views = {}
        self.validate_adapter()

    def configure_port(self, configuration):
        """Applica la configurazione globale validata della Port presentation."""
        self.port_configuration = configuration
        cors_policy = configuration["cors_policy"]

        self.middleware_static[1] = Middleware(
            CORSMiddleware,
            allow_origins=(
                cors_policy.get("allowed_origins", [])
                if cors_policy["enabled"] else []
            ),
            allow_methods=cors_policy.get("allowed_methods", ["GET", "POST", "OPTIONS"]),
            allow_headers=cors_policy.get("allowed_headers", ["Content-Type"]),
            allow_credentials=bool(cors_policy.get("allow_credentials", False)),
            max_age=cors_policy.get("max_age_seconds", 600),
        )

    def _session_secret(self):
        config = getattr(getattr(self, 'loader', None), 'current_config', {})
        defender = config.get('manager', {}).get('defender', {}) if isinstance(config, dict) else {}
        secret = defender.get('key') if isinstance(defender, dict) else None
        if not secret:
            manager = self.config.get('manager', {})
            defender = manager.get('defender', {}) if isinstance(manager, dict) else {}
            secret = defender.get('key') if isinstance(defender, dict) else None
        secret = secret or self.config.get('session_key')
        if not secret:
            if self.config.get('dev'):
                return secrets.token_urlsafe(32)
            raise RuntimeError("Configurare manager.defender.key o session_key per l'adapter Starlette")
        return secret

    async def http_exception_handler(self,request, exc):
        #html = await self.mount_view("/"+str(exc.status_code),identifier = request.cookies.get('session_identifier', secrets.token_urlsafe(16)))
        return JSONResponse({"errore": exc.detail}, status_code=exc.status_code)
        #return HTMLResponse(content=html, status_code=exc.status_code)
        
    async def _run_runtime(self):
        loop = asyncio.get_running_loop()
        security = (self.defender.get_configuration("presentation") or {}).get(
            "security_and_waf", {}
        )
        tls_required = security.get("tls_enabled", True)
        minimum_tls_version = security.get("min_tls_version", "TLSv1.2")
        if tls_required and not {
            "ssl_keyfile",
            "ssl_certfile",
        }.issubset(self.config):
            missing_certificates = [
                setting
                for setting in ("ssl_keyfile", "ssl_certfile")
                if setting not in self.config
            ]
            logger.error(
                "Avvio Starlette rifiutato dalla policy TLS",
                host=self.config.get("host", "127.0.0.1"),
                port=self.config.get("port", 8000),
                missing_certificates=missing_certificates,
            )
            raise RuntimeError(
                "TLS richiesto dalla policy: configurare ssl_keyfile e ssl_certfile"
            )
        self.routes_static += [
            WebSocketRoute("/reactive", self.render_reactive, name="reactive")
        ]
        await self.mount_route(self.routes_static) # 'routes' deve essere accessibile qui
        # Inizializza l'applicazione Starlette con rotte e middleware
        self.app = Starlette(debug=False, routes=self.routes_static, exception_handlers={HTTPException: self.http_exception_handler}, middleware=self.middleware_static)
        #print(di['message'][0].logger,'###########')
        # Parametri di configurazione base per Uvicorn
        uvicorn_config_params = {
            "app": self.app,
            "log_config": _uvicorn_log_config(),
            "host": self.config.get('host', '127.0.0.1'),
            "port": int(self.config.get('port', 8000)),
            "use_colors": True,
            "reload": False, # `reload=True` non è compatibile con create_task in questo modo
            "loop": loop,
            #'log_level':"trace"
            #'log_config':None
        }
        # Aggiunge i parametri SSL se presenti
        if 'ssl_keyfile' in self.config and 'ssl_certfile' in self.config:
            #await messenger.post(domain='debug', message="SSL abilitato.")
            uvicorn_config_params['ssl_keyfile'] = self.config['ssl_keyfile']
            uvicorn_config_params['ssl_certfile'] = self.config['ssl_certfile']
        else:
            #await messenger.post(domain='debug', message="SSL disabilitato.")
            pass

        # Costruisci la stringa della porta
        port_str = ""
        if 'port' in uvicorn_config_params:
            port_str = f":{uvicorn_config_params['port']}"

        # Costruisci l'URL
        self.url = f"http{'s' if 'ssl_certfile' in self.config else ''}://{uvicorn_config_params['host']}{port_str}"
        config = Config(**uvicorn_config_params)
        config.load()
        if config.ssl is not None:
            config.ssl.minimum_version = {
                "TLSv1.2": ssl.TLSVersion.TLSv1_2,
                "TLSv1.3": ssl.TLSVersion.TLSv1_3,
            }[minimum_tls_version]
        self.server = Server(config)
        return await self.server.serve()

    async def _shutdown_runtime(self):
        if hasattr(self, 'server'):
            self.server.should_exit = True
        sockets = [socket for group in self.active_websockets.values() for socket in group]
        for websocket in sockets:
            await websocket.close()
        self.active_websockets.clear()
        
    @staticmethod
    def _apply_authentication_result(request, result):
        if not flow.is_result(result):
            request.session["errors"] = ["Risultato di autenticazione non valido"]
            return False
        if not flow.check(result):
            request.session["errors"] = [str(flow.output(result))]
            return False

        session_data = flow.output(result)
        to_dict = getattr(session_data, "to_dict", None)
        if callable(to_dict):
            session_data = to_dict()
        if not isinstance(session_data, dict):
            request.session["errors"] = ["La sessione restituita non è valida"]
            return False

        request.session.update(session_data)
        request.session.pop("errors", None)
        authentication_data = session_data.get("authentication", {})
        user = (
            authentication_data.get("user")
            if isinstance(authentication_data, dict)
            else None
        )
        if isinstance(user, dict) and user:
            request.session["user"] = user
        else:
            request.session.pop("user", None)
        return True

    async def signout(self,request):
        # Determina le credenziali in base al metodo HTTP
        match request.method:
            case 'GET':
                credentials = dict(request.query_params)
            case 'POST':
                credentials = dict(await request.form())
            case _:
                return RedirectResponse('/', status_code=405)

        result = await self.authenticator.invalidate(request.session, **credentials)
        self._apply_authentication_result(request, result)

        # Crea la risposta di reindirizzamento
        return RedirectResponse(request.session.get("previous_url", "/"), status_code=303)

    async def signin(self, request):
        # Determina le credenziali in base al metodo HTTP
        match request.method:
            case 'GET':
                credentials = dict(request.query_params)
            case 'POST':
                credentials = dict(await request.form())
            case _:
                return RedirectResponse('/', status_code=405)

        result = await self.authenticator.authenticate(request.session, **credentials)
        self._apply_authentication_result(request, result)

        # Crea la risposta di reindirizzamento
        return RedirectResponse(request.session.get("previous_url", "/"), status_code=303)
    
    async def signup(self, request):
        # Determina le credenziali in base al metodo HTTP
        match request.method:
            case 'GET':
                credentials = dict(request.query_params)
            case 'POST':
                credentials = dict(await request.form())
            case _:
                return RedirectResponse('/', status_code=405)

        result = await self.authenticator.activate(request.session, **credentials)
        self._apply_authentication_result(request, result)

        # Crea la risposta di reindirizzamento
        return RedirectResponse(request.session.get("previous_url", "/"), status_code=303)

    async def signaid(self, request):
        # Determina le credenziali in base al metodo HTTP
        match request.method:
            case 'GET':
                credentials = dict(request.query_params)
            case 'POST':
                credentials = dict(await request.form())
            case _:
                return RedirectResponse('/', status_code=405)

        result = await self.authenticator.regenerate(request.session, **credentials)
        self._apply_authentication_result(request, result)

        # Crea la risposta di reindirizzamento
        return RedirectResponse(request.session.get("previous_url", "/"), status_code=303)

    async def action(self, request, **constants):
        match request.method:
            case 'GET':
                return JSONResponse(dict(request.query_params))
                
            case 'POST':
                form = await request.form()
                data = dict(form)
                request.scope["user"] = data
                return RedirectResponse('/', status_code=303)

            case _:
                return JSONResponse({"error": "Metodo non supportato"}, status_code=405)

    async def render_view(self,request):
        current_url = str(request.url)
        request.session["current_url"] = split_url(current_url)
        request.session["previous_url"] = current_url
        html = await self.mount_view(url=request.state.url, metadata=request.state.metadata, session=request.session)
        request.session["errors"] = []
        if flow.is_result(html):
            html = flow.output(html)
        if not isinstance(html, (str, bytes, memoryview)):
            html = str(html)
        if (self.defender.get_configuration("presentation") or {}).get(
            "security_and_waf", {}
        ).get("csrf_protection", True):
            document = BeautifulSoup(html, "html.parser")
            for form in document.find_all("form"):
                token = document.new_tag("input", type="hidden", name="csrf_token")
                token["value"] = request.session["csrf_token"]
                form.insert(0, token)
            html = str(document)
        return HTMLResponse(html)

    async def mount_view(self, url, metadata, session):
        view = metadata.get('view')
        controllers = metadata.get("controllers") or []
        xml_view = await self.loader.resource(view)
        if flow.is_result(xml_view):
            xml_view = flow.output(xml_view)

        session_result = await self.defender.session_create(**session)
        runtime_session = flow.output(session_result)
        self.sessions[runtime_session.sid] = runtime_session
        self._session_controllers[runtime_session.sid] = controllers
        self._session_views[runtime_session.sid] = {
            "text": xml_view,
            "source_name": view,
            "session": session.copy(),
        }
        self._current_view_controllers = controllers
        controller_context = await self.execute_controllers(
            runtime_session,
            controllers,
            source_name=view,
        )
        rendered_html = await self.render_template(
            runtime_session,
            controller_context=controller_context,
            text=xml_view,
            session=session.copy(),
        )

        return rendered_html

    @staticmethod
    def _normalized_origin(origin):
        if not isinstance(origin, str):
            return None
        try:
            parsed = urlsplit(origin)
            scheme = parsed.scheme.casefold()
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return None
        if (
            scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        return scheme, hostname.casefold(), port or (443 if scheme == "https" else 80)

    @classmethod
    def _websocket_origin_allowed(cls, websocket, allowed_origins=()):
        origin = cls._normalized_origin(websocket.headers.get("origin"))
        if origin is None:
            return False

        try:
            request_url = urlsplit(str(websocket.url))
        except (TypeError, ValueError):
            return False
        request_scheme = {"ws": "http", "wss": "https"}.get(
            request_url.scheme.casefold()
        )
        if request_scheme is None:
            return False
        expected_origin = cls._normalized_origin(
            f"{request_scheme}://{request_url.netloc}"
        )
        if origin == expected_origin:
            return True

        if isinstance(allowed_origins, str):
            allowed_origins = (allowed_origins,)
        if not isinstance(allowed_origins, (list, tuple, set, frozenset)):
            return False
        return any(
            origin == cls._normalized_origin(allowed_origin)
            for allowed_origin in allowed_origins
        )

    async def render_reactive(self, websocket):
        if not self._websocket_origin_allowed(
            websocket, self.config.get("websocket_allowed_origins", ())
        ):
            await websocket.close(code=1008, reason="Origin not allowed")
            return
        await websocket.accept()
        session_data = websocket.session
        sid = session_data.get('id')

        self.active_websockets.setdefault(sid, []).append(websocket)
        runtime_session = self.defender.session_get(sid)
        if runtime_session is not None:
            self.sessions[sid] = runtime_session
        
        try:
            while True:
                data = await websocket.receive_json()
                event = self.parse_reactive_event(data)
                if event:
                    dsl_alias = event['alias']
                    event_name = event['name']
                    try:
                        runtime_session = self.sessions.get(sid)
                        if runtime_session is None:
                            runtime_session = self.defender.session_get(sid)
                            if runtime_session is not None:
                                self.sessions[sid] = runtime_session
                        if runtime_session is None:
                            raise RuntimeError("La sessione WebSocket non è disponibile")
                        event_payload = data.get("payload", data.get("value", {}))
                        result = await self.messenger.send(
                            runtime_session,
                            adapter="dsl",
                            receiver=dsl_alias,
                            domain=event_name,
                            message=event_payload,
                        )
                        if flow.is_result(result) and not flow.check(result):
                            logger.error(
                                "Errore durante l'emissione dell'evento",
                                controller=dsl_alias,
                                event=event_name,
                                error=flow.output(result),
                            )
                        elif (
                            dsl_alias == "terminal"
                            and event_name == "select"
                            and isinstance(event_payload, str)
                            and event_payload
                        ):
                            selected_scope = (
                                "framework" if event_payload.startswith("src/framework/")
                                else "infrastructure" if event_payload.startswith("src/infrastructure/")
                                else "application"
                            )
                            scoped_result = await self.messenger.send(
                                runtime_session,
                                adapter="dsl",
                                receiver=dsl_alias,
                                domain=f"select_{selected_scope}",
                                message=event_payload,
                            )
                            if flow.is_result(scoped_result) and not flow.check(scoped_result):
                                logger.error(
                                    "Errore durante la selezione dello scope",
                                    controller=dsl_alias,
                                    event=f"select_{selected_scope}",
                                    error=flow.output(scoped_result),
                                )
                    except Exception as e:
                        logger.error("Errore durante l'emissione dell'evento", exception=e)
                             
        except WebSocketDisconnect:
            pass
        finally:
            if sid in self.active_websockets:
                sockets = self.active_websockets[sid]
                if websocket in sockets:
                    sockets.remove(websocket)
                if not sockets:
                    self.active_websockets.pop(sid, None)

    async def _rebuild(self, session, node_id, context=None, dsl_alias=None):
        session_id = getattr(session, "sid", None)
        controllers = self._session_controllers.get(
            session_id,
            getattr(self, "_current_view_controllers", []),
        )
        controller_context = self.get_controller_contexts(session, controllers)
        view = self._session_views.get(session_id)
        if view is not None:
            rendered_view = await self.render_template(
                session,
                text=view["text"],
                controller_context=controller_context,
                source_name=view["source_name"],
                session=view["session"],
            )
            if flow.is_result(rendered_view):
                if not flow.check(rendered_view):
                    return rendered_view
                rendered_view = flow.output(rendered_view)

            document = BeautifulSoup(str(rendered_view), "html.parser")
            target = document.find(id=node_id)
            if target is None:
                raise LookupError(
                    f"Nodo HTML '{node_id}' non trovato nella view '{view['source_name']}'"
                )
            rendered_node = str(target)
        else:
            node = self.DOM.get(node_id)
            if node is None:
                return None
            rendered_node = await self.render_template(
                session,
                text=node,
                controller_context=controller_context,
                source_name=node_id,
            )
            if flow.is_result(rendered_node):
                if not flow.check(rendered_node):
                    return rendered_node
                rendered_node = flow.output(rendered_node)

        if rendered_node and session_id in self.active_websockets:
            message = json.dumps({"type": "update", "id": node_id, "html": rendered_node})
            for websocket in self.active_websockets[session_id]:
                await websocket.send_text(message)

        return rendered_node

    async def mount_route(self, routes):
        if not hasattr(routes, "append"):
            routes = list(routes)
        for path, methods_dict in self.routes.items():
            for method, data in methods_dict.items():
                typee = data.get('type')
                # method = data.get('method')
                view = data.get('view')

                # Associa il path alla view (utile per debug o reverse lookup)
                self.views[path] = view

                # Se è una mount statica
                if typee == 'mount' and path == '/static':
                    r = Mount(path, app=StaticFiles(directory='/public'), name="static")
                    routes.append(r)
                    continue

                # Determina l'endpoint
                if typee == 'model':
                    endpoint = self.action
                elif typee == 'view':
                    endpoint = self.render_view
                elif typee == 'action':
                    endpoint = self.action
                elif typee == 'authenticate':
                    endpoint = self.signin
                elif typee == 'terminate':
                    endpoint = self.signout
                elif typee == 'activate':
                    endpoint = self.signup
                elif typee == 'reinstate':
                    endpoint = self.signaid
                else:
                    #endpoint = self.http_exception_handler  # fallback o gestione errori
                    continue

                # Crea la rotta e aggiungila
                r = Route(path, endpoint=endpoint, methods=[method])
                routes.append(r)
        return routes

    def mount_css(self, node, context):
        pass

    def node_create(self, tag, attrs=None, inner=None):
        attrs = attrs or {}
        inner = inner or []
        children = _html_children(inner)
        # Se tag è una funzione (es. un componente funzionale/lambda)
        if callable(tag) and type(tag).__name__ == "function":
            return Markup(str(tag({"inner": children, "attrs": attrs})))
        # Altrimenti trattalo come un elemento htpy standard
        if not hasattr(tag, "__getitem__"):
            return Markup(str(tag(**attrs)))
        return Markup(str(tag(**attrs)[children]))
    
    def node_union(self, node, context):
        pass
    
    def node_update(self, node, context):
        pass

    def dom_get(self, widget_id):
        return self.DOM.get(widget_id)

    def _apply_node_attrs(self, node, attrs_dict):
        return node

    async def _show_screen(self, screen):
        return screen

    async def _push_screen(self, screen):
        return screen

    async def _pop_screen(self):
        return None