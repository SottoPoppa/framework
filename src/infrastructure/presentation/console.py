import asyncio
import framework.core.flow as flow
import uuid
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Callable

from textual.app import App, ComposeResult
from textual.containers import Container, HorizontalGroup, Vertical, Grid
from textual.widgets import (
    Rule, Link, Checkbox, Static, Button, Input, Select, TextArea,
    Header, Footer, Label, Markdown,
    MaskedInput, OptionList, Switch, Pretty,
    ListView, ListItem, Tabs, Tab, TabbedContent, TabPane,
    RadioButton, RadioSet, SelectionList,
    ProgressBar, Sparkline, DataTable, Tree, DirectoryTree,
    Collapsible, ContentSwitcher, LoadingIndicator,
    Log, RichLog, Digits, Placeholder, MarkdownViewer,
)
from rich.text import Text
from textual.screen import Screen, ModalScreen
from textual.binding import Binding


import framework.port.presentation as presentation
from framework.manager.defender import Manager as Defender
from framework.manager.presenter import Manager as Presenter
from framework.manager.messenger import Manager as Messenger
from framework.manager.loader import Loader
from framework.manager.authenticator import Manager as Authenticator


# ==========================================================================
# HELPER GENERICI
#
# Ogni nodo DSL arriva ai lambda come x = {"inner": [...], "attrs": {...}}.
# Queste funzioni astraggono gli accessi ripetuti in ogni lambda, così i
# widget dict sotto restano dichiarativi invece che pieni di boilerplate.
# ==========================================================================

def _attr(x: Dict[str, Any], key: str, default=None):
    """Legge un attributo (già filtrato dallo schema di presentation.py)."""
    return x.get("attrs", {}).get(key, default)


def _widget_text(w) -> str:
    """
    Estrae il testo "sorgente" da un widget Textual già costruito.

    IMPORTANTE: NON si può usare widget.render() qui — richiede un'app
    Textual attiva e solleva NoActiveAppError se il widget non è ancora
    montato (come nel nostro caso: node_create() costruisce i widget
    PRIMA che vengano montati). Anche str(widget) non aiuta: restituisce
    solo la rappresentazione della classe (es. "Label()"), non il testo.

    Gli attributi pubblici giusti, verificati sui widget Textual reali:
      - Static/Label:                      .content
      - Button/Checkbox/RadioButton:       .label

    NOTA: alcuni widget (es. Checkbox) hanno ENTRAMBI gli attributi, ma
    '.content' è vuoto e solo '.label' contiene il testo — per questo si
    prova ogni attributo e si accetta solo il primo risultato non vuoto,
    invece di fermarsi al primo attributo semplicemente presente.
    """
    for attr in ("content", "label", "renderable"):
        value = getattr(w, attr, None)
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return str(w)


def _children(x: Dict[str, Any]) -> List[Any]:
    """
    Figli che sono widget da comporre inline: esclude il testo grezzo e le
    Screen (es. un <Window type="modal"> annidato in un'altra vista).

    Una Screen non va MAI composta come figlio dentro un Container/Column/
    Row: Textual la gestisce tramite lo screen stack (push_screen/
    pop_screen), non come nodo di un albero di widget. Resta comunque
    registrata in self.widgets (node_create registra QUALSIASI nodo con un
    id, Screen incluse) — recuperabile in seguito per essere mostrata
    on-demand con Adapter.open_registered_modal(id).
    """
    return [f for f in x.get("inner", []) if not isinstance(f, str) and not isinstance(f, Screen)]


def _text(x: Dict[str, Any]) -> str:
    """Testo del nodo: concatena stringhe e il testo dei figli non testuali."""
    parts = []
    for f in x.get("inner", []):
        parts.append(f if isinstance(f, str) else _widget_text(f))
    return "".join(parts)


def _bool_attr(x: Dict[str, Any], key: str, default: bool = False) -> bool:
    v = _attr(x, key)
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes")


