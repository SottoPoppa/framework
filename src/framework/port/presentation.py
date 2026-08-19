from abc import ABC, abstractmethod
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from jinja2 import Environment, select_autoescape,FileSystemLoader,BaseLoader,ChoiceLoader,Template,DebugUndefined
from html import escape
import uuid
import untangle
import markupsafe
import re
import itertools
import os
from urllib.parse import urlparse, parse_qs, urljoin
from enum import Enum

import os
import pathlib

import framework.service.flow as flow
from framework.service.route import compile_pattern, match, normalize_path, register, register_many
from framework.service.template import render

class Tag(Enum):
    WINDOW = "window"
    TEXT = "text"
    INPUT = "input"
    ACTION = "action"
    MEDIA = "media"
    CARD = "card"
    NAVIGATION = "navigation"
    GROUP = "group"
    ROW = "row"
    COLUMN = "column"
    STACK = "stack"
    CONTAINER = "container"
    DEFENDER = "defender"
    MESSENGER = "messenger"
    MESSAGE = "message"
    STOREKEEPER = "storekeeper"
    PRESENTER = "presenter"
    VIEW = "view"
    DIVIDER = "divider"
    ICON = "icon"
    ACCORDION = "accordion"
    GRID = "grid"
    SVG = "svg"
    CANVAS = "canvas"
    G = "g"
    DEFS = "defs"
    RECT = "rect"
    CIRCLE = "circle"
    PATH = "path"
    TEXT_SVG = "text_svg"
    TSPAN = "tspan"
    STYLE_SVG = "style_svg"
    FILTER = "filter"
    FE_GAUSSIAN_BLUR = "fegaussianblur"
    FE_OFFSET = "feoffset"
    FE_FLOOD = "feflood"
    FE_COMPOSITE = "fecomposite"
    FE_MERGE = "femerge"
    FE_MERGE_NODE = "femergenode"
    ANIMATE = "animate"
    ANIMATE_TRANSFORM = "animatetransform"
    STOP = "stop"
    LINEAR_GRADIENT = "lineargradient"
    RADIAL_GRADIENT = "radialgradient"
    POLYGON = "polygon"
    LINE = "line"
    FE_DROP_SHADOW = "fedropshadow"
    CLIP_PATH = "clippath"
    PATTERN = "pattern"
    RESOURCE = "resource"

class Attribute(Enum):
    CLICK = "click"
    DBLCLICK = "dblclick"
    MOUSEOVER = "mouseover"
    MOUSEOUT = "mouseout"
    KEYDOWN = "keydown"
    KEYUP = "keyup"
    KEYPRESS = "keypress"
    CHANGE = "change"
    
    ID = "id"
    ROUTE = "route"
    ACT = "act"
    
    TYPE = "type"
    SRC = "src"
    ALT = "alt"
    TITLE = "title"
    WIDTH = "width"
    HEIGHT = "height"
    MIN_WIDTH = "min-width"
    MAX_WIDTH = "max-width"
    MIN_HEIGHT = "min-height"
    MAX_HEIGHT = "max-height"
    CONTROLS = "controls"
    AUTOPLAY = "autoplay"
    LOOP = "loop"
    MUTED = "muted"
    CLASS = "class"
    NAME = "name"
    VALUE = "value"
    COLOR = "color"
    THEME = "theme"
    LANGUAGE = "language"
    PLACEHOLDER = "placeholder"
    REQUIRED = "required"
    DISABLED = "disabled"
    READONLY = "readonly"
    MAX = "max"
    MIN = "min"
    SIZE = "size"
    MULTIPLE = "multiple"
    STYLE = "style"
    JUSTIFY = "justify"
    ALIGN = "align"
    SPACING = "spacing"
    VARIANT = "variant"
    TONE = "tone"
    BACKGROUND = "background"
    BORDER = "border"
    RADIUS = "radius"
    SHADOW = "shadow"
    TEXT_ALIGN = "text-align"
    WEIGHT = "weight"
    POSITION = "position"
    RESPONSIVE = "responsive"
    PADDING = "padding"
    MARGIN = "margin"
    EXPAND = "expand"
    MATTER = "matter"
    POINTER = "pointer"
    THICKNESS = "thickness"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    OVERFLOW = "overflow"
    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"
    TRUNCATE = "truncate"
    FONT = "font"
    VIEWBOX = "viewBox"
    D = "d"
    CX = "cx"
    CY = "cy"
    R = "r"
    RX = "rx"
    RY = "ry"
    X = "x"
    Y = "y"
    DX = "dx"
    DY = "dy"
    FILL = "fill"
    STROKE = "stroke"
    STROKE_WIDTH = "stroke-width"
    TRANSFORM = "transform"
    FILTER_ATTR = "filter"
    STD_DEVIATION = "stdDeviation"
    IN = "in"
    IN2 = "in2"
    OPERATOR = "operator"
    RESULT = "result"
    FLOOD_COLOR = "flood-color"
    FLOOD_OPACITY = "flood-opacity"
    TEXT_ANCHOR = "text-anchor"
    FONT_FAMILY = "font-family"
    FONT_SIZE = "font-size"
    FONT_WEIGHT = "font-weight"
    FONT_STYLE = "font-style"
    ATTRIBUTE_NAME = "attributeName"
    VALUES = "values"
    X1 = "x1"
    Y1 = "y1"
    X2 = "x2"
    Y2 = "y2"
    DUR = "dur"
    REPEAT_COUNT = "repeatCount"
    OPACITY = "opacity"
    POINTS = "points"
    OFFSET = "offset"
    STOP_COLOR = "stop-color"
    STOP_OPACITY = "stop-opacity"
    CLIP_PATH = "clip-path"
    CLIP_PATH_UNITS = "clipPathUnits"
    FROM = "from"
    TO = "to"
    BEGIN = "begin"
    ADDITIVE = "additive"
    ACCUMULATE = "accumulate"
    PATTERN_UNITS = "patternUnits"
    PATTERN_CONTENT_UNITS = "patternContentUnits"
    PATTERN_TRANSFORM = "patternTransform"
    PRESERVE_ASPECT_RATIO = "preserveAspectRatio"
    HREF = "href"
    

