"""Base agnostica per gli adapter della porta presentation.

Le implementazioni concrete devono vivere in un modulo backend-specifico e
fornire il rendering, il lifecycle e la gestione del DOM del proprio runtime.
Questo modulo non importa alcun toolkit UI.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import framework.core.flow as flow
import framework.service.dom as dom
import framework.port.presentation as presentation


def protect_editor_jinja_delimiters(root):
    """Protegge il markup Jinja scritto dentro i contenuti degli editor."""
    replacements = {
        "{{": "__OMNI_LBRACE____OMNI_LBRACE__",
        "}}": "__OMNI_RBRACE____OMNI_RBRACE__",
        "{%": "__OMNI_LBRACE____OMNI_PERCENT__",
        "%}": "__OMNI_PERCENT____OMNI_RBRACE__",
        "{#": "__OMNI_LBRACE____OMNI_HASH__",
        "#}": "__OMNI_HASH____OMNI_RBRACE__",
    }

    def protect(value):
        if not value:
            return value
        for source, target in replacements.items():
            value = value.replace(source, target)
        return value

    def protect_editor_content(element, inside_storekeeper=False):
        is_storekeeper = element.tag.split("}")[-1].lower() == "storekeeper"
        skip_content = inside_storekeeper or is_storekeeper
        if not skip_content:
            element.text = protect(element.text)
        for child in list(element):
            protect_editor_content(child, skip_content)
            if not skip_content:
                child.tail = protect(child.tail)

    for editor in root.iter():
        if editor.attrib.get("type") == "editor":
            protect_editor_content(editor)

    protected = dom.serialize(root)
    return (
        protected
        .replace("__OMNI_LBRACE__", "&#123;")
        .replace("__OMNI_RBRACE__", "&#125;")
        .replace("__OMNI_PERCENT__", "%")
        .replace("__OMNI_HASH__", "#")
    )


class NodeRegistry:
    """Registro backend-agnostico dei nodi live indicizzati per id."""

    def __init__(self):
        self._nodes: Dict[str, Any] = {}

    def register(self, node_id: Optional[str], instance):
        if node_id:
            self._nodes[node_id] = instance
        return instance

    def get(self, node_id: Optional[str]):
        return self._nodes.get(node_id) if node_id else None

    def forget(self, node_id: Optional[str]):
        if node_id:
            self._nodes.pop(node_id, None)

    def forget_all(self):
        self._nodes.clear()

    def __contains__(self, node_id) -> bool:
        return node_id in self._nodes


class Adapter(presentation.Port, ABC):
    """Contratto comune per costruire nuovi adapter di presentation.

    La logica condivisa del DSL e della sessione e' implementata da
    :class:`framework.port.presentation.Port`. Un adapter concreto deve
    definire almeno i metodi astratti dichiarati da ``Port``:
    ``mount_view``, ``mount_route``, ``mount_css``, ``node_create``,
    ``node_update`` e ``rebuild``.

    ``tags`` e ``capabilities`` appartengono al backend concreto: la base non
    presume se il rendering avvenga in HTML, in una TUI o in un altro runtime.
    """

    tags = {}
    capabilities = dict(presentation.Port.capabilities)

    def __init__(self, loader, defender, messenger, authenticator, **constants):
        super().__init__(
            loader,
            defender,
            messenger,
            authenticator,
            **constants,
        )
        self._render_lock = asyncio.Lock()
        self._rebuild_lock = asyncio.Lock()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._pending_rebuilds: Dict[
            str, tuple[Any, Dict[str, Any] | None]
        ] = {}
        self.nodes = NodeRegistry()

    async def start(self, session):
        """Crea la sessione, prepara le route e avvia il runtime concreto."""
        logger = getattr(self, "logger", None)
        if logger:
            logger.info(
                "Adapter.start: inizio",
                adapter=getattr(self, "name", None) or type(self).__name__,
                type=type(self).__name__,
            )
        session_result = await self.defender.session_create()
        self.session = flow.output(session_result)
        if logger:
            logger.debug("Adapter.start: sessione creata")
        await self.parse_route()
        if logger:
            logger.info("Adapter.start: route registrate", routes=len(self.routes))
        return await self._run_runtime()

    async def shutdown(self):
        if getattr(self, "session", None) is not None:
            await self.session.close()
        await self._shutdown_runtime()

    async def mount_view(self, url):
        self._prepare_runtime()
        logger = getattr(self, "logger", None)
        route_info, _params = self.match_route(url, "GET")
        if not route_info:
            raise KeyError(f"Nessuna rotta GET trovata per l'URL '{url}'")

        view_path = route_info.get("view")
        controllers = route_info.get("controllers") or []
        if logger:
            logger.info("mount_view: route trovata", url=url, view=view_path, controllers=controllers)
        xml_view = flow.output(await self.loader.resource(view_path))
        if logger:
            logger.debug("mount_view: XML caricato", size=len(xml_view))
        self._current_view_text = xml_view
        self._current_view_controllers = controllers
        return await self.render_template(
            self.session,
            controllers=controllers,
            text=xml_view,
            source_name=view_path,
        )

    async def render_view(self, url):
        self._prepare_runtime()
        self.url = url
        logger = getattr(self, "logger", None)
        if logger:
            logger.info("render_view: inizio", url=url)
        async with self._render_lock:
            result = await self.mount_view(url)
            if not flow.check(result):
                if logger:
                    logger.error("render_view: template fallito", result=flow.output(result))
                return result
            screen = flow.output(result)
            if logger:
                logger.info("render_view: screen creato", screen=type(screen).__name__)
            await self._show_screen(screen)
            await self._flush_pending_rebuilds()
            if logger:
                logger.info("render_view: screen montato")
            return result

    async def navigate_to(self, url: str, modal: bool = False):
        self._prepare_runtime()
        self.url = url
        async with self._render_lock:
            result = await self.mount_view(url)
            if not flow.check(result):
                return result
            screen = flow.output(result)
            if modal:
                await self._push_screen(screen)
            else:
                await self._show_screen(screen)
            await self._flush_pending_rebuilds()
        return result

    async def open_modal(self, view_path: str, **context):
        xml_view = flow.output(await self.loader.resource(view_path))
        modal = await self.render_template(
            self.session,
            text=xml_view,
            controllers=self.routes[view_path]["GET"].get("controllers", []),
            **context,
        )
        await self._push_screen(modal)
        return modal

    async def open_registered_modal(self, modal_id: str):
        xml_fragment = self.DOM.get(modal_id)
        if xml_fragment is None:
            return None
        modal = await self.render_template(
            self.session,
            text=xml_fragment,
            controllers=getattr(self, "_current_view_controllers", []),
        )
        await self._push_screen(modal)
        return modal

    def close_modal(self) -> None:
        self._close_modal_runtime()

    async def go_back(self):
        self._prepare_runtime()
        await self._pop_screen()

    async def mount_route(self, routes):
        for path, methods_dict in self.routes.items():
            for _method, data in methods_dict.items():
                self.views[path] = data.get("view")

    async def node_update(self, node, context: Dict[str, Any] = None):
        """Aggiorna un nodo usando le primitive del backend concreto."""
        descriptor = self.node_union({"attrs": {}, "inner": []}, context or {})
        new_attrs = descriptor["attrs"]
        new_text, new_children = presentation.split_text_and_children(
            descriptor["inner"]
        )

        if new_attrs:
            self._apply_node_attrs(node, new_attrs)

        if new_text and hasattr(node, "update"):
            try:
                node.update(new_text)
            except Exception:
                pass

        if new_children and hasattr(node, "remove_children") and hasattr(node, "mount"):
            try:
                await node.remove_children()
                await node.mount(*new_children)
            except Exception:
                pass

        return node

    def node_create(self, tag, attrs=None, inner=None):
        attrs = attrs or {}
        inner = inner or []
        if not (callable(tag) and type(tag).__name__ == "function"):
            raise NotImplementedError(
                "node_create richiede una factory callable del backend"
            )
        instance = tag({"inner": inner, "attrs": attrs})
        return self._register_node(attrs.get("id"), instance)

    async def dom_update(self, widget_id: str, context: Dict[str, Any]):
        node = self.dom_get(widget_id)
        if node is None:
            return None
        return await self.node_update(node, context)

    async def dom_replace(
        self,
        widget_id: str,
        tag: str,
        attrs_dict: Dict[str, Any] = None,
        inner: List[Any] = None,
    ):
        old = self.dom_get(widget_id)
        new_attrs = dict(attrs_dict or {})
        new_attrs.setdefault("id", widget_id)
        new_widget = self.mount_tag(tag, new_attrs, inner or [])

        if old is not None and getattr(old, "parent", None) is not None:
            parent = old.parent
            await old.remove()
            await parent.mount(new_widget)

        self._register_node(widget_id, new_widget)
        return new_widget

    async def dom_remove(self, widget_id: str):
        node = self.dom_get(widget_id)
        if node is not None and getattr(node, "parent", None) is not None:
            await node.remove()
        self._forget_node(widget_id)

    @abstractmethod
    def dom_get(self, widget_id: str):
        """Restituisce il nodo live del backend per il suo identificativo."""
        pass

    @abstractmethod
    def _apply_node_attrs(self, node, attrs_dict: Dict[str, Any]):
        """Applica gli attributi DSL secondo le regole del backend."""
        pass

    def _register_node(self, widget_id: str, node):
        return self.nodes.register(widget_id, node)

    def _forget_node(self, widget_id: str):
        self.nodes.forget(widget_id)

    async def _flush_pending_rebuilds(self):
        pending = self._pending_rebuilds
        self._pending_rebuilds = {}
        for node_id, (session, context) in pending.items():
            await self.rebuild(session, node_id, context)

    @abstractmethod
    async def _run_runtime(self):
        pass

    async def _shutdown_runtime(self):
        pass

    def _prepare_runtime(self):
        pass

    @abstractmethod
    async def _show_screen(self, screen):
        pass

    @abstractmethod
    async def _push_screen(self, screen):
        pass

    @abstractmethod
    async def _pop_screen(self):
        pass

    def _close_modal_runtime(self):
        return None

    async def rebuild(
        self,
        session,
        node_id: str,
        context: Dict[str, Any] = None,
        dsl_alias: str = None,
    ):
        """Serializza i rebuild e delega la sostituzione al backend concreto."""
        async with self._rebuild_lock:
            return await self._rebuild(session, node_id, context, dsl_alias)

    @abstractmethod
    async def _rebuild(
        self,
        session,
        node_id: str,
        context: Dict[str, Any] = None,
        dsl_alias: str = None,
    ):
        """Ricostruisce un nodo usando le primitive del backend."""
        pass