def _options(x: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Coppie (etichetta, valore_stringa) per Select/SelectionList a partire dai figli."""
    options = []
    for f in x.get("inner", []):
        text_val = f if isinstance(f, str) else _widget_text(f)
        # Usiamo il testo stesso (o un attributo 'value' se presente nel tag figlio) come valore
        val = getattr(f, "value", None) or text_val
        options.append((text_val, str(val)))
    return options


def _parse_data(raw) -> List[float]:
    """Converte l'attributo 'data' (CSV o lista) in lista di float per Sparkline."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(v) for v in raw]
    if isinstance(raw, str):
        try:
            return [float(v.strip()) for v in raw.split(",") if v.strip()]
        except ValueError:
            return []
    return []

_NON_STYLE_KEYS = {
    "id", "class", "type", "name", "value", "placeholder",
    "title", "path", "label", "data",
    "required", "disabled", "readonly", "max", "min", "multiple",
    "route", "act",
    "click", "dblclick", "mouseover", "mouseout", "keydown", "keyup", "keypress",
    "style",
}


def attrs(widget, attrs_dict: Dict[str, Any] = None):
    """
    Applica dinamicamente proprietà di stile Textual al widget.

    Supporta sia un attributo 'style' in formato CSS-like
    ("width: 80%; color: red; overflow: auto") sia attributi diretti
    ({"width": "80%", "color": "red"}). Gli attributi diretti hanno
    priorità sulla stringa 'style'. Default retrocompatibili se non
    specificato altro: overflow-y=auto, overflow-x=hidden, height=80%.
    """
    attrs_dict = attrs_dict or {}

    parsed: Dict[str, str] = {}
    for rule in (attrs_dict.get("style") or "").split(";"):
        rule = rule.strip()
        if ":" in rule:
            k, v = rule.split(":", 1)
            parsed[k.strip().lower()] = v.strip()

    merged = {**parsed, **{k: v for k, v in attrs_dict.items() if k != "style"}}

    for key, value in merged.items():
        key_norm = key.lower()
        if key_norm in _NON_STYLE_KEYS:
            continue
        if key_norm == "overflow":
            widget.styles.overflow_x = widget.styles.overflow_y = value
            continue
        try:
            setattr(widget.styles, key_norm.replace("-", "_"), value)
        except Exception as e:
            print(f"[attrs] Impossibile impostare '{key_norm}' = '{value}' su {widget!r}: {e}")

    if "overflow" not in merged and "overflow-y" not in merged:
        widget.styles.overflow_y = "auto"
    if "overflow" not in merged and "overflow-x" not in merged:
        widget.styles.overflow_x = "hidden"
    # NOTA: niente default di "height" qui. Un default percentuale (es. 80%)
    # applicato a QUALSIASI widget si risolve a 0 quando il genitore ha
    # height:auto (TabPane, Collapsible, ...) — causa esattamente il bug
    # "il contenuto annidato è montato ma invisibile". Meglio lasciare che
    # sia il widget Textual stesso a usare il proprio default (auto, 1fr,
    # ecc.) a meno che il DSL non specifichi height esplicitamente.

    return widget


# ==========================================================================
# widget(): factory che genera un lambda pronto per il dizionario `tags`.
#
# `build(x)` restituisce (args, kwargs) per il costruttore del widget.
# Se `build` è None: nessun arg posizionale, kwargs={'id': <id>}.
# `style=False` salta l'applicazione di attrs() (per widget senza .styles
# rilevanti da esporre, es. Rule, LoadingIndicator).
# ==========================================================================
def widget(cls, build: Callable[[Dict[str, Any]], Tuple[tuple, dict]] = None, style: bool = True):
    def factory(x):
        args, kwargs = build(x) if build else ((), {"id": _attr(x, "id")})
        instance = cls(*args, **kwargs)
        return attrs(instance, x.get("attrs", {})) if style else instance
    return factory


def _build(children: bool = False, text: bool = False, default_text: str = "", extra: Dict[str, Any] = None):
    """
    Genera una funzione build(x) da passare a widget(), coprendo i due
    pattern più comuni nel dizionario `tags`:

      - children=True: passa i widget figli come argomenti posizionali
        (es. Container(*figli), Grid(*figli), ...)
      - text=True: passa il testo del nodo come unico argomento posizionale
        (es. Button(testo), Checkbox(testo), ...)

    `extra` aggiunge kwargs statici o dinamici (funzioni x -> valore), utile
    per widget che hanno bisogno di un attributo specifico oltre a id/testo/
    figli (es. {"language": "python"} o {"value": lambda x: _bool_attr(...)}).

    kwargs include sempre {"id": _attr(x, "id")} come base.
    """
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


def _collapsible(default_title: str):
    """Collapsible con titolo di default diverso (usato da <group type="collapsible"> e <accordion>)."""
    return widget(Collapsible, _build(children=True, extra={"title": lambda x: _attr(x, "title", default_title)}))

class XmlScreen(Screen):
    """Una schermata che si auto-costruisce leggendo un file XML."""

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
    """
    Variante modale di XmlScreen: si sovrappone alla schermata corrente
    (sfondo attenuato, contenuto centrato) invece di sostituirla. Si apre
    con Adapter.open_modal()/open_registered_modal() e si chiude con
    Adapter.close_modal(), con ESC, o con un bottone click="modal:close".

    NOTA: ModalScreen di Textual NON lega ESC alla chiusura di default
    (verificato nel sorgente: le sue BINDINGS coprono solo focus/copia) —
    va aggiunto esplicitamente, da qui il binding sotto.

    Niente Header/Footer: una modale è tipicamente un riquadro di dialogo,
    non un'intera schermata applicativa.
    """

    BINDINGS = [Binding("escape", "dismiss_modal", "Chiudi", show=False)]

    DEFAULT_CSS = """
    XmlModalScreen {
        align: center middle;
    }
    XmlModalScreen > Container {
        width: auto;
        height: auto;
        max-width: 80%;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, inner: str, title: str = "", sub_title: str = "", **kwargs):
        super().__init__(**kwargs)
        self.inner = inner
        self.title = title
        self.sub_title = sub_title

    def compose(self) -> ComposeResult:
        yield Container(*self.inner)

    async def action_dismiss_modal(self) -> None:
        """Chiude questa modale (Screen.dismiss() la rimuove dallo screen stack)."""
        await self.dismiss()

    async def open_modal(self, view_path: str, **context):
        """
        Costruisce la vista XML in `view_path` (che deve contenere un
        <Window type="modal">, altrimenti mount_tag produce una XmlScreen
        normale) e la mostra sopra la schermata corrente.

        `context` viene passato al template Jinja della vista, come già
        fa render_template() per le viste normali.

        Usare per modali definite in un FILE XML SEPARATO. Se la modale è
        invece annidata nello stesso file della pagina corrente (come
        <Window type="modal"> figlio di <Window type="page">), è già stata
        costruita e registrata durante il rendering della pagina: usare
        open_registered_modal() invece, che non ricarica nulla da disco.
        """
        xml_view = flow.output(await self.presenter.get_view(self.session, view_path))
        modal = await self.render_template(text=xml_view, controllers=[self.routes[view_path]['GET']['controller']], **context)
        await self.app.push_screen(modal)
        return modal

    async def open_registered_modal(self, modal_id: str):
        """
        Ricostruisce e mostra come modale il <Window type="modal"> con
        quell'id, definito inline nella stessa vista.

        IMPORTANTE: ricostruisce SEMPRE un'istanza nuova a partire dal suo
        XML grezzo (già disponibile in self.DOM, popolato durante il primo
        rendering della pagina) invece di riusare il widget costruito in
        precedenza. In Textual una Screen non è pensata per essere spinta
        sullo screen stack più di una volta: dopo pop_screen() i suoi
        widget interni restano "già montati" internamente, e ripresentare
        la stessa istanza causa un blocco invece di un errore pulito.
        Ricostruire da zero ad ogni apertura è il pattern corretto — è
        esattamente lo stesso approccio già usato da open_modal() per le
        modali caricate da file esterno, solo che qui il testo XML non
        viene letto da disco ma da self.DOM.
        """
        xml_fragment = self.DOM.get(modal_id)
        if xml_fragment is None:
            print(f"[open_registered_modal] Nessun nodo con id '{modal_id}' in DOM")
            return None
        modal = await self.render_template(text=xml_fragment)
        await self.app.push_screen(modal)
        return modal

    def close_modal(self) -> None:
        """
        Chiude la modale corrente, se ce n'è una in cima allo stack.
        Non fa nulla se la schermata attiva non è una modale (evita di
        chiudere per errore la schermata principale).
        """
        if isinstance(self.app.screen, ModalScreen):
            self.app.pop_screen()

class AppDinamica(App):

    DEFAULT_CSS = """
    Grid {
        grid-size: 3;
        grid-gutter: 1 2;
        padding: 1;
    }
    """

    BINDINGS = [
        ("d", "toggle_dark", "Cambia Tema"),
        ("q", "quit", "Esci"),
        ("ctrl+s", "save", "Salva"),
    ]

    def __init__(self, adapter, **kwargs):
        super().__init__(**kwargs)
        self.adapter = adapter

    def check_action(self, action, parameters):
        widget = self.focused

        if action == "save":
            return isinstance(widget, TextArea)

        if action == "close_tab":
            return isinstance(widget, Tab)

        return True

    async def action_save(self):
        focused = self.focused

        if isinstance(focused, TextArea):
            print("Salvo editor:", focused.text)
        else:
            print("Nessun editor attivo")

    async def on_mount(self) -> None:
        await self.adapter.render_view(url="/")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        
        w = self.adapter.node_get(event.button.id)

        if w is not None:
            attrs_tag = self.adapter.presenter.estrai_attributi_tag(w)
            await self.adapter.messenger.send(self.adapter.session, domain=attrs_tag['click'], message=str(event.button.id))
        
        """if click == "modal:close":
            self.adapter.close_modal()
            return
        if click and click.startswith("modal:open:"):
            modal_id = click.split(":", 2)[2]
            await self.adapter.open_registered_modal(modal_id)
            return"""

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        a = self._dsl_attrs(event.input.id)
        raise Exception(f"[on_input_submitted] Nessun attributo 'submit' per Input {event.input.id} (DSL: {a})")
        if a and 'submit' in a:
            await self.adapter.messenger.send(self.adapter.session, domain=a['submit'], message=str(event.value))
        raise Exception(f"[on_input_submitted] Nessun attributo 'submit' per Input {event.input.id} (DSL: {a})")
    
    async def on_input_changed(self, event: Input.Changed) -> None:
        a = self._dsl_attrs(event.input.id)
        exit(a)
        #a = self._dsl_attrs(event.input.id)
        #raise Exception(f"[on_input_changed] Nessun attributo 'change' per Input {event.input.id} (DSL: {a})")

    async def on_select_changed(self, event: Select.Changed) -> None:
        w = self.adapter.node_get(event.select.id)

        if w is not None:
            attrs_tag = self.adapter.presenter.estrai_attributi_tag(w)
            await self.adapter.messenger.send(self.adapter.session, domain=attrs_tag['change'], message=str(event.value))
        
        #a = self._dsl_attrs(event.select.id)
        #raise Exception(f"[on_select_changed] Nessun attributo 'change' per Select {event.select.id} (DSL: {a})")

    async def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._log_change("Checkbox", event.checkbox.id, event.value)

    async def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._log_change("RadioSet", event.radio_set.id, event.pressed)

    async def on_switch_changed(self, event: Switch.Changed) -> None:
        self._log_change("Switch", event.switch.id, event.value)

    async def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        print(f"Tab attivata: {event.tab.id}")

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        print(f"ListView selezionata: {event.item}")


# ==========================================================================
# Casi speciali: non riducibili alla factory `widget()` per vincoli reali
# dell'API Textual (non per pigrizia — vedi commenti).
# ==========================================================================

def _make_tabbed_content(x: Dict[str, Any]):
    """
    TabbedContent(*titles) accetta SOLO stringhe come titoli: passargli
    un TabPane fa sì che Textual provi a renderizzarlo come testo e crasha
    (AttributeError: 'TabPane' object has no attribute 'translate').
    Il contenuto va aggiunto con compose_add_child(), il metodo pubblico
    che Textual usa internamente per `with TabbedContent(): yield contenuto`.
    """
    children = _children(x)
    titles = [(getattr(c, "id", None) or f"Tab {i + 1}") for i, c in enumerate(children)]
    tabbed = TabbedContent(*titles, id=_attr(x, "id"))
    for child in children:
        tabbed.compose_add_child(child)
    return attrs(tabbed, x.get("attrs", {}))


def _make_card(x: Dict[str, Any]):
    """Container con bordo titolato: border_title è una proprietà d'istanza,
    non un parametro del costruttore, quindi va impostata dopo la creazione."""
    card = widget(Container, _build(children=True))(x)
    title = _attr(x, "title")
    if title:
        card.border_title = title
    return card

def _make_editor(x):
    editor = TextArea.code_editor(
        _text(x),
        id=_attr(x, "id"),
        language=_attr(x, "language", "python"),
        theme="monokai",
    )

    print("LANG:", editor.language)
    print("AVAILABLE:", editor.available_languages)

    return attrs(editor, x.get("attrs", {}))

class DomRegistry:
    """
    Registro dei widget Textual LIVE (già montati/costruiti), indicizzati
    per id. È distinto da `Adapter.DOM`, che contiene invece lo XML grezzo
    dei nodi (usato per rileggere attributi originali del DSL come
    'click'/'submit' — un widget Textual costruito non li conserva).

    Questo registro è ciò che permette a node_update()/dom_*() di trovare
    e patchare un widget esistente senza dover ripercorrere l'albero XML.
    """

    def __init__(self):
        self._widgets: Dict[str, Any] = {}

    def register(self, widget_id: Optional[str], instance):
        if widget_id:
            self._widgets[widget_id] = instance
        return instance

    def get(self, widget_id: Optional[str]):
        return self._widgets.get(widget_id) if widget_id else None

    def forget(self, widget_id: Optional[str]):
        if widget_id:
            self._widgets.pop(widget_id, None)

    def forget_all(self):
        self._widgets.clear()

    def __contains__(self, widget_id) -> bool:
        return widget_id in self._widgets


class Adapter(presentation.Port):
    """
    Adapter Textual nativo per il Framework.

    Implementa presentation.Port. La chiave di ogni voce di `tags` deve
    corrispondere a un valore di presentation.Tag; la sotto-chiave al
    valore dell'attributo `type="..."` nel DSL (o al nome del tag stesso),
    replicando la logica di mount_tag():

        tipo = attrs.get("type") or tag
        elemento = self.tags[tag].get(tipo) or self.tags[tag].get(tag)
    """

    tags = {
        presentation.Tag.WINDOW.value: {
            "window": lambda x: XmlScreen(_children(x), _attr(x, "title", "App"), _attr(x, "subtitle", "")),
            "modal": lambda x: XmlModalScreen(_children(x), _attr(x, "title", ""), _attr(x, "subtitle", "")),
        },

        presentation.Tag.NAVIGATION.value: {
            # Static è un widget "foglia" (un solo renderable, niente figli
            # montabili): usare Container qui faceva sì che i widget annidati
            # (es. <Text> dentro <Navigation>) non venissero mai mostrati.
            "navigation": widget(Container, _build(children=True, extra={"id": lambda x: _attr(x, "id", "nav")})),
            "tabs": widget(Tabs, lambda x: (
                tuple(Tab(f if isinstance(f, str) else _widget_text(f)) for f in x.get("inner", [])),
                {"id": _attr(x, "id")},
            )),
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
            "select": widget(Select, lambda x: ((_options(x),), {"id": _attr(x, "id")})),
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
            "action": widget(Button, lambda x: ((_text(x),), {"id": _attr(x, "id")})),
            "button": widget(Button, lambda x: ((_text(x),), {"id": _attr(x, "id")})),
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

    def __init__(self, loader: Loader, defender: Defender, presenter: Presenter, messenger: Messenger, authenticator: Authenticator, **constants):
        """
        Inizializza l'adapter Textual.

        Args (via dependency injection dal container):
            loader: Manager per il caricamento delle risorse
            defender: Manager per autenticazione/autorizzazione
            messenger: Manager per messaggistica
            executor: Manager per esecuzione DSL
            presenter: Manager per presentazione
            **constants: Configurazione da pyproject.toml (adapter.registry)
        """
        super().__init__(loader, defender, presenter, messenger, authenticator, **constants)
        self._render_lock = asyncio.Lock()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.active_screens: Dict[str, 'TUIScreen'] = {}
        self.widgets = DomRegistry()  # registro dei widget live, per id
        self.app = AppDinamica(self)
        self.validate_adapter()

    def _ensure_active_app(self):
        if hasattr(self, 'app') and self.app:
            from textual._context import active_app
            try:
                active_app.get()
            except LookupError:
                active_app.set(self.app)

    async def start(self, session):
        """Avvia l'applicazione TUI (equivalente di Starlette server.serve())."""
        session_result = await self.defender.session_create()
        self.session = flow.output(session_result)
        await self.parse_route()
        return self.app.run_async()

    async def shutdown(self):
        if self.app:
            self.app.exit()

    def mount_css(self, css_content: str) -> None:
        """Inietta lo stile nell'applicazione."""
        if self.app:
            self._ensure_active_app()
            self.app.parse_stylesheet(css_content)

    async def mount_view(self, url):
        self._ensure_active_app()
        route_info, params = self.match_route(url, 'GET')
        if not route_info:
            raise KeyError(f"Nessuna rotta GET trovata per l'URL '{url}'")

        view_path = route_info.get('view')
        controller = route_info.get('controller')
        controllers = [controller] if controller else []

        xml_view = flow.output(await self.presenter.get_view(self.session, view_path))
        return await self.render_template(self.session, controllers=controllers, text=xml_view)

    async def render_view(self, url):
        self._ensure_active_app()
        self.url = url
        async with self._render_lock:
            result = await self.mount_view(url)
            if not flow.check(result):
                return result
            screen = flow.output(result)

            if self.app.screen.id == "_default":
                await self.app.push_screen(screen)
            else:
                await self.app.switch_screen(screen)

    async def mount_route(self, routes):
        for path, methods_dict in self.routes.items():
            for method, data in methods_dict.items():
                self.views[path] = data.get('view')

    async def rebuild(self, node_id: str, session_id: str = None, context: Dict[str, Any] = None, dsl_alias: str = None):
        """Ricostruisce il widget live a partire dal frammento XML aggiornato nel DOM."""
        self._ensure_active_app()

        # IMPORTANTE: va preso PRIMA di chiamare render_template(), perché
        # render_template -> mount_tag -> node_create sovrascrive subito
        # self.widgets[node_id] con la nuova istanza (ancora non montata).
        # Se lo prendi dopo, dom_get() ti restituisce rendered_node stesso.
        old_widget = self.dom_get(node_id)
        if old_widget is None:
            print("Widget non montato:", node_id)
            return None

        xml_fragment = self.DOM.get(node_id)
        if xml_fragment is None:
            print(f"[rebuild] Nessun nodo con id '{node_id}' in DOM")
            return None

        try:
            rendered_node = await self.render_template(
                self.session, controllers=['terminal'], text=xml_fragment
            )
        except Exception as e:
            print(f"[rebuild] Impossibile ricostruire il nodo '{node_id}': {e}")
            return None

        parent = old_widget.parent
        if parent is None:
            print(f"[rebuild] '{node_id}' non ha un parent montato, impossibile sostituire")
            return None

        await parent.mount(rendered_node, before=old_widget)
        await old_widget.remove()

        self.widgets.register(node_id, rendered_node)  # ridondante (node_create l'ha già fatto), ma innocuo

        return rendered_node

    def dom_get(self, widget_id):
        try:
            return self.app.query_one(f"#{widget_id}")
        except Exception:
            return None

    def node_create(self, tag, attrs=None, inner=None):
        attrs = attrs or {}
        inner = inner or []
        """
        Chiamato da mount_tag() come: self.node_create(elemento, new_attrs, inner)
        dove `elemento` è il lambda selezionato da self.tags[tag][tipo].

        Oltre a costruire il widget, lo registra in self.widgets (se ha un
        id), così node_update()/dom_*() potranno trovarlo in seguito senza
        dover ripercorrere l'albero XML.
        """
        if not (callable(tag) and type(tag).__name__ == "function"):
            raise NotImplementedError("node_create è stato deprecato. Usa node_create2 per creare widget Textual direttamente da tag DSL.")
        instance = tag({"inner": inner, "attrs": attrs})
        return self.widgets.register(attrs.get("id"), instance)

    async def node_update(self, node, context: Dict[str, Any] = None):
        """
        Applica un aggiornamento a un widget Textual GIÀ MONTATO (patch in
        place), invece di ricostruirlo da zero. `context` ha la stessa forma
        di un nodo DSL: {'attrs': {...}, 'inner': [...]}.

        Aggiorna, se applicabile al widget:
          1. Stile     -> tramite attrs()
          2. Testo     -> tramite widget.update(...) se il widget lo espone
                          (Label, Static, Markdown, Digits, ...)
          3. Figli     -> tramite remove_children()+mount() se il widget è
                          un container già montato (Container, Vertical, ...)

        È async perché il montaggio/smontaggio di figli in Textual lo è.
        Se un tipo di widget deve cambiare del tutto (non solo il suo
        contenuto), usare dom_replace() invece: node_update() patcha
        un'istanza esistente, non può trasformarla in un'altra classe.
        """
        descriptor = self.node_union({"attrs": {}, "inner": []}, context or {})
        new_attrs = descriptor["attrs"]
        new_text, new_children = presentation.split_text_and_children(descriptor["inner"])

        # 1. Stile
        if new_attrs:
            attrs(node, new_attrs)

        # 2. Testo (widget "foglia" con update(), es. Label/Static/Markdown/Digits)
        if new_text and hasattr(node, "update") and callable(getattr(node, "update", None)):
            try:
                node.update(new_text)
            except Exception as e:
                print(f"[node_update] update() fallito su {node!r}: {e}")

        # 3. Figli (container già montato)
        if new_children and hasattr(node, "remove_children") and hasattr(node, "mount"):
            try:
                await node.remove_children()
                await node.mount(*new_children)
            except Exception as e:
                print(f"[node_update] impossibile aggiornare i figli di {node!r}: {e}")

        return node

    def dom_get(self, widget_id: str):
        """Restituisce il widget Textual live con quell'id, o None."""
        return self.widgets.get(widget_id)

    async def dom_update(self, widget_id: str, context: Dict[str, Any]):
        """Applica node_update() al widget live con quell'id."""
        node = self.dom_get(widget_id)
        if node is None:
            print(f"[dom_update] Nessun widget live con id '{widget_id}'")
            return None
        return await self.node_update(node, context)

    async def dom_replace(self, widget_id: str, tag: str, attrs_dict: Dict[str, Any] = None, inner: List[Any] = None):
        """
        Sostituisce completamente il widget con quell'id: lo smonta e monta
        un widget nuovo al suo posto. Usare quando cambia il TIPO di widget
        (es. da <text> a <input>), non solo il suo contenuto — in quel caso
        node_update()/dom_update() bastano e sono più economici.
        """
        old = self.dom_get(widget_id)
        new_attrs = dict(attrs_dict or {})
        new_attrs.setdefault("id", widget_id)
        new_widget = self.mount_tag(tag, new_attrs, inner or [])

        if old is not None and getattr(old, "parent", None) is not None:
            parent = old.parent
            await old.remove()
            await parent.mount(new_widget)

        self.widgets.register(widget_id, new_widget)
        return new_widget

    async def dom_remove(self, widget_id: str):
        """Rimuove un widget dalla UI (se montato) e dal registro."""
        node = self.dom_get(widget_id)
        if node is not None and getattr(node, "parent", None) is not None:
            await node.remove()
        self.widgets.forget(widget_id)