_IDENTITY = {a.value: a.value for a in [Attribute.ID, Attribute.CLASS]}
_MEDIA = {**_IDENTITY, **{a.value: a.value for a in [Attribute.SRC, Attribute.WIDTH, Attribute.HEIGHT, Attribute.ALT]}}
_FIELD = {**_IDENTITY, **{a.value: a.value for a in [Attribute.NAME, Attribute.VALUE, Attribute.PLACEHOLDER, Attribute.REQUIRED, Attribute.DISABLED, Attribute.READONLY, Attribute.MAX, Attribute.MIN, Attribute.MULTIPLE]}}
_MULTIMEDIA = {**_MEDIA, **{a.value: a.value for a in [Attribute.CONTROLS, Attribute.AUTOPLAY, Attribute.LOOP, Attribute.MUTED]}}
_LAYOUT_STATIC = {**_IDENTITY, **{a.value: a.value for a in [Attribute.WIDTH,Attribute.MAX_WIDTH, Attribute.MIN_WIDTH, Attribute.HEIGHT, Attribute.MAX_HEIGHT, Attribute.MIN_HEIGHT, Attribute.PADDING, Attribute.MARGIN, Attribute.OVERFLOW]}}
_LAYOUT = {**_LAYOUT_STATIC, **{a.value: a.value for a in [Attribute.EXPAND, Attribute.SPACING]}}
_LOCATION = {**_IDENTITY, **{a.value: a.value for a in [Attribute.JUSTIFY, Attribute.ALIGN, Attribute.POSITION, Attribute.TOP, Attribute.BOTTOM, Attribute.LEFT, Attribute.RIGHT]}}
_STYLE = {**_IDENTITY, **{a.value: a.value for a in [Attribute.THEME, Attribute.BACKGROUND, Attribute.MATTER, Attribute.COLOR, Attribute.BORDER, Attribute.RADIUS, Attribute.SHADOW, Attribute.THICKNESS, Attribute.STYLE]}}
_TYPOGRAPHY = {**_LAYOUT, **{a.value: a.value for a in [Attribute.SIZE, Attribute.WEIGHT, Attribute.UPPERCASE, Attribute.LOWERCASE, Attribute.TRUNCATE, Attribute.FONT, Attribute.ALIGN]}}
_EVENTS = {
    Attribute.CLICK.value: f"data-{Attribute.CLICK.value}",
    Attribute.DBLCLICK.value: f"data-{Attribute.DBLCLICK.value}",
    Attribute.MOUSEOVER.value: f"data-{Attribute.MOUSEOVER.value}",
    Attribute.MOUSEOUT.value: f"data-{Attribute.MOUSEOUT.value}",
    Attribute.KEYDOWN.value: f"data-{Attribute.KEYDOWN.value}",
    Attribute.KEYUP.value: f"data-{Attribute.KEYUP.value}",
    Attribute.KEYPRESS.value: f"data-{Attribute.KEYPRESS.value}",
    Attribute.CHANGE.value: f"data-{Attribute.CHANGE.value}",
}

