import uuid
import asyncio
from html import escape
import re
import json
from datetime import datetime
from urllib.parse import urlunparse, ParseResult,parse_qs
import xml.etree.ElementTree as ET
import htpy
from markupsafe import Markup

import framework.port.presentation as presentation
import framework.core.flow as flow
import framework.service.route as route
from framework.service.route import split_url
from framework.manager.defender import Manager as Defender
from framework.manager.presenter import Manager as Presenter
from framework.manager.messenger import Manager as Messenger
from framework.manager.authenticator import Manager as Authenticator
from framework.manager.loader import Loader

try:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse,HTMLResponse,RedirectResponse
    from starlette.routing import Route,Mount,WebSocketRoute
    from starlette.middleware import Middleware
    from starlette.websockets import WebSocket, WebSocketDisconnect
    from starlette.middleware.sessions import SessionMiddleware
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
    import secrets
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

class DefenderMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, defender, routes):
        super().__init__(app)
        self.defender = defender
        self.routes = routes
    

    async def dispatch(self, request, call_next):
        # Esempio: decidiamo se accettare la richiesta in base al path
        if "id" not in request.session:
            session = await self.defender.session_create(request.session.copy())
            if session.get('success'):
                request.session.update(session.get('outputs', {}))
            else:
                request.session["errors"] = session.get('errors', [])
        request.session["ip"] = request.client.host
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
        # Logica di decisione (senza scomodare il resolve del router)
        authorized = self.defender.authorized('presentation', action=method, resource=request.state.metadata.get('view'), location=request.state.metadata.get('path'))
                    
        if not authorized:
            # Rifiutiamo la richiesta con un 403 Forbidden o 404
            return HTMLResponse(status_code=404)

        # Se va bene, procediamo
        response = await call_next(request)
        return response

# --- Configurazione Programmatica Attributi ---

mapping_attributes = {
    presentation.Attribute.WIDTH.value: lambda x: {
        "full": "w-full",
        "1/2": "w-1/2",
        "1/3": "w-1/3",
        "1/4": "w-1/4",
        "auto": "w-auto",
        True:f"w-[{x}]"
    }.get(True if '%' in x or 'px' in x else x, ""),
    presentation.Attribute.HEIGHT.value: lambda x: {
        "full": "h-full",
        "1/2": "h-1/2",
        "1/3": "h-1/3",
        "1/4": "h-1/4",
        "auto": "h-auto",
        True:f"h-[{x}]"
    }.get(True if '%' in x or 'px' in x else x),
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

def attrs(tag_key, input_data, classe=None):
    # 1. Prendi gli attributi grezzi passati dall'utente
    raw_attrs = input_data.get("attrs", {})
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
        **{k: v for k, v in raw_attrs.items() if k != "class"}
    }

