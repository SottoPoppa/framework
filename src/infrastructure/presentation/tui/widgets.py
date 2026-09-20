import framework.port.presentation as presentation
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Grid, HorizontalGroup, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Label, Markdown, MarkdownViewer, Pretty, Digits, Log, RichLog,
    Input, TextArea, Select, Checkbox, MaskedInput, OptionList, Switch, Button,
    RadioButton, RadioSet, SelectionList, ProgressBar, Link,
    ContentSwitcher, Rule, Static, ListView, ListItem, Tabs, Tab,
    TabbedContent, TabPane, LoadingIndicator, Placeholder, DataTable,
    Tree, DirectoryTree, Sparkline, Collapsible, Header, Footer,
)


def _attr(x: Dict[str, Any], key: str, default=None):
    return x.get("attrs", {}).get(key, default)


def _widget_text(widget_instance) -> str:
    dsl_text = getattr(widget_instance, "_storekeeper_text", None)
    if dsl_text is not None:
        return str(dsl_text)
    for attribute in ("content", "label", "renderable"):
        value = getattr(widget_instance, attribute, None)
        if value is not None and str(value):
            return str(value)
    return str(widget_instance)


def _children(x: Dict[str, Any]) -> List[Any]:
    return [
        child for child in x.get("inner", [])
        if not isinstance(child, str) and not isinstance(child, Screen)
    ]


def _text(x: Dict[str, Any]) -> str:
    return "".join(
        child if isinstance(child, str) else _widget_text(child)
        for child in x.get("inner", [])
    )


def _bool_attr(x: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = _attr(x, key)
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes")


class OptionValue:
    def __init__(self, label: str, value: str, click: str = None, content=None):
        self.label = label
        self.value = value
        self._dsl_click = click
        self._dsl_value = value
        self.content = list(content or [])


def _option_values(x: Dict[str, Any]) -> List[OptionValue]:
    options = [
        option for option in x.get("inner", [])
        if option is not None and not (isinstance(option, str) and not option.strip())
    ]
    if not all(isinstance(option, OptionValue) for option in options):
        received = ", ".join(type(option).__name__ for option in options) or "nessuno"
        raise ValueError(
            "Select e tabs richiedono esclusivamente figli <Option>; "
            f"ricevuti: {received}"
        )
    return options


def _options(x: Dict[str, Any]) -> List[Tuple[str, str]]:
    return [(option.label, option.value) for option in _option_values(x)]


def _parse_data(raw) -> List[float]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(value) for value in raw]
    if isinstance(raw, str):
        try:
            return [float(value.strip()) for value in raw.split(",") if value.strip()]
        except ValueError:
            return []
    return []


_NON_STYLE_KEYS = {
    "id", "class", "type", "name", "value", "placeholder", "title", "path",
    "label", "data", "required", "disabled", "readonly", "max", "min",
    "multiple", "route", "act", "click", "dblclick", "mouseover", "mouseout",
    "keydown", "keyup", "keypress", "style",
}


def attrs(widget_instance, attrs_dict: Dict[str, Any] = None):
    attrs_dict = attrs_dict or {}
    parsed: Dict[str, str] = {}
    for rule in (attrs_dict.get("style") or "").split(";"):
        if ":" in rule:
            key, value = rule.split(":", 1)
            parsed[key.strip().lower()] = value.strip()

    merged = {**parsed, **{key: value for key, value in attrs_dict.items() if key != "style"}}
    for key, value in merged.items():
        key_norm = key.lower()
        if key_norm in _NON_STYLE_KEYS:
            continue
        try:
            if key_norm == "overflow":
                widget_instance.styles.overflow_x = value
                widget_instance.styles.overflow_y = value
            else:
                setattr(widget_instance.styles, key_norm.replace("-", "_"), value)
        except Exception:
            continue

    if "overflow" not in merged and "overflow-y" not in merged:
        widget_instance.styles.overflow_y = "auto"
    if "overflow" not in merged and "overflow-x" not in merged:
        widget_instance.styles.overflow_x = "hidden"
    return widget_instance


def widget(cls, build: Callable[[Dict[str, Any]], Tuple[tuple, dict]] = None, style: bool = True):
    def factory(x):
        args, kwargs = build(x) if build else ((), {"id": _attr(x, "id")})
        instance = cls(*args, **kwargs)
        return attrs(instance, x.get("attrs", {})) if style else instance
    return factory


def _build(children: bool = False, text: bool = False, default_text: str = "", extra: Dict[str, Any] = None):
    extra = extra or {}

    def build(x):
        kwargs = {"id": _attr(x, "id")}
        for key, value in extra.items():
            kwargs[key] = value(x) if callable(value) else value
        if children:
            return tuple(_children(x)), kwargs
        if text:
            return (_text(x) or default_text,), kwargs
        return (), kwargs
    return build