_ATTRIBUTES_SCHEMA = {
    Tag.WINDOW.value: _IDENTITY | _LOCATION | _LAYOUT | _STYLE | {Attribute.TITLE.value:"title", Attribute.POINTER.value:"pointer"},
    Tag.NAVIGATION.value: _IDENTITY | _LOCATION | _LAYOUT | _STYLE,
    Tag.TEXT.value: _TYPOGRAPHY | _STYLE, 
    Tag.INPUT.value: _EVENTS | _FIELD | _LAYOUT | _STYLE | {Attribute.LANGUAGE.value:"language"}, 
    Tag.ACTION.value: _EVENTS | {Attribute.ROUTE.value:"action", Attribute.ACT.value:"method"} | _LAYOUT | _STYLE | {Attribute.POINTER.value:"pointer"}, 
    Tag.CONTAINER.value: _LAYOUT_STATIC | _LOCATION | _STYLE, 
    Tag.ROW.value: _LAYOUT | _LOCATION | _STYLE, 
    Tag.COLUMN.value: _LAYOUT | _LOCATION | _STYLE, 
    Tag.STACK.value: _LAYOUT | _LOCATION | _STYLE, 
    Tag.DIVIDER.value: _LOCATION | _LAYOUT | _STYLE | {Attribute.THICKNESS.value:"thickness"},
    Tag.ICON.value: _IDENTITY | {Attribute.NAME.value:"class", Attribute.SIZE.value:"size", Attribute.COLOR.value:"color"},
    Tag.GROUP.value: _IDENTITY | _LAYOUT | _LOCATION | _STYLE,
    Tag.ACCORDION.value: _IDENTITY | _LAYOUT | _STYLE,
    Tag.MEDIA.value: _IDENTITY | _MEDIA | _STYLE | _LAYOUT,
    Tag.CARD.value: _IDENTITY | _LAYOUT | _STYLE,
    Tag.CANVAS.value: _IDENTITY | _LAYOUT | _STYLE | _LOCATION,
    Tag.GRID.value: _IDENTITY | _LAYOUT | _STYLE | _LOCATION,
}

_SVG_ATTRIBUTES = {a.value: a.value for a in [
    Attribute.ID, Attribute.CLASS, Attribute.STYLE, Attribute.VIEWBOX, Attribute.D, Attribute.CX, Attribute.CY, Attribute.R, Attribute.RX, Attribute.RY,
    Attribute.X, Attribute.Y, Attribute.DX, Attribute.DY, Attribute.FILL, Attribute.STROKE, Attribute.STROKE_WIDTH, Attribute.TRANSFORM,
    Attribute.FILTER_ATTR, Attribute.STD_DEVIATION, Attribute.IN, Attribute.IN2, Attribute.OPERATOR, Attribute.RESULT,
    Attribute.FLOOD_COLOR, Attribute.FLOOD_OPACITY, Attribute.TEXT_ANCHOR, Attribute.FONT_FAMILY, Attribute.FONT_SIZE,
    Attribute.FONT_WEIGHT, Attribute.FONT_STYLE, Attribute.ATTRIBUTE_NAME, Attribute.VALUES, Attribute.DUR,
    Attribute.REPEAT_COUNT, Attribute.OPACITY, Attribute.POINTS, Attribute.OFFSET, Attribute.STOP_COLOR, Attribute.STOP_OPACITY,
    Attribute.WIDTH, Attribute.HEIGHT, Attribute.X1, Attribute.Y1, Attribute.X2, Attribute.Y2,
    Attribute.CLIP_PATH, Attribute.CLIP_PATH_UNITS, Attribute.FROM, Attribute.TO, Attribute.BEGIN,
    Attribute.ADDITIVE, Attribute.ACCUMULATE, Attribute.PATTERN_UNITS, Attribute.PATTERN_CONTENT_UNITS,
    Attribute.PATTERN_TRANSFORM, Attribute.PRESERVE_ASPECT_RATIO, Attribute.HREF
]}

