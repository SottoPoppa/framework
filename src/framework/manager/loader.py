import ast
import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import signal
import sys
import types
import uuid
from dataclasses import dataclass, field
from functools import partial
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any, Optional, Type, TypedDict, get_args, get_type_hints

from jinja2 import BaseLoader, Environment
import framework.core.flow as flow
import framework.service.scheme as scheme

# ============================================================
# RESOURCE
# ============================================================

@dataclass
class Resource:
    """Rappresenta una risorsa/modulo gestita dal kernel del framework."""
    name: str
    path: str
    module: Any = None
    kind: Optional[str] = None
    config: dict = field(default_factory=dict)
    extend: dict = field(default_factory=dict)


class LoaderContext(TypedDict, total=False):
    """Stato condiviso dagli step delle pipe del Loader."""

    config_path: Any
    kwargs: dict
    config_file: str
    schemes: dict
    config: dict
    manager_resources: tuple[Resource, ...]
    adapter_resources: tuple[Resource, ...]
    discovery: tuple[dict, tuple[Resource, ...]]
    managers: dict
    session: Any


# ============================================================
# HANDLE
# ============================================================

class Handle:
    """
    Proxy thread-safe ed elevata stabilità per l'hot-reloading dei componenti.
    Mantiene l'identità del riferimento sostituendo l'istanza interna al runtime.
    """

    def __init__(self, obj: Any = None):
        object.__setattr__(self, "_obj", None)
        object.__setattr__(self, "_state", {})
        if obj is not None:
            self.swap(obj)

    def swap(self, new_obj: Any) -> None:
        """Sostituisce l'oggetto sottostante preservando lo stato accumulato."""
        old = self._obj
        if old is not None and new_obj is not None:
            for k, v in getattr(old, "__dict__", {}).items():
                if k != "__dict__":
                    try:
                        setattr(new_obj, k, v)
                    except Exception:
                        pass

        object.__setattr__(self, "_obj", new_obj)
        if new_obj is not None:
            for k, v in self._state.items():
                try:
                    setattr(new_obj, k, v)
                except Exception:
                    pass

    def __getattr__(self, name: str) -> Any:
        obj = object.__getattribute__(self, "_obj")
        if obj is None:
            raise AttributeError(f"Handle vuoto: impossibile accedere a '{name}'")
        return getattr(obj, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_obj", "_state"):
            object.__setattr__(self, name, value)
            return
        self._state[name] = value
        if self._obj is not None:
            setattr(self._obj, name, value)

    def __repr__(self) -> str:
        return f"<Handle ({self._obj})>" if self._obj else "<Handle (empty)>"

# ============================================================
# LOADER (COMPOSITION ROOT)
# ============================================================

class Loader:
    """Composition Root responsabile dell'infezione delle dipendenze e del wiring."""

    cores = {

        "flow": "src/framework/core/flow.py",
        "interpreter": "src/framework/core/interpreter.py",
        "compiler": "src/framework/core/compiler.py",
        "parser": "src/framework/core/parser.py",
        "model": "src/framework/core/model.py",
        "session": "src/framework/core/session.py",
        "runner": "src/framework/core/runner.py",
        "graph": "src/framework/core/graph.py",
        "execution": "src/framework/core/execution.py",
        "context": "src/framework/core/context.py",
        "ast": "src/framework/core/ast.py",
        "data": "src/framework/core/data.py",
        "scheme": "src/framework/core/scheme.py",
    }

    services = {
        #"flow": "src/framework/service/flow.py",
        "factory": "src/framework/service/factory.py",
        #"language": "src/framework/service/language.py",
        #"scheme": "src/framework/service/scheme.py",
        "manage": "src/framework/port/manage.py",
        "container": "src/framework/service/container.py",
        "introspection": "src/framework/service/introspection.py",
        "contract": "src/framework/service/contract.py",
        "route": "src/framework/service/route.py",
        "template": "src/framework/service/template.py",
        "diagnostic": "src/framework/service/diagnostic.py",
    }

    ports = {
        "message": "src/framework/port/message.py",
        "presentation": "src/framework/port/presentation.py",
        "persistence": "src/framework/port/persistence.py",
        "network": "src/framework/port/network.py",
        "authentication": "src/framework/port/authentication.py",
        "manager": "src/framework/port/manager.py",
    }

    managers = {
        "defender": "src/framework/manager/defender.py",
        "messenger": "src/framework/manager/messenger.py",
        "presenter": "src/framework/manager/presenter.py",
        "storekeeper": "src/framework/manager/storekeeper.py",
        "orchestrator": "src/framework/manager/orchestrator.py",
        "networker": "src/framework/manager/networker.py",
        "tester": "src/framework/manager/tester.py",
        "authenticator": "src/framework/manager/authenticator.py"
    }

    def __init__(self, framework, infrastructure):
        self.framework = framework
        self.infrastructure = infrastructure
        self.container = None
        self.handle = Handle(self)
        self.current_config = {}
        self.kwargs = {}
        self.app = None
        self._reload_lock = asyncio.Lock()

        sys.modules["framework.loader"] = sys.modules[__name__]

    def _resolve_dependency(self, dependency: Any) -> Any:
        """Risolve una singola dipendenza nel container."""
        if dependency is Loader:
            return self.handle

        if (
            isinstance(dependency, type)
            and getattr(dependency, "__module__", "").startswith("framework.port.")
        ):
            val = self.container.get_port(dependency)
            if val is None:
                raise RuntimeError(f"Porta non risolta: {dependency}")
            return val

        val = self.container.get(dependency)
        if val is None:
            name = getattr(dependency, "__name__", str(dependency))
            raise RuntimeError(f"Dipendenza non risolta: {name}")
        return val

    def _resolve_dependencies(self, cls: Type) -> list:
        deps = self.framework.dependencies_from_class(cls).get(cls, [])
        return [self._resolve_dependency(d) for d in deps]

    def _port_interface(self, port_key: str) -> Optional[Type]:
        module = sys.modules.get(f"framework.port.{port_key}")
        return getattr(module, "Port", None) if module else None

    def _adapter_specs(self, item: tuple[str, Any]) -> tuple[tuple[str, str, dict], ...]:
        port_key, enabled = item
        if port_key in {"project", "manager", "tool"} or not isinstance(enabled, dict):
            return ()
        return tuple(
            (
                port_key,
                adapter_name,
                {
                    key: value.casefold()
                    if key in ("name", "auth") and isinstance(value, str)
                    else value
                    for key, value in (cfg.items() if isinstance(cfg, dict) else [])
                },
            )
            for adapter_name, adapter_config in enabled.items()
            for cfg in (
                adapter_config
                if isinstance(adapter_config, (list, tuple))
                else [adapter_config]
            )
        )

    def _adapter_resource(self, spec: tuple[str, str, dict]) -> Resource:
        port_key, adapter_name, config = spec
        implementation = config.get("implementation")
        if implementation is None:
            path = Path("src/infrastructure") / port_key / f"{adapter_name}.py"
        else:
            if not isinstance(implementation, str) or not implementation:
                raise ValueError(
                    f"Implementazione adapter non valida per {port_key}.{adapter_name}"
                )
            implementation_path = Path(implementation)
            if implementation_path.is_absolute() or ".." in implementation_path.parts:
                raise ValueError(
                    f"Percorso implementazione adapter non valido: {implementation}"
                )
            path = (
                Path("src/infrastructure")
                / port_key
                / adapter_name
                / f"{implementation_path.with_suffix('')}.py"
            )
        return Resource(
            name=f"framework.adapter.{port_key}.{adapter_name}",
            path=str(path),
            kind="ADAPTER",
            config=[config],
        )

    def _manager_entry(self, resource: Resource) -> tuple[Type, Resource] | None:
        manager = getattr(resource.module, "Manager", None)
        return (manager, resource) if manager else None

    def _adapter_entries(self, resource: Resource) -> tuple[tuple[Resource, dict], ...]:
        if not resource.module or not getattr(resource.module, "Adapter", None):
            return ()
        configs = resource.config if isinstance(resource.config, list) else [resource.config]
        return tuple((resource, config or {}) for config in configs)

    async def _discover_adapters(self, config: dict) -> flow.Result:
        """Scopre e carica tutti gli adapter configurati."""
        return await flow.pipe(
            config,
            flow.map_items_tuple(),
            flow.tuple_map_tuple(self._adapter_specs),
            flow.tuple_flatten_tuple(),
            flow.tuple_map_tuple(self._adapter_resource),
            flow.pipe_foreach_tuple(self._load_resource),
            action="loader.discover_adapters",
        )

    async def _load_resource(self, resource: Resource) -> Resource:
        await self.framework.load(resource)
        return resource

    def _build(self, cls: Type, config: dict = None) -> Handle:
        config = config or {}
        args = self._resolve_dependencies(cls)
        return Handle(cls(*args, **config))

    def _build_managers(self, resources: list[Resource]) -> flow.Result:
        """Costruisce e registra i manager rispettando l'ordine di dipendenza."""
        return flow.pipe_sync(
            resources,
            flow.tuple_map_tuple(self._manager_entry),
            flow.tuple_filter_tuple(lambda entry: entry is not None),
            self._order_manager_entries,
            flow.tuple_map_tuple(self._build_manager_entry),
            action="loader.build_managers",
        )

    def _order_manager_entries(self, entries: tuple) -> tuple:
        classes = [cls for cls, _ in entries]
        dependencies = {}
        for cls in classes:
            dependencies.update(self.framework.dependencies_from_class(cls))
        order = self.framework.resolve_order(classes, dependencies)
        resources = {cls: resource for cls, resource in entries}
        return tuple((cls, resources[cls]) for cls in order if cls is not Loader)

    def _build_manager_entry(self, entry: tuple[Type, Resource]) -> Handle:
        cls, resource = entry
        obj = self._build(cls, resource.config or {})
        self.container.put(cls, obj, singleton=True)
        print(f"[✓] Manager {cls.__module__}.{cls.__name__}")
        return obj

    def _build_adapters(
        self, resources: list[Resource], save: bool = True
    ) -> flow.Result:
        """Costruisce gli adapter istanziati e li assegna alle rispettive porte."""
        return flow.pipe_sync(
            resources,
            flow.tuple_map_tuple(self._adapter_entries),
            flow.tuple_flatten_tuple(),
            flow.tuple_map_tuple(partial(self._build_adapter_entry, save=save)),
            action="loader.build_adapters",
        )

    def _build_adapter_entry(self, entry: tuple[Resource, dict], save: bool) -> Handle:
        resource, config = entry
        parts = resource.name.split(".")
        interface = self._port_interface(parts[2])
        adapter_cls = getattr(resource.module, "Adapter", None)
        if not interface or not adapter_cls:
            raise RuntimeError(f"Adapter non valido: {resource.name}")
        obj = self._build(adapter_cls, config)
        self._register_adapter_capabilities(parts[2], obj)
        if save:
            self.container.add_port(interface, obj)
        print(f"[✓] Adapter {adapter_cls.__name__} name={config.get('name')}")
        return obj

    def _register_adapter_capabilities(self, port: str, adapter: Any) -> None:
        capabilities = getattr(adapter, "capabilities", None)
        if not isinstance(capabilities, dict):
            raise RuntimeError(f"Adapter {port} privo di capabilities")
        capabilities_schema = getattr(scheme, "schemes", {}).get(f"{port}_adapter")
        if not capabilities_schema:
            raise RuntimeError(f"Schema sicurezza mancante per la Port '{port}'")
        result = scheme.normalize(capabilities, capabilities_schema)
        if not result.is_success:
            raise RuntimeError(f"Capabilities non valide per la Port '{port}': {result.output.error}")
        defender_resource = self.framework.component("framework.manager.defender")
        defender_cls = getattr(defender_resource.module, "Manager", None) if defender_resource else None
        defender = self.container.get(defender_cls) if defender_cls else None
        if defender and hasattr(defender, "_register_capabilities"):
            defender._register_capabilities(None, port, capabilities, adapter)

    async def reload(self, session: Any, changed_path: str | None) -> bool:
        """Esegue il reload in-memory di adapter o manager modificati."""
        if not isinstance(changed_path, str) or not changed_path.endswith(".py"):
            return False

        norm_path = changed_path.replace("\\", "/")
        async with self._reload_lock:
            if "/infrastructure/" in norm_path:
                parts = norm_path.split("/")
                idx = parts.index("infrastructure")
                if idx + 1 >= len(parts):
                    return False
                interface = f"framework.port.{parts[idx + 1]}.Port"
                old_handles = self.container.get_port(interface)
                resource = self.framework.resource_by_path(changed_path)
                if not resource:
                    return False

                await self.framework.reload(resource)
                new_handles = flow.unwrap(self._build_adapters([resource], save=False))
                for old, new in zip(old_handles or [], new_handles):
                    old.swap(new._obj)
                return True

            if "/framework/manager/" in norm_path:
                resource = self.framework.resource_by_path(changed_path)
                if not resource:
                    return False

                old_cls = getattr(resource.module, "Manager", None)
                if not old_cls:
                    return False

                old_handle = self.container.get(old_cls)
                await self.framework.reload(resource)
                new_cls = getattr(resource.module, "Manager", None)
                if not new_cls:
                    return False

                new_handle = self._build(new_cls, resource.config)
                if old_handle is None:
                    self.container.put(new_cls, new_handle, singleton=True)
                else:
                    old_handle.swap(new_handle._obj)
                    self.container.remove(old_cls)
                    self.container.put(new_cls, old_handle, singleton=True)
                return True

        return False

    async def load_schemes(self, directories: list) -> dict:
        return await self.infrastructure.load_schemes(directories)

    async def resource(self, path: Any) -> str:
        return await self.infrastructure.resource(path)

    def record_contract(self, test_path: str, outcome: dict):
        """Registra i risultati dei test di contratto."""
        contract_mod = sys.modules.get("framework.service.contract")
        contract = getattr(contract_mod, "Contract", None) if contract_mod else globals().get("Contract")
        
        reflect_mod = sys.modules.get("framework.service.introspection")
        reflection = getattr(reflect_mod, "Reflection", None) if reflect_mod else globals().get("Reflection")
        if not contract or not reflection:
            return

        norm_path = test_path.replace("\\", "/")
        if not norm_path.endswith(".test.dsl"):
            return

        source_path = norm_path[: -len(".test.dsl")] + ".py"
        resource = self.framework.resource_by_path(source_path)
        if not resource or not resource.module:
            return

        data = outcome.get("data", {})
        manifest = data.get("exports")
        contract_exports = manifest if isinstance(manifest, dict) else None
        declared_exports = None
        if isinstance(manifest, dict):
            declared_exports = []
            for methods in manifest.values():
                if isinstance(methods, list):
                    declared_exports.extend(methods)
                elif isinstance(methods, str):
                    declared_exports.append(methods)
        available = reflection.module_components(
            resource.module,
            set(declared_exports) if declared_exports is not None else None,
        )
        if not available:
            return

        if declared_exports is not None and not outcome.get("success"):
            return

        passed, failed = set(), set()
        for detail in data.get("details", []):
            target = detail.get("target")
            if not target:
                continue
            candidates = [str(target), str(target).rsplit(".", 1)[-1]]
            name = next((c for c in candidates if c in available), None)
            if name:
                (passed if detail.get("status") == "OK" else failed).add(name)

        tested = passed - failed
        if declared_exports is not None and tested != set(declared_exports):
            return
        if not tested:
            return

        hashes = {n: reflection.hash_text(available[n]) for n in tested}
        contract.record_tested(
            source_path,
            hashes,
            exports=contract_exports if contract_exports is not None else declared_exports,
        )
        print(f"[🔏] Contratto aggiornato: {source_path} → {', '.join(sorted(hashes))}")

    def get_managers(self) -> dict:
        """Restituisce il dizionario di tutti i manager registrati."""
        result = {"loader": self.handle}
        for res in self.framework.components_iter():
            if not res.name.startswith("framework.manager."):
                continue
            mgr_cls = getattr(res.module, "Manager", None)
            if mgr_cls:
                obj = self.container.get(mgr_cls)
                if obj:
                    result[res.name.split(".")[-1]] = obj
        return result

    def _discovery_context(self, config_toml_path: Any) -> LoaderContext:
        kwargs = (
            config_toml_path
            if isinstance(config_toml_path, dict)
            else {"config": str(config_toml_path)}
        )
        return {"kwargs": kwargs, "config_file": kwargs.get("config", "pyproject.toml")}

    async def _prepare_core(self, context: LoaderContext) -> LoaderContext:
        schemes = await self.load_schemes(["src/framework/scheme", "src/application/model"])
        core_scheme = importlib.import_module("framework.core.scheme")
        core_scheme.schemes.clear()
        core_scheme.schemes.update(schemes)
        core_scheme.jinja_env = self.infrastructure.jinja_env
        await self.framework.load_core(
            self.services,
            self.ports,
            extra_by_name={"scheme": {"schemes": schemes, "jinja_env": self.infrastructure.jinja_env}},
        )
        return {**context, "schemes": schemes}

    def _read_discovery_config(self, context: LoaderContext) -> LoaderContext:
        config = self.infrastructure.load_toml_config(context["config_file"])
        self.current_config = config
        return {**context, "config": config}

    def _manager_resource(self, item: tuple[str, str, dict]) -> Resource:
        name, path, config = item
        return Resource(
            name=f"framework.manager.{name}",
            path=path,
            kind="MANAGER",
            config=config,
        )

    async def _discover_manager_resources(self, config: dict) -> tuple[Resource, ...]:
        manager_config = config.get("manager", {})
        specs = tuple(
            (name, path, manager_config.get(name, {}))
            for name, path in self.managers.items()
        )
        resources = await flow.pipe(
            specs,
            flow.tuple_map_tuple(self._manager_resource),
            flow.tuple_map_async_tuple(self._load_resource),
            action="loader.discover_managers",
        )
        return flow.unwrap(resources)

    async def _discover_adapter_resources(self, config: dict) -> tuple[Resource, ...]:
        result = await self._discover_adapters(config)
        return flow.unwrap(result)

    async def _discover_resources(self, context: LoaderContext) -> LoaderContext:
        resources = await flow.pipe(
            context["config"],
            flow.pipe_fork_async_tuple(
                self._discover_manager_resources,
                self._discover_adapter_resources,
            ),
            action="loader.discover_resources",
        )
        manager_resources, adapter_resources = flow.unwrap(resources)
        return {
            **context,
            "manager_resources": manager_resources,
            "adapter_resources": adapter_resources,
        }

    def _discovery_result(self, context: dict) -> tuple[dict, tuple[Resource, ...], tuple[Resource, ...]]:
        return (
            context["config"],
            tuple(context["manager_resources"]),
            tuple(context["adapter_resources"]),
        )

    def _bootstrap_context(self, config_toml_path: Any) -> dict:
        kwargs = (
            config_toml_path
            if isinstance(config_toml_path, dict)
            else {"config": str(config_toml_path)}
        )
        self.kwargs = kwargs
        self.framework.strict = not (
            kwargs.get("dev")
            or kwargs.get("test") is not None
            or kwargs.get("test_integration") is not None
            or kwargs.get("skip_verify")
        )
        return {"config_path": config_toml_path}

    async def _prepare_container(self, context: LoaderContext) -> LoaderContext:
        container_mod = sys.modules.get("framework.service.container")
        if not container_mod or not hasattr(container_mod, "Container"):
            raise RuntimeError(
                "Impossibile trovare la classe Container in 'framework.service.container'"
            )
        container_cls = getattr(container_mod, "Container")
        self.container = container_cls()
        self.container.put(container_cls, self.container, singleton=True)
        return context

    async def _discover_bootstrap(self, context: LoaderContext) -> LoaderContext:
        discovery = await self._discover_components(context["config_path"])
        return {**context, "discovery": flow.unwrap(discovery)}

    def _build_runtime(self, context: LoaderContext) -> LoaderContext:
        config, mgr_resources, adapter_resources = context["discovery"]
        print("\n[*] Discovery...")
        print("\n[*] Build...")
        managers = flow.unwrap(self._build_managers(mgr_resources))
        flow.unwrap(self._build_adapters(adapter_resources))
        return {**context, "config": config, "managers": managers}

    async def _start_runtime(self, context: LoaderContext) -> LoaderContext:
        def_res = self.framework.component("framework.manager.defender")
        def_cls = getattr(def_res.module, "Manager", None) if def_res else None
        defender = self.container.get(def_cls) if def_cls else None
        session = None

        if defender:
            if hasattr(defender, "startup"):
                startup_result = await defender.startup()
                if flow.is_result(startup_result) and not flow.check(startup_result):
                    raise RuntimeError(flow.output(startup_result))
            if defender:
                self._apply_port_configurations(defender)
            if hasattr(defender, "session_create"):
                session = flow.output(await defender.session_create())
                print(f"[*] Sessione creata: {session}")

        return {**context, "session": session}

    def _apply_port_configurations(self, defender) -> None:
        """Pubblica le configurazioni DSL globali su manager e adapter."""
        manager_names = {
            "presentation": "presenter",
            "authentication": "authenticator",
            "persistence": "storekeeper",
            "message": "messenger",
        }
        managers = self.get_managers()
        for port, configuration in defender.port_configurations.items():
            manager = managers.get(manager_names.get(port, ""))
            targets = [manager] if manager is not None else []
            targets.extend(self.container.get_port(port))
            for target in targets:
                target.port_configuration = configuration
                configure = getattr(target, "configure_port", None)
                if callable(configure):
                    configure(configuration)

    async def _discover_components(self, config_toml_path: Any) -> flow.Result:
        """Carica core, manager e adapter senza istanziarli."""
        return await flow.pipe(
            config_toml_path,
            self._discovery_context,
            self._prepare_core,
            self._read_discovery_config,
            self._discover_resources,
            self._discovery_result,
            action="loader.discover_components",
        )

    async def bootstrap(self, config_toml_path: Any):
        """Inizializza il framework caricando configurazione e risorse."""
        return flow.unwrap(
            await flow.pipe(
                config_toml_path,
                self._bootstrap_context,
                self._discover_bootstrap,
                self._prepare_container,
                self._build_runtime,
                self._start_runtime,
                flow.map_construct_value(
                    partial(Application, self),
                    "managers",
                    "session",
                ),
                flow.pipe_tap_value(partial(setattr, self, "app")),
                action="loader.bootstrap",
            )
        )

    async def run_tests(self, filter_value: str | None = None) -> bool:
        """Esegue i test di contract DSL tramite il Manager del Tester."""
        return await self._run_tester_suite("run", filter_value)

    async def run_integration_tests(self, filter_value: str | None = None) -> bool:
        """Esegue gli scenari di integrazione DSL sul runtime bootstrap-ato."""
        return await self._run_tester_suite("run_integration", filter_value)

    async def _run_tester_suite(self, method_name: str, filter_value: str | None) -> bool:
        """Invoca una suite del Tester mantenendo il confine Flow nel Loader."""
        managers = self.get_managers()
        tester = managers.get("tester")
        if tester is None:
            print("[!] Manager 'tester' non trovato nel container")
            return False
        
        session = getattr(self.app, "_session", None)
        method = getattr(tester, method_name, None)
        if method is None:
            print(f"[!] Metodo Tester '{method_name}' non trovato nel container")
            return False
        result = await method(session, filter=filter_value)
        return flow.output(result)

    async def verify_contracts(self, config_toml_path: Any) -> bool:
        """Verifica i contract senza costruire o avviare l'applicazione."""
        self.kwargs = (
            config_toml_path
            if isinstance(config_toml_path, dict)
            else {"config": str(config_toml_path)}
        )
        self.framework.strict = True

        try:
            result = await self._discover_components(config_toml_path)
            flow.unwrap(result)
        except Exception as exc:
            print(f"[!] Verifica contract fallita: {exc}")
            return False

        print("[✓] Tutti i contract sono verificati in modalità strict.")
        return True

    async def import_module(self, module_path: str):
        """Importa un modulo Python dinamicamente tramite l'infrastruttura."""
        return await self.infrastructure.import_module(module_path)

    async def install(self, config_or_path: Any = "pyproject.toml") -> bool:
        """Delega al Framework l'installazione delle dipendenze dei contract."""
        try:
            return await self.framework.install(
                config_or_path,
                infrastructure=self.infrastructure,
                cores=self.cores,
                services=self.services,
                ports=self.ports,
            )
        except Exception as exc:
            self.framework.logger.error("Installazione fallita", exception=exc)
            return False