class XmlScreen(Screen):
    def __init__(self, inner: Any, title: str = "App", sub_title: str = "", **kwargs):
        super().__init__(**kwargs)
        self.inner = inner if isinstance(inner, (list, tuple)) else [inner]
        self.title = title
        self.sub_title = sub_title

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(*self.inner)
        yield Footer()


class XmlModalScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss_modal", "Chiudi", show=False)]

    def __init__(self, inner: Any, title: str = "", sub_title: str = "", **kwargs):
        super().__init__(**kwargs)
        self.inner = inner
        self.title = title
        self.sub_title = sub_title

    def compose(self) -> ComposeResult:
        yield Container(*self.inner)

    async def action_dismiss_modal(self) -> None:
        await self.dismiss()


def _collapsible(default_title: str):
    return widget(
        Collapsible,
        _build(children=True, extra={"title": lambda x: _attr(x, "title", default_title)}),
    )


def _make_tabs(x):
    tabs = []
    for option in _option_values(x):
        tab = Tab(option.label)
        tab._dsl_click = option._dsl_click
        tab._dsl_value = option._dsl_value
        tabs.append(tab)
    tabs_widget = attrs(Tabs(*tabs, id=_attr(x, "id")), x.get("attrs", {}))
    active = _attr(x, "value")
    if active is not None:
        for tab in tabs_widget._tabs:
            if str(active) in (str(tab.id), str(getattr(tab, "_dsl_value", ""))):
                tabs_widget._first_active = tab.id
                break
    tabs_widget._dsl_tab_events = {
        tab.id: (tab._dsl_click, tab._dsl_value)
        for tab in tabs if getattr(tab, "_dsl_click", None)
    }
    return tabs_widget


def _make_option(x):
    options = x.get("inner", [])
    content = _children(x)
    title = _attr(x, "title")
    value = _attr(x, "value")
    if title is None and len(options) > 1:
        raise ValueError("<Option> richiede title quando contiene più elementi")
    child = options[0] if options else None
    label = str(title or (_widget_text(child) if child is not None else value or ""))
    value = value or getattr(child, "_dsl_value", label)
    return OptionValue(label, str(value), _attr(x, "data-click", _attr(x, "click")), content)


def _make_action(x):
    action = widget(Button, lambda node: ((_text(node),), {"id": _attr(node, "id")}))(x)
    action._dsl_click = _attr(x, "data-click", _attr(x, "click"))
    action._dsl_route = _attr(x, "route")
    value = _attr(x, "value")
    action._dsl_has_value = value is not None
    action._dsl_value = _text(x) if value is None else value
    return action


def _make_tabbed_content(x: Dict[str, Any]):
    panes = []
    for option in _option_values(x):
        if not option.content:
            raise ValueError("<Option> di un Group type='tab' richiede contenuto")
        panes.append(TabPane(option.label, *option.content, id=option.value or None))
    tabbed = TabbedContent(id=_attr(x, "id"))
    for pane in panes:
        tabbed.compose_add_child(pane)
    return attrs(tabbed, x.get("attrs", {}))


def _make_card(x: Dict[str, Any]):
    card = widget(Container, _build(children=True))(x)
    title = _attr(x, "title")
    if title:
        card.border_title = title
    return card


def _make_editor(x):
    editor = TextArea.code_editor(
        _text(x), id=_attr(x, "id"), language=_attr(x, "language", "python"),
        theme=_attr(x, "theme", "monokai"),
    )
    return attrs(editor, x.get("attrs", {}))


def _make_window(x):
    screen = XmlScreen(
        _children(x),
        _attr(x, "title", "App"),
        _attr(x, "subtitle", ""),
    )
    return attrs(screen, x.get("attrs", {}))


def _make_modal_window(x):
    screen = XmlModalScreen(
        _children(x),
        _attr(x, "title", ""),
        _attr(x, "subtitle", ""),
    )
    return attrs(screen, x.get("attrs", {}))