_ATTRIBUTES_SCHEMA |= {
    Tag.SVG.value: _SVG_ATTRIBUTES,
    Tag.G.value: _SVG_ATTRIBUTES,
    Tag.DEFS.value: _SVG_ATTRIBUTES,
    Tag.RECT.value: _SVG_ATTRIBUTES,
    Tag.CIRCLE.value: _SVG_ATTRIBUTES,
    Tag.PATH.value: _SVG_ATTRIBUTES,
    Tag.TEXT_SVG.value: _SVG_ATTRIBUTES,
    Tag.TSPAN.value: _SVG_ATTRIBUTES,
    Tag.STYLE_SVG.value: _SVG_ATTRIBUTES | {Attribute.TYPE.value: "type"},
    Tag.FILTER.value: _SVG_ATTRIBUTES,
    Tag.FE_GAUSSIAN_BLUR.value: _SVG_ATTRIBUTES,
    Tag.FE_OFFSET.value: _SVG_ATTRIBUTES,
    Tag.FE_FLOOD.value: _SVG_ATTRIBUTES,
    Tag.FE_COMPOSITE.value: _SVG_ATTRIBUTES,
    Tag.FE_MERGE.value: _SVG_ATTRIBUTES,
    Tag.FE_MERGE_NODE.value: _SVG_ATTRIBUTES,
    Tag.ANIMATE.value: _SVG_ATTRIBUTES,
    Tag.ANIMATE_TRANSFORM.value: _SVG_ATTRIBUTES,
    Tag.STOP.value: _SVG_ATTRIBUTES,
    Tag.LINEAR_GRADIENT.value: _SVG_ATTRIBUTES,
    Tag.RADIAL_GRADIENT.value: _SVG_ATTRIBUTES,
    Tag.POLYGON.value: _SVG_ATTRIBUTES,
    Tag.LINE.value: _SVG_ATTRIBUTES,
    Tag.FE_DROP_SHADOW.value: _SVG_ATTRIBUTES,
    Tag.CLIP_PATH.value: _SVG_ATTRIBUTES,
    Tag.PATTERN.value: _SVG_ATTRIBUTES,
}