class Adapter(presentation.Port):
    capabilities = {
        "tls": False,
        "min_tls_version": "TLSv1.2",
        "csrf": False,
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
                htpy.body(**attrs(presentation.Tag.WINDOW.value, x))[
                    [Markup(i) for i in x['inner']],
                    htpy.script(src="static/js/grid.js"),
                    htpy.script(src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"),
                    htpy.script(src="static/js/dsl.js"),

                    htpy.script[Markup("""
                        (function() {
                            const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/reactive`);
                            ws.onmessage = (e) => {
                                console.log(e.data);
                                const data = JSON.parse(e.data);
                                if (data.type === 'update') {
                                    const el = document.getElementById(data.id);
                                    if (el) el.outerHTML = data.html;
                                }
                            };

                            // Mappa eventi DOM -> attributo data-* sul nodo
                            const EVENT_ATTRS = {
                                'click':      'data-click',
                                'dblclick':   'data-dblclick',
                                'mouseover':  'data-mouseover',
                                'mouseout':   'data-mouseout',
                                'keydown':    'data-keydown',
                                'keyup':      'data-keyup',
                                'keypress':   'data-keypress',
                            };

                            Object.entries(EVENT_ATTRS).forEach(([domEvent, dataAttr]) => {
                                document.addEventListener(domEvent, (e) => {
                                    const el = e.target.closest(`[${dataAttr}]`);
                                    if (el) {
                                        const trigger = el.getAttribute(dataAttr);
                                        console.log(`[${domEvent}] Sending trigger:`, trigger);
                                        ws.send(JSON.stringify({type: 'event', name: trigger}));
                                    }
                                });
                            });
                        })();
                    """)]
                ]
            ],
            "dialog": lambda x: htpy.div(class_="modal fade", id=x.get("attrs", {}).get("id", "myModal"), tabindex="-1", aria_hidden="true")[
                htpy.div(class_="modal-dialog")[
                    htpy.div(class_="modal-content")[
                        htpy.div(class_="modal-header")[
                            htpy.h5(class_="modal-title")[x.get("attrs", {}).get("title", "")],
                            htpy.button(type="button", class_="btn-close", data_bs_dismiss="modal", aria_label="Close")
                        ],
                        htpy.div(class_="modal-body")[[Markup(i) for i in x['inner']]],
                        htpy.div(class_="modal-footer")[
                            htpy.button(type="button", class_="btn btn-secondary", data_bs_dismiss="modal")["Chiudi"]
                        ]
                    ]
                ]
            ],
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
            "select": lambda x: htpy.select(type="select", **attrs("input", x))[[Markup(htpy.option()[i]) for i in x['inner']]],
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
            "bar": lambda x: htpy.nav(**attrs("bar", x,"nav"))[[Markup(i) for i in x['inner']]],
            "app": lambda x: htpy.nav(**attrs("app", x,""))[[Markup(i) for i in x['inner']]],
            "breadcrumb": lambda x: htpy.nav(**attrs("breadcrumb", x,"breadcrumb"))[[Markup(i) for i in x['inner']]],
            "tab": lambda x: htpy.nav(**attrs("tab", x,"nav-tabs"))[[Markup(i) for i in x['inner']]],
        },
        presentation.Tag.GROUP.value: {
            "input": lambda x: htpy.div(**attrs("input", x,'input-group'))[[Markup(i) for i in x['inner']]],
            "action": lambda x: htpy.div(**attrs("button", x,'btn-group'))[[Markup(i) for i in x['inner']]],
            "card": lambda x: htpy.div(**attrs("card", x,'card-group'))[[Markup(i) for i in x['inner']]],
            "list": lambda x: htpy.ul(**attrs("group", x,'flex-col'))[[Markup(htpy.li[i]) for i in x['inner']]],
            "tab": lambda x: htpy.ul(**attrs("tab", x,'nav-tabs'))[[Markup(htpy.li('.nav-item')[i]) for i in x['inner']]],
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

    def __init__(self, loader: Loader, defender: Defender, presenter: Presenter, messenger: Messenger, authenticator: Authenticator, **constants):
        super().__init__(loader, defender, presenter, messenger, authenticator, **constants)
        self.ssh = {}
        cwd = os.getcwd()
        self.routes_static=[
            Mount('/static', app=StaticFiles(directory=f'{cwd}/public/'), name="static"),
            Mount('/framework', app=StaticFiles(directory=f'{cwd}/src/framework'), name="y"),
            Mount('/application', app=StaticFiles(directory=f'{cwd}/src/application'), name="z"),
            Mount('/infrastructure', app=StaticFiles(directory=f'{cwd}/src/infrastructure'), name="x"),
            #WebSocketRoute("/messenger", self.websocket, name="messenger"),
            #WebSocketRoute("/ssh", self.websocketssh, name="ssh"),
        ]
        
        self.middleware_static = [
            Middleware(SessionMiddleware, session_cookie="session_state", secret_key=self._session_secret()),
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
        
    async def start(self, session):
        self.session = session
        loop = asyncio.get_event_loop()
        await self.parse_route()
        self.routes_static += [
            WebSocketRoute("/reactive", self.render_reactive, name="reactive")
        ]
        await self.mount_route(self.routes_static) # 'routes' deve essere accessibile qui
        # Inizializza l'applicazione Starlette con rotte e middleware
        self.app = Starlette(debug=True, routes=self.routes_static, exception_handlers={HTTPException: self.http_exception_handler}, middleware=self.middleware_static)
        #print(di['message'][0].logger,'###########')
        # Parametri di configurazione base per Uvicorn
        uvicorn_config_params = {
            "app": self.app,
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
        self.server = Server(config)
        return self.server.serve()

    async def shutdown(self):
        if hasattr(self, 'server'):
            self.server.should_exit = True
        sockets = [socket for group in self.active_websockets.values() for socket in group]
        for websocket in sockets:
            await websocket.close()
        self.active_websockets.clear()
        
    async def signout(self,request) -> None:
        # Determina le credenziali in base al metodo HTTP
        match request.method:
            case 'GET':
                credentials = dict(request.query_params)
            case 'POST':
                credentials = dict(await request.form())
            case _:
                return RedirectResponse('/', status_code=405)

        # Autenticazione tramite defender
        session = await self.defender.terminate(request.session, **credentials)
        
        if session['success']:
            request.session.update(session['outputs'])
        else:
            request.session["errors"] = session['errors']

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

        # Autenticazione tramite defender
        #raise Exception("Defender non implementato per Starlette. Implementare la logica di autenticazione qui.")
        session = await self.authenticator.authenticate(request.session, **credentials)
        
        if session['success']:
            request.session.update(session['outputs'])
        else:
            request.session["errors"] = session['errors']

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

        # Autenticazione tramite defender
        session = await self.authenticator.activate(request.session, **credentials)
        
        if session['success']:
            request.session.update(session['outputs'])
        else:
            request.session["errors"] = session['errors']

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

        # Autenticazione tramite defender
        session = await self.authenticator.reinstate(request.session, **credentials)
        
        if session['success']:
            request.session.update(session['outputs'])
        else:
            request.session["errors"] = session['errors']

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
        return HTMLResponse(html)

    async def mount_view(self, url, metadata, session):
        view = metadata.get('view')
        controller = metadata.get('controller')
        xml_view = await self.presenter.get_view(session, view)
        if flow.is_result(xml_view):
            xml_view = flow.output(xml_view)
        controllers = [controller] if controller else []

        session_result = await self.defender.session_create(**session)
        runtime_session = flow.output(session_result)
        rendered_html = await self.render_template(
            runtime_session,
            controllers=controllers,
            text=xml_view,
            session=session.copy(),
        )

        return rendered_html

    async def render_reactive(self, websocket):
        await websocket.accept()
        session_data = websocket.session
        sid = session_data.get('id')

        self.active_websockets.setdefault(sid, []).append(websocket)
        
        try:
            while True:
                data = await websocket.receive_json()
                event = self.parse_reactive_event(data)
                if event:
                    dsl_alias = event['alias']
                    event_name = event['name']
                    file_path = event['file']
                    #print(f"Event: {event_full_name}")
                    #print(f"Data: {data['name']}")
                    
                    # Estrazione file e trigger name (es. counter:logic.increment)
                    # Il file e la sessione sono già inizializzati da mount_view al page load.
                    # Qui aggiungiamo il file solo se per qualche motivo non fosse ancora caricato
                    # (es. controller specificato via WS prima del page load HTTP).
                    if file_path not in self.executor.interpreter.runner.nodes:
                        try:
                            content = await self.loader.resource(file_path)
                            await self.executor.add_file(file_path, content)
                        except Exception as e:
                            print(f"Errore caricamento file {file_path}: {e}")
                    
                    #print(f"Emitting {event_name} for {file_path} (SID: {sid})")
                    try:
                        #print(f"Emitting {event_name} for {file_path} (SID: {sid})")
                        self.executor.interpreter.runner.emit(sid, file_path, event_name)
                    except Exception as e:
                         print(f"Errore durante l'emissione dell'evento: {e}")
                             
        except WebSocketDisconnect:
            pass
        finally:
            if sid in self.active_websockets:
                self.active_websockets[sid].remove(websocket)

    async def rebuild(self, node_id, session_id, context, dsl_alias):
        node = self.DOM.get(node_id)
        # Invece di usare solo il frammento "context", recuperiamo tutto lo stato aggiornato
        # in modo che i template possano usare `counter_logic.count` in tutti i casi
        full_ctx = {}
        if hasattr(self, 'executor') and self.executor:
            try:
                full_ctx = self.executor.interpreter.runner.context(session_id) or {}
            except Exception as e:
                print(f"Errore recupero contesto per rebuild: {e}")
                
        # Uniamo i due per sicurezza, dando priorità al context appena passato
        
        #final_context = {**full_ctx, **context}
        final_context = {}
        final_context[dsl_alias] = full_ctx
        
        rendered_node = await self.render_template(text=node, **final_context)

        if rendered_node:
             #html = await self.render_node(target_node, context)
             # Inviamo l'aggiornamento a tutti i websocket attivi per questo SID
             if session_id in self.active_websockets:
                msg = json.dumps({'type': 'update', 'id': node_id, 'html': rendered_node})
                for ws in self.active_websockets[session_id]:
                    await ws.send_text(msg)

        return rendered_node

    async def mount_route(self, routes):
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

    def mount_css(self, node, context):
        pass

    def node_create(self, tag, attrs=None, inner=None):
        attrs = attrs or {}
        inner = inner or []
        # Se tag è una funzione (es. un componente funzionale/lambda)
        if callable(tag) and type(tag).__name__ == "function":
            return str(tag({"inner": inner, "attrs": attrs}))
        # Altrimenti trattalo come un elemento htpy standard
        children = [Markup(i) for i in inner] if isinstance(inner, list) else Markup(inner or "")
        if not hasattr(tag, "__getitem__"):
            return str(tag(**attrs))
        return str(tag(**attrs)[children])
    
    def node_union(self, node, context):
        pass
    
    def node_update(self, node, context):
        pass