tags = {
    presentation.Tag.WINDOW.value: {
        "window": _make_window,
        "modal": _make_modal_window,
    },

    presentation.Tag.OPTION.value: {
        "option": _make_option,
    },

    presentation.Tag.NAVIGATION.value: {
        # Static è un widget "foglia" (un solo renderable, niente figli
        # montabili): usare Container qui faceva sì che i widget annidati
        # (es. <Text> dentro <Navigation>) non venissero mai mostrati.
        "navigation": widget(Container, _build(children=True, extra={"id": lambda x: _attr(x, "id", "nav")})),
        "tabs": _make_tabs,
    },

    presentation.Tag.TEXT.value: {
        "text": widget(Label, lambda x: ((Text(_text(x)),), {"id": _attr(x, "id")})),
        "markdown": widget(Markdown, lambda x: ((_text(x),), {"id": _attr(x, "id")})),
        "markdownviewer": widget(MarkdownViewer, lambda x: ((_text(x),), {"id": _attr(x, "id")})),
        "pretty": widget(Pretty, _build(children=True)),
        "digits": widget(Digits, lambda x: ((_text(x) or "0",), {"id": _attr(x, "id")})),
        "log": widget(Log),
        "richlog": widget(RichLog),
    },

    presentation.Tag.INPUT.value: {
        "select": widget(Select, lambda x: (
            (_options(x),),
            {
                "id": _attr(x, "id"),
                "value": _attr(x, "value", Select.BLANK),
            },
        )),
        "text": widget(Input, lambda x: ((), {
            "id": _attr(x, "id"), 
            "value": _attr(x, "value", ""),
        })),
        "editor": widget(TextArea.code_editor, lambda x: ((_text(x),), {
            "id": _attr(x, "id"),
            "language": _attr(x, "language", "python"),
            "theme": _attr(x, "theme", "monokai"),
        })),
        "input": widget(Input, lambda x: ((), {
            "placeholder": _attr(x, "placeholder", ""),
            "value": _attr(x, "value", ""),
            "password": _attr(x, "type") == "password",
            "id": _attr(x, "id"),
        })),
        "checkbox": widget(Checkbox, lambda x: ((_text(x),), {"id": _attr(x, "id")})),
        "masked": widget(MaskedInput, lambda x: ((), {"template": _attr(x, "placeholder", ""), "id": _attr(x, "id")})),
        "option": widget(OptionList, _build(children=True)),
        "switch": widget(Switch, lambda x: ((), {"value": _bool_attr(x, "value"), "id": _attr(x, "id")})),
        "radio": widget(RadioButton, lambda x: ((_text(x),), {"id": _attr(x, "id")})),
        "radioset": widget(RadioSet, _build(children=True)),
        "selectionlist": widget(SelectionList, lambda x: ((_options(x),), {"id": _attr(x, "id")})),
        "progress": widget(ProgressBar),
    },

    presentation.Tag.ACTION.value: {
        "action": _make_action,
        "button": _make_action,
        "link": widget(Link, lambda x: ((_text(x) or _attr(x, "href", ""),), {"url": _attr(x, "href", "#")})),
    },

    presentation.Tag.CONTAINER.value: {
        "container": widget(Container, _build(children=True)),
        "loading": widget(LoadingIndicator, style=False),
        "placeholder": widget(Placeholder),
    },

    presentation.Tag.ROW.value: {
        "row": widget(HorizontalGroup, _build(children=True)),
    },
    presentation.Tag.COLUMN.value: {
        "column": widget(Vertical, _build(children=True)),
    },
    presentation.Tag.STACK.value: {
        # Textual non ha un widget "Stack" nativo: ContentSwitcher mostra
        # un solo figlio per volta, comportamento equivalente a uno stack.
        "stack": widget(ContentSwitcher, _build(children=True)),
    },

    presentation.Tag.DIVIDER.value: {
        "divider": widget(Rule, style=False),
        "horizontal": widget(Rule, style=False),
    },

    presentation.Tag.ICON.value: {
        "icon": widget(Static, lambda x: ((_attr(x, "class", _attr(x, "name", "•")),), {}), style=False),
    },

    presentation.Tag.GROUP.value: {
        "list": widget(ListView, lambda x: (tuple(ListItem(c) for c in _children(x)), {"id": _attr(x, "id")})),
        "tab": _make_tabbed_content,
        "tree": widget(Tree, lambda x: ((_attr(x, "label", "root"),), {"id": _attr(x, "id")})),
        "directorytree": widget(DirectoryTree, lambda x: ((_attr(x, "path", "."),), {"id": _attr(x, "id")})),
        "collapsible": _collapsible("Toggle"),
        "contentswitcher": widget(ContentSwitcher, _build(children=True)),
    },

    presentation.Tag.ACCORDION.value: {
        "accordion": _collapsible("Accordion"),
    },

    presentation.Tag.CARD.value: {
        "card": _make_card,
    },

    presentation.Tag.MEDIA.value: {
        # Un terminale non può riprodurre audio/video: mostriamo un
        # segnaposto testuale invece di far fallire il render.
        "media": widget(Static, lambda x: ((f"[media: {_attr(x, 'src', '?')}]",), {}), style=False),
    },

    presentation.Tag.GRID.value: {
        "grid": widget(Grid, _build(children=True)),
        "sparkline": widget(Sparkline, lambda x: ((_parse_data(_attr(x, "data")),), {"id": _attr(x, "id")})),
        "datatable": widget(DataTable),
    },
}