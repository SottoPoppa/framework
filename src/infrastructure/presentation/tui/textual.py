import asyncio
import re
from time import perf_counter
from collections import OrderedDict
from pathlib import Path
import framework.core.flow as flow
import framework.service.dom as dom
from framework.service.diagnostic import LogBuffer, get_logger
import xml.etree.ElementTree as ET
from typing import Dict, Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import (
    Button, Input, Select, TextArea, Static, Tab, RichLog,
)
from textual.containers import Horizontal
from textual.screen import Screen, ModalScreen
from textual.events import Click
from infrastructure.presentation.tui.widgets import (
    tags,
    attrs,
    XmlScreen,
    XmlModalScreen,
)

from infrastructure.presentation.adapter import (
    Adapter as PresentationAdapter,
    protect_editor_jinja_delimiters,
)
from framework.manager.defender import Manager as Defender
from framework.manager.messenger import Manager as Messenger
from framework.manager.loader import Loader
from framework.manager.authenticator import Manager as Authenticator


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LOG_LEVEL = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")


def _entry_level(entry: str) -> str | None:
    match = _LOG_LEVEL.search(_ANSI_ESCAPE.sub("", entry))
    return match.group(1) if match else None


class LogScreen(ModalScreen):
    """Visualizza le righe raccolte dal logger locale del TUI."""

    BINDINGS = [
        Binding("escape", "close", "Chiudi", show=False),
        Binding("ctrl+c", "copy_log", "Copia log", show=False),
    ]
    DEFAULT_CSS = """
    LogScreen {
        align: center middle;
    }

    LogScreen RichLog {
        width: 90%;
        height: 80%;
        border: round $accent;
        background: $surface;
    }

    LogScreen #log-toolbar {
        width: 90%;
        height: auto;
        padding: 0 1;
        layout: horizontal;
    }

    LogScreen #log-filter {
        width: 24;
    }

    LogScreen #copy-hint {
        width: auto;
        margin-left: 1;
        color: $text-muted;
        display: none;
    }

    LogScreen #copy-hint.visible {
        display: block;
    }
    """

    def __init__(self, log_buffer: LogBuffer, **kwargs):
        super().__init__(**kwargs)
        self.log_buffer = log_buffer
        self._rendered_snapshot = None
        self._rendered_level = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Select(
                [("Tutti", "ALL"), ("Debug", "DEBUG"), ("Info", "INFO"),
                 ("Warning", "WARNING"), ("Error", "ERROR"),
                 ("Critical", "CRITICAL")],
                value="ALL",
                id="log-filter",
            ),
            Static("Ctrl+C copia log", id="copy-hint"),
            id="log-toolbar",
        )
        log_widget = RichLog(id="runtime-log", highlight=True, markup=False)
        log_widget.can_focus = True
        yield log_widget

    def on_mount(self) -> None:
        self._refresh_log()
        self.set_interval(1.0, self._refresh_log)

    def _set_copy_hint(self, visible: bool) -> None:
        hint = self.query_one("#copy-hint", Static)
        hint.set_class(visible, "visible")

    def on_focus(self, event) -> None:
        if isinstance(event.widget, RichLog):
            self._set_copy_hint(True)

    def on_blur(self, event) -> None:
        if isinstance(event.widget, RichLog):
            self._set_copy_hint(False)

    def _refresh_log(self) -> None:
        log_widget = self.query_one("#runtime-log", RichLog)
        selected_level = self.query_one("#log-filter", Select).value
        snapshot = self.log_buffer.snapshot()
        if snapshot == self._rendered_snapshot and selected_level == self._rendered_level:
            return

        scroll_position = log_widget.scroll_y
        follow_tail = scroll_position >= log_widget.max_scroll_y

        log_widget.clear()
        for entry in snapshot:
            if selected_level != "ALL" and _entry_level(entry) != selected_level:
                continue
            for line in entry.splitlines():
                log_widget.write(_ANSI_ESCAPE.sub("", line), scroll_end=False)
        self._rendered_snapshot = snapshot
        self._rendered_level = selected_level
        if follow_tail:
            log_widget.scroll_end(animate=False)
        else:
            log_widget.scroll_to(y=scroll_position, animate=False)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "log-filter":
            self._refresh_log()

    def action_copy_log(self) -> None:
        selected_level = self.query_one("#log-filter", Select).value
        entries = []
        for entry in self.log_buffer.snapshot():
            if selected_level != "ALL" and _entry_level(entry) != selected_level:
                continue
            entries.append(_ANSI_ESCAPE.sub("", entry))
        self.app.copy_to_clipboard("\n".join(entries))
        self.notify("Log copiato negli appunti")

    async def action_close(self) -> None:
        await self.dismiss()


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
        ("ctrl+c", "quit", "Esci"),
        ("ctrl+s", "save", "Salva"),
        ("ctrl+l", "show_log", "Log"),
    ]

    def __init__(self, adapter, **kwargs):
        super().__init__(**kwargs)
        self.adapter = adapter

    def _form_payload(self):
        payload = {}
        fields = []
        active_screen = getattr(self, "screen", None)
        for widget_type in (Input, TextArea, Select):
            if active_screen is not None:
                fields.extend(active_screen.query(widget_type))
            else:
                fields.extend(self.query(widget_type))
        for field in fields:
            node = self.adapter.node_get(field.id)
            if node is None:
                continue
            attributes = dom.attributes_from_tag(node)
            name = attributes.get("name") or field.id
            value = getattr(field, "value", "")
            payload[name] = "" if value is None else str(value)
        return payload

    @flow.request_boundary
    async def _send_dsl_event(self, event_name, message):
        if not isinstance(event_name, str) or ":" not in event_name:
            return
        receiver, domain = event_name.split(":", 1)
        if not receiver or not domain:
            return
        await self.adapter.messenger.send(
            self.adapter.session,
            adapter="dsl",
            receiver=receiver,
            domain=domain,
            message=message,
        )

    def check_action(self, action, parameters):
        widget = self.focused

        if action == "save":
            return isinstance(widget, TextArea)

        if action == "close_tab":
            return isinstance(widget, Tab)

        return True

    @flow.request_boundary
    async def action_save(self):
        focused = self.focused

        if not isinstance(focused, TextArea):
            return

        selected = self.adapter.session.context.get("selected")
        if not selected:
            await self.adapter.messenger.send(
                self.adapter.session,
                receiver="console",
                domain="error",
                message="Nessun file selezionato.",
            )
            return

        storekeeper = self.adapter.loader.get_managers().get("storekeeper")
        if storekeeper is None:
            await self.adapter.messenger.send(
                self.adapter.session,
                receiver="console",
                domain="error",
                message="Storekeeper non disponibile.",
            )
            return

        result = await storekeeper.change(
            self.adapter.session,
            repository="file",
            filter={"eq": {"filename": selected}},
            payload={"content": focused.text},
        )
        if not flow.check(result):
            await self.adapter.messenger.send(
                self.adapter.session,
                receiver="console",
                domain="error",
                message=f"Salvataggio fallito: {flow.output(result)}",
            )
            return

        await self.adapter.messenger.send(
            self.adapter.session,
            receiver="console",
            domain="info",
            message=f"File salvato: {selected}",
        )

    async def action_show_log(self) -> None:
        if isinstance(self.screen, LogScreen):
            return
        await self.push_screen(LogScreen(self.adapter.log_buffer))

    async def on_mount(self) -> None:
        self.adapter.logger.debug(
            "Textual.on_mount: iniziato",
            screen_stack=len(self._screen_stack),
        )
        self.adapter.logger.debug("Textual.on_mount: avvio render diretto")
        await self._render_initial_view()

    async def _render_initial_view(self) -> None:
        started = perf_counter()
        try:
            result = await self.adapter.render_view(url="/")
            if not flow.check(result):
                self.adapter.logger.error(
                    "Rendering iniziale fallito",
                    result=flow.output(result),
                )
                raise RuntimeError(flow.output(result))
            self.adapter.logger.info(
                "Rendering iniziale completato",
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
        except Exception as error:
            self.adapter.logger.error(
                "Eccezione durante il rendering iniziale",
                exception=error,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            await self.mount(
                Static(
                    f"Initial render failed: {type(error).__name__}: {error}",
                    id="initial-render-error",
                )
            )

    @flow.request_boundary
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        w = self.adapter.node_get(event.button.id)
        click = getattr(event.button, "_dsl_click", None)

        if w is None and not click:
            return

        attrs_tag = dom.attributes_from_tag(w) if w is not None else {}

        # Se il pulsante ha un attributo route, naviga a quella URL
        route = getattr(event.button, "_dsl_route", None) or attrs_tag.get("route")
        if route:
            if isinstance(route, str) and route.startswith("#"):
                await self.adapter.open_registered_modal(route[1:])
                return
            await self.adapter.navigate_to(route)
            return

        click = attrs_tag.get("click") or click
        if click == "modal:close":
            self.adapter.close_modal()
            return

        message = (
            self._form_payload()
            if attrs_tag.get("form")
            else getattr(event.button, "_dsl_value", None) or str(event.button.id)
        )
        if getattr(event.button, "_dsl_has_value", False):
            message = {"value": message}
        await self._send_dsl_event(click, message)

    @flow.request_boundary
    async def on_click(self, event: Click) -> None:
        widget = event.widget
        source = widget
        while source is not None and not getattr(source, "_dsl_click", None):
            source = getattr(source, "parent", None)

        if source is None:
            parent = getattr(widget, "parent", None)
            while parent is not None and not hasattr(parent, "_dsl_tab_events"):
                parent = getattr(parent, "parent", None)
            tab_events = getattr(parent, "_dsl_tab_events", {})
            active_tab = getattr(parent, "active_tab", None)
            event_data = tab_events.get(getattr(active_tab, "id", None))
            if event_data is None:
                event_data = tab_events.get(getattr(widget, "id", None))
            if event_data:
                click, value = event_data
                await self._send_dsl_event(click, str(value))
            return

        await self._send_dsl_event(
            source._dsl_click,
            str(getattr(source, "_dsl_value", "")),
        )

    @flow.request_boundary
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        node = self.adapter.node_get(event.input.id)
        if node is None:
            return
        attributes = dom.attributes_from_tag(node)
        if 'submit' in attributes:
            await self._send_dsl_event(attributes['submit'], str(event.value))
    
    @flow.request_boundary
    async def on_input_changed(self, event: Input.Changed) -> None:
        node = self.adapter.node_get(event.input.id)
        if node is None:
            return
        attributes = dom.attributes_from_tag(node)
        if 'change' in attributes:
            await self._send_dsl_event(attributes['change'], str(event.value))

    @flow.request_boundary
    async def on_select_changed(self, event: Select.Changed) -> None:
        w = self.adapter.node_get(event.select.id)

        if w is not None:
            attrs_tag = dom.attributes_from_tag(w)
            initial_value = attrs_tag.get("value")
            if initial_value is not None and str(event.value) == str(initial_value):
                return
            await self._send_dsl_event(attrs_tag.get("change"), str(event.value))


class Adapter(PresentationAdapter):
    """
    Adapter Textual nativo per il Framework.

    Implementa presentation.Port. La chiave di ogni voce di `tags` deve
    corrispondere a un valore di presentation.Tag; la sotto-chiave al
    valore dell'attributo `type="..."` nel DSL (o al nome del tag stesso),
    replicando la logica di mount_tag():

        tipo = attrs.get("type") or tag
        elemento = self.tags[tag].get(tipo) or self.tags[tag].get(tag)
    """

    tags = tags

    def __init__(
        self,
        loader: Loader,
        defender: Defender,
        messenger: Messenger,
        authenticator: Authenticator,
        log_buffer: LogBuffer,
        **constants,
    ):
        """
        Inizializza l'adapter Textual.

        Args (via dependency injection dal container):
            loader: Manager per il caricamento delle risorse
            defender: Manager per autenticazione/autorizzazione
            messenger: Manager per messaggistica
            executor: Manager per esecuzione DSL
            **constants: Configurazione da pyproject.toml (adapter.registry)
        """
        super().__init__(loader, defender, messenger, authenticator, **constants)
        self.log_buffer = log_buffer
        self.logger = get_logger("tui")
        self._storekeeper_file_cache = OrderedDict()
        self.active_screens: Dict[str, Screen] = {}
        self.widgets = self.nodes  # alias compatibile per il runtime Textual
        self.app = AppDinamica(self)
        self.validate_adapter()

    async def _load_storekeeper(self, runtime_session, attributes):
        request = dict(attributes)
        filters = request.get("filter")
        equalities = filters.get("eq") if isinstance(filters, dict) else None
        filename = equalities.get("filename") if isinstance(equalities, dict) else None
        is_file_read = (
            set(request).issubset({"repository", "filter", "operation", "id", "type"})
            and
            request.get("repository") == "file"
            and str(request.get("operation", "gather")).casefold() in {"gather", "read"}
            and isinstance(filename, str)
            and bool(filename)
            and set(filters) == {"eq"}
            and set(equalities) == {"filename"}
        )
        if not is_file_read:
            return await super()._load_storekeeper(runtime_session, attributes)

        storekeeper = self.loader.get_managers().get("storekeeper")
        repository = getattr(storekeeper, "maked", {}).get("file")
        profiles = set(getattr(repository, "location", {}))
        all_local_providers = [
            provider
            for provider in getattr(storekeeper, "persistences", [])
            if isinstance(getattr(provider, "config", None), dict)
            and getattr(provider, "path", None) is not None
        ]
        providers = [
            provider
            for provider in all_local_providers
            if str(getattr(provider, "config", {}).get("name", "")).casefold()
            in profiles
        ]
        if repository is None and len(all_local_providers) == 1:
            providers = all_local_providers
        if len(providers) != 1:
            return await super()._load_storekeeper(runtime_session, attributes)

        try:
            root = Path(providers[0].path).resolve()
            path = Path(filename)
            path = path if path.is_absolute() else root / path
            path = path.resolve()
            path.relative_to(root)
            current_stat = path.stat()
        except (OSError, TypeError, ValueError):
            return await super()._load_storekeeper(runtime_session, attributes)
        if not path.is_file():
            return await super()._load_storekeeper(runtime_session, attributes)

        cache_key = (id(runtime_session), str(path.resolve()))
        file_version = (
            current_stat.st_mtime_ns,
            current_stat.st_ctime_ns,
            current_stat.st_size,
        )
        cached = self._storekeeper_file_cache.get(cache_key)
        if cached is not None and cached[0] == file_version:
            self._storekeeper_file_cache.move_to_end(cache_key)
            return cached[1]

        content = await super()._load_storekeeper(runtime_session, attributes)
        try:
            updated_stat = path.stat()
        except OSError:
            return content
        if path.is_file() and file_version == (
            updated_stat.st_mtime_ns,
            updated_stat.st_ctime_ns,
            updated_stat.st_size,
        ):
            self._storekeeper_file_cache[cache_key] = (file_version, content)
            self._storekeeper_file_cache.move_to_end(cache_key)
            if len(self._storekeeper_file_cache) > 32:
                self._storekeeper_file_cache.popitem(last=False)
        return content

    def _ensure_active_app(self):
        if hasattr(self, 'app') and self.app:
            from textual._context import active_app
            try:
                active_app.get()
            except LookupError:
                active_app.set(self.app)

    def mount_css(self, css_content: str) -> None:
        """Inietta lo stile nell'applicazione."""
        if self.app:
            self._ensure_active_app()
            self.app.stylesheet.add_source(css_content)
            self.app.stylesheet.parse()
            self.app.refresh_css()

    async def _run_runtime(self):
        self.logger.info("Avvio runtime Textual")
        await self.app.run_async()
        self.logger.info("Runtime Textual terminato")

        application = getattr(self.loader, "app", None)
        stop_event = getattr(application, "_stop_event", None)
        if stop_event is not None:
            stop_event.set()

    async def _shutdown_runtime(self):
        if self.app:
            self.app.exit()

    def _prepare_runtime(self):
        self._ensure_active_app()

    async def _show_screen(self, screen):
        started = perf_counter()
        self.logger.debug(
            "Textual._show_screen: inizio",
            screen=type(screen).__name__,
            screen_stack=len(self.app._screen_stack),
        )
        if self.app.screen.id == "_default":
            await self.app.push_screen(screen)
        else:
            await self.app.switch_screen(screen)
        self.logger.debug(
            "Textual._show_screen: completato",
            screen_stack=len(self.app._screen_stack),
            active=type(self.app.screen).__name__,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )

    async def _push_screen(self, screen):
        await self.app.push_screen(screen)

    async def _pop_screen(self):
        self.app.pop_screen()

    def _close_modal_runtime(self):
        if isinstance(self.app.screen, ModalScreen):
            self.app.pop_screen()

    async def _rebuild(
        self,
        session,
        node_id: str,
        context: Dict[str, Any] = None,
        dsl_alias: str = None,
    ):
        """Ricalcola il DOM e sostituisce solo il widget richiesto."""
        self._ensure_active_app()

        # Un evento Select può arrivare nello stesso ciclo in cui il template
        # sta ancora montando i widget. Lasciamo terminare quel mount prima di
        # cercare il widget da sostituire.
        await asyncio.sleep(0)

        # IMPORTANTE: va preso PRIMA di chiamare render_template(), perché
        # render_template -> mount_tag -> node_create sovrascrive subito
        # self.widgets[node_id] con la nuova istanza (ancora non montata).
        # Se lo prendi dopo, dom_get() ti restituisce rendered_node stesso.
        old_widget = self.dom_get(node_id)
        if old_widget is None:
            self.widgets.forget(node_id)
            if getattr(self, "url", None) and not self._render_lock.locked():
                await self.render_view(self.url)
                return self.dom_get(node_id)
            self._pending_rebuilds[node_id] = (session, context)
            return None

        # Il DOM contiene XML già elaborato da Jinja. Ricalcoliamo la sorgente
        # in memoria per aggiornare DOM senza sostituire la schermata attiva.
        view_text = getattr(self, "_current_view_text", None)
        if view_text:
            await self.render_template(
                session,
                controllers=getattr(self, "_current_view_controllers", []),
                text=view_text,
                _fragment_refresh=True,
            )

        xml_fragment = self.DOM.get(node_id)
        if xml_fragment is None:
            raise LookupError(f"Nodo XML '{node_id}' non trovato nel DOM")

        fragment_root = ET.fromstring(xml_fragment)
        protected_fragment = protect_editor_jinja_delimiters(fragment_root)
        rendered_node = await self.render_template(
            session,
            controllers=[],
            text=protected_fragment,
        )

        parent = old_widget.parent
        if parent is None:
            raise RuntimeError(
                f"Widget '{node_id}' non ha un parent montato"
            )

        sibling_index = list(parent.children).index(old_widget)
        await old_widget.remove()
        await parent.mount(rendered_node, before=sibling_index)

        self.widgets.register(node_id, rendered_node)  # ridondante (node_create l'ha già fatto), ma innocuo

        return rendered_node

    def dom_get(self, widget_id):
        """Restituisce il widget Textual live con quell'id, o None."""
        try:
            return self.app.query_one(f"#{widget_id}")
        except Exception:
            widget = self.widgets.get(widget_id)
            if widget is not None and getattr(widget, "parent", None) is not None:
                return widget
            self.widgets.forget(widget_id)
            return None

    def _apply_node_attrs(self, node, attrs_dict: Dict[str, Any]):
        attrs(node, attrs_dict)

    def _register_node(self, widget_id: str, node):
        return self.widgets.register(widget_id, node)

    def _forget_node(self, widget_id: str):
        self.widgets.forget(widget_id)