class Port(ABC):
    tags = {}

    def __init__(self, loader, defender, presenter, messenger, **constants):
        self.config = constants
        self.loader = loader
        self.defender = defender
        self.presenter = presenter
        self.messenger = messenger
        self.executor = constants.get("executor")
        self.views = {}
        self.initialize()

    def initialize(self):
        if isinstance(self, type):
            return None
        self.components = {}
        self.DOM = {}
        self.data = {}
        self.routes = {}
        self.views = {}
        # DOM
        self.document = {}
        fs_loader = FileSystemLoader("src/application/view/layout/")

        #http_loader = MyLoader()
        #choice_loader = ChoiceLoader([fs_loader, http_loader])

        ui_kit = [
            'breadcrumb',
            #'table',
            'badge',
            'input',
            'action',
            'text',
            #'media',
            'window',
            'card',
            #'navigation',
            'pagination',
            'group',
            'row',
            'column',
            'container',
            'defender',
            'messenger',
            'message',
            'storekeeper',
            'presenter',
            'view',
            'divider',
            'icon',
            'accordion',
            #'resource',
        ]
        
        '''for widget in ui_kit:
            if widget not in self.WIDGETS:
                raise NotImplementedError(f"Tag '{widget}' non gestito in compose_view")'''
        
        self.env = Environment(loader=fs_loader,autoescape=select_autoescape(["html", "xml"]),undefined=DebugUndefined)
        #self.env.filters['route'] = language.route

    def validate_adapter(self):
        required_state = ('loader', 'defender', 'presenter', 'messenger', 'DOM', 'routes', 'env')
        missing = [name for name in required_state if not hasattr(self, name)]
        if missing:
            raise RuntimeError(f"Adapter presentation incompleto: mancano {', '.join(missing)}")
        if not isinstance(self.tags, dict) or not self.tags:
            raise RuntimeError("Adapter presentation deve definire una mappa 'tags' non vuota")
        for method in ('node_create', 'node_update', 'rebuild'):
            if not callable(getattr(self, method, None)):
                raise RuntimeError(f"Adapter presentation non implementa '{method}'")
        return True

    @abstractmethod
    async def mount_view(self, *services, **constants):
        pass

    @abstractmethod
    async def mount_route(self, *services, **constants):
        pass

    @abstractmethod
    async def mount_css(self, *services, **constants):
        pass

    @abstractmethod
    def node_create(self, tag, attrs=None, inner=None):
        pass

    @abstractmethod
    async def node_update(self, node, context=None):
        pass

    def node_union(self, node=None, context=None):
        """Unisce un descrittore DSL con un contesto di aggiornamento."""
        node = node or {}
        context = context or {}
        return {
            "attrs": {**node.get("attrs", {}), **context.get("attrs", {})},
            "inner": context["inner"] if "inner" in context else node.get("inner", []),
        }

    def node_get(self, id: str):
        """Restituisce il widget DSL corrispondente a un id, se presente nel DOM."""
        if isinstance(self, type):
            return None
        if id and id in self.DOM:
            return self.DOM[id]
        return None

    @abstractmethod
    async def rebuild(self, node_id, view=None, context=None):
        pass

    def mount_tag(self, tag, attrs=None, inner=None, in_svg=False):
        attrs = attrs or {}
        inner = inner or []
        if "}" in tag:
            tag = tag.split("}")[-1]
        tag = tag.lower()
        if in_svg and tag == "text":
            tag = Tag.TEXT_SVG.value
        elif in_svg and tag == "style":
            tag = Tag.STYLE_SVG.value
            
        if tag not in self.tags: raise Exception(f"Tag {tag} non trovato")
        tipo = attrs.get("type") or tag
        elemento = self.tags[tag].get(tipo) or self.tags[tag].get(tag)
        if elemento is None: raise Exception(f"Tipo {tipo} non trovato in {tag}")
        schema = _ATTRIBUTES_SCHEMA.get(tag) or {}
        new_attrs = {}
        for attr in attrs:
            if attr not in schema: 
                #print(f"Attributo {attr} non valido per il tag {tag}")
                pass
            else:
                new_attrs[schema[attr]] = attrs[attr]

        #print(tag,new_attrs)
        return self.node_create(elemento,new_attrs,inner)
 
    @staticmethod
    def normalize_route_path(path):
        return normalize_path(path)

    @staticmethod
    def compile_route_pattern(path):
        return compile_pattern(path)

    def register_route(self, route):
        return register(self.routes, route)

    def match_route(self, path, method='GET'):
        return match(self.routes, path, method)

    @staticmethod
    def parse_reactive_event(payload=None, **fields):
        if payload is None:
            payload = fields
        elif fields:
            payload = {**payload, **fields}
        if not isinstance(payload, dict) or payload.get('type') != 'event':
            raise ValueError("Payload reactive non valido")
        event = payload.get('name')
        if not isinstance(event, str) or ':' not in event:
            raise ValueError("L'evento reactive deve avere formato alias:event")
        alias, name = event.split(':', 1)
        if not alias or not name:
            raise ValueError("Alias e nome evento reactive sono obbligatori")
        return {
            'alias': alias,
            'name': name,
            'file': Port.resolve_controller_file(alias),
        }

    @staticmethod
    def resolve_controller_file(alias):
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError("L'alias DSL deve essere una stringa non vuota")
        alias = alias.strip()
        return f"src/application/controller/{alias}.dsl"

    @staticmethod
    async def shutdown():
        return None

    async def parse_route(self):
        routes_cfg = self.defender.get_policy('presentation').get('routes', {}).values()
        self.routes.clear()
        register_many(self.routes, routes_cfg)
        return self.routes

    async def render_template(self, runtime_session, text=None, file=None, controllers=None, **constants):
        return await render(
            self.loader,
            runtime_session,
            self.render_node,
            text=text,
            file=file,
            controllers=controllers,
            **constants,
        )

    async def render_node(self, parent, node, context, runtime_session=None):
        """Trasforma ricorsivamente i nodi XML in oggetti del Driver"""
        tag = node.tag.split('}')[-1] if '}' in node.tag else node.tag
        in_svg = context.get('in_svg', False)
        if tag.lower() == "svg":
            in_svg = True

        ID = node.attrib.get('id')
        if isinstance(ID, str):
            extracted = self.presenter.estrai_da_xml_string(parent, ID)
            if extracted:
                self.DOM[ID] = extracted

        # Controllo se il tag è un componente (custom tag)
        component_paths = [
            #f"src/application/view/components/{tag}.xml",
            f"src/application/view/component/{tag}.xml"
        ]


        for path in component_paths:
            if os.path.exists(path):
                # Rimuove "src/" per passarlo a render_template
                # poiché render_template aggiunge già "src/"
                #relative_path = path.replace("src/", "", 1)
                relative_path = path
                
                # 1. Cattura i nodi figli originali come stringa XML pura (non renderizzata)
                # Questo evita che il parser XML veda tag HTML durante l'espansione
                inner_xml = "".join([ET.tostring(child, encoding='unicode') for child in list(node)])
                
                # 2. Prepara ID e Attributi
                node_id = node.attrib.get('id', str(uuid.uuid4()))
                attributes = {k.split('}')[-1]: v for k, v in node.attrib.items()}
                attributes['id'] = node_id
                
                # 3. Renderizza il componente iniettando l'XML non ancora processato
                return await self.render_template(
                    runtime_session,
                    **(context | {
                        'file': relative_path,
                        'inner': inner_xml,
                        'component': {
                            'id': node_id,
                            'attributes': attributes,
                            'inner': inner_xml
                        }
                    })
                )

        # Gestione Standard dei tag DSL
        children = []
        new_context = context.copy()
        new_context['in_svg'] = in_svg
        for child in list(node):
            children.append(
                await self.render_node(
                    parent,
                    child,
                    new_context,
                    runtime_session=runtime_session,
                )
            )

        # Gestione ID e Stato
        node_id = node.attrib.get('id')
        attributes = {}
        for k, v in node.attrib.items():
            attr_name = k.split('}')[-1] if '}' in k else k
            attributes[attr_name] = v
            
        if node_id:
            attributes['id'] = node_id
        
        if node.text and tag.lower() == "text":
            children.append(node.text)

        bind_var = attributes.pop("bind", None)
        if bind_var:
            if not node_id:
                raise Exception(f"Errore UI Reattiva: Un elemento con attributo 'bind' ({bind_var}) DEVE avere un attributo 'id' esplicito per permettere l'aggiornamento tramite WebSockets. Nodo incriminato: <{tag}>")
                
            if ":" in bind_var:
                dsl_alias, var_path = bind_var.split(":", 1)
                controller_file = f"src/application/controller/{dsl_alias}.dsl"
            else:
                var_path = bind_var
                controller_file = context.get("controller_file")

            # Assicuriamoci che l'executor e l'interpreter siano disponibili (in Adapter lo sono)
            if hasattr(self, "executor") and self.executor and hasattr(self.executor, "interpreter"):
                runner = self.executor.interpreter.runner
                
                # Se il path non è caricato e stiamo chiamando un alias specifico potremmo non avere le nodes caricate.
                # Per resilienza assumiamo che esista, ma gestiamo il caso.
                if controller_file and controller_file in runner.nodes:
                    bind_node_name = f"_auto_bind_{node_id}_{var_path}"
                    
                    if bind_node_name not in runner.nodes[controller_file]:
                        async def auto_bind_task(inputs):
                            sid = inputs.get("sid")
                            #print("#############################",inputs)
                            if sid:
                                await self.rebuild(node_id, sid, inputs,dsl_alias)
                            return True
                            
                        bind_node = {
                            "name":        bind_node_name,
                            "fn":          auto_bind_task,
                            "default":     None,
                            "deps":        [var_path],
                            "policy":      "all",
                            "meta":        False,
                            "trigger":     None,
                            "schedule":    None,
                            "duration":    None,
                            "timeout":     30,
                            "retries":     0,
                            "retry_delay": 0,
                            "when":        None,
                            "path":        bind_node_name,
                            "cache":       False,
                            "on_start":    None,
                            "on_success":  None,
                            "on_error":    None,
                            "on_end":      None,
                        }
                        
                        runner.attach_node(controller_file, bind_node)

        # mount_view: Il driver crea l'istanza del widget/tag 
        return self.mount_tag(tag, attributes, children, in_svg)