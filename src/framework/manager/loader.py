import ast
import asyncio
import importlib
import importlib.util
import inspect
import json
import signal
import subprocess
import sys
import types
import uuid
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any, Optional, Type, get_args, get_type_hints

from jinja2 import BaseLoader, Environment

# Python 3.11+ native TOML support with fallback for older versions
try:
    import tomllib
except ImportError:
    import tomli as tomllib


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
# INFRASTRUCTURE
# ============================================================

class Infrastructure:
    """Gestisce I/O, schemi JSON, templating Jinja e risorse statiche."""

    def __init__(self):
        self.jinja_env = Environment(loader=BaseLoader())
        self.jinja_env.filters["tojson"] = json.dumps
        self.jinja_env.globals["uuid4"] = lambda: str(uuid.uuid4())

    def render_jinja(self, target: str, context: Optional[dict] = None) -> str:
        """Renderizza una stringa Jinja con i global registrati in Infrastructure."""
        if not isinstance(target, str):
            return target
        if "{{" not in target and "{%" not in target and "{#" not in target:
            return target
        payload = context or {}
        return self.jinja_env.from_string(target).render(**payload)

    def load_toml_config(self, config_file: str | Path, context: Optional[dict] = None) -> dict:
        """Legge un file TOML e renderizza eventuali placeholder Jinja prima del parse."""
        content = Path(config_file).read_text(encoding="utf-8")
        rendered = self.render_jinja(content, context=context)
        return tomllib.loads(rendered)

    async def load_schemes(self, directories: list[str]) -> dict:
        """Carica e risolve ricorsivamente i file di schema JSON nelle cartelle."""
        raw: dict[str, Any] = {}
        for directory in map(Path, directories):
            if not directory.exists():
                continue
            for json_file in directory.glob("*.json"):
                try:
                    raw[json_file.stem] = json.loads(
                        json_file.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError as exc:
                    print(f"[!] JSON {json_file.name}: {exc}")


        cache: dict[str, Any] = {}

        def resolve(name: str) -> Any:
            if name in cache:
                return cache[name]
            obj = raw.get(name)
            if obj is None:
                return None

            cache[name] = {}

            def render(val: Any) -> Any:
                if isinstance(val, dict):
                    return {k: render(v) for k, v in val.items()}
                if isinstance(val, list):
                    return [render(v) for v in val]
                if isinstance(val, str) and "{{" in val:
                    stripped = val.strip()
                    if (
                        stripped.startswith("{{")
                        and stripped.endswith("}}")
                        and "|" not in stripped
                    ):
                        ref = stripped[2:-2].strip()
                        if ref in raw:
                            return resolve(ref)
                        g_val = self.jinja_env.globals.get(ref)
                        return g_val() if callable(g_val) else g_val
                    context = {**self.jinja_env.globals, **raw, **cache}
                    return self.jinja_env.from_string(val).render(**context)
                return val

            cache[name] = render(obj)
            return cache[name]

        final = {name: resolve(name) for name in raw}
        print(f"[+] Schemi: {', '.join(sorted(final))}" if final else "[!] Nessuno schema")
        return final

    async def resource(self, path: str | Path) -> str:
        """Legge un file risorsa dal file-system in modo asincrono/trasparente."""
        p = Path(path)
        if str(p).startswith("application/"):
            p = Path("src") / p
        return p.read_bytes().decode("utf-8")

    async def import_module(self, module_path: str):
        """Importa un modulo Python dinamicamente e lo rende disponibile nel DSL.
        
        :param module_path: Percorso del modulo (es. "framework.manager.tester")
        :return: Il modulo importato
        """
        try:
            return importlib.import_module(module_path)
        except ModuleNotFoundError as import_error:
            parts = module_path.split(".")
            candidates = [
                Path("src") / Path(*parts).with_suffix(".py"),
            ]
            for split in range(len(parts) - 1, 0, -1):
                directory = Path("src") / Path(*parts[:split])
                filename = ".".join(parts[split:]) + ".py"
                candidates.append(directory / filename)

            source_path = next((path for path in candidates if path.is_file()), None)
            if source_path is None:
                raise import_error

            package_names = [".".join(parts[:index]) for index in range(1, len(parts))]
            for package_name in package_names:
                if package_name in sys.modules:
                    continue
                package = types.ModuleType(package_name)
                package.__path__ = []
                package.__package__ = package_name.rpartition(".")[0]
                sys.modules[package_name] = package
                if "." in package_name:
                    parent, child = package_name.rsplit(".", 1)
                    setattr(sys.modules[parent], child, package)

            spec = importlib.util.spec_from_file_location(module_path, source_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Impossibile creare ModuleSpec per {source_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_path] = module
            parent, child = module_path.rsplit(".", 1)
            setattr(sys.modules[parent], child, module)
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_path, None)
                raise
            return module


# ============================================================
# FRAMEWORK KERNEL
# ============================================================

class Framework:
    """Kernel per importazione dinamica, estrazione dipendenze e contratti."""

    def __init__(self):
        self.components: dict[str, Resource] = {}
        self.errors: list[str] = []
        self.strict: bool = False

    def _pkg(self, name: str) -> types.ModuleType:
        """Crea o recupera la gerarchia di pacchetti sintetici in sys.modules."""
        if not name:
            return None
        if name in sys.modules:
            return sys.modules[name]

        pkg = types.ModuleType(name)
        pkg.__path__ = []
        pkg.__package__ = name.rpartition(".")[0]
        sys.modules[name] = pkg

        if "." in name:
            parent_name, child_name = name.rsplit(".", 1)
            setattr(self._pkg(parent_name), child_name, pkg)
        return pkg

    def imports(self, code: str) -> list[str]:
        """Analizza l'AST del codice sorgente per rilevare gli import."""
        try:
            tree = ast.parse(code)
        except Exception:
            return []
        result = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                result.add(node.module)
        return list(result)

    async def load_module(
        self, name: str, path: str, extra: dict = None, force: bool = False
    ):
        """Carica o ricarica un modulo Python utilizzando importlib in modo sicuro."""
        if name in sys.modules and not force:
            return sys.modules[name]

        file_path = Path(path)
        spec = importlib.util.spec_from_file_location(name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Impossibile creare ModuleSpec per {path}")

        module = importlib.util.module_from_spec(spec)
        if extra:
            module.__dict__.update(extra)

        sys.modules[name] = module

        if "." in name:
            parent_name, short_name = name.rsplit(".", 1)
            setattr(self._pkg(parent_name), short_name, module)

        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise

        print(f"[+] {name}")
        return module

    async def add(self, resource: Resource, extra: dict = None):
        """Registra un nuovo modulo risorsa nel registry."""
        module = await self.load_module(resource.name, resource.path, extra)
        resource.module = module
        self.components[resource.name] = resource

        contract_mod = sys.modules.get("framework.service.contract")
        contract = getattr(contract_mod, "Contract", None) if contract_mod else globals().get("Contract")
        if contract is not None:
            contract.verify_module(resource.path, module, self.strict)

        print(f"[~] {resource.name}")
        return resource

    async def load(self, resource: Resource, extra_by_name: dict = None):
        extra_by_name = extra_by_name or {}
        short_name = resource.name.rsplit(".", 1)[-1]
        return await self.add(resource, extra_by_name.get(short_name))

    async def reload(self, resource: Resource):
        """Ricarica forzatamente una risorsa."""
        module = await self.load_module(
            resource.name, resource.path, resource.extend, force=True
        )
        resource.module = module
        print(f"[✓] Reload {resource.name}")
        return resource

    async def load_core(self, services: dict, ports: dict, extra_by_name: dict = None):
        """Carica i servizi di core ordinandoli topologicamente."""
        extra_by_name = extra_by_name or {}
        modules = {**services, **ports}
        graph = {}
        pending = {}

        for name, path in modules.items():
            ns_type = "service" if name in services else "port"
            namespace = f"framework.{ns_type}.{name}"
            pending[name] = Resource(name=namespace, path=path)

            try:
                source = Path(path).read_text(encoding="utf-8")
                imp_list = self.imports(source)
            except Exception:
                imp_list = []

            graph[name] = {item.rsplit(".", 1)[-1] for item in imp_list} & modules.keys()

        order = TopologicalSorter(graph).static_order()

        for name in order:
            res = pending[name]
            short_name = res.name.rsplit(".", 1)[-1]
            await self.add(res, extra_by_name.get(short_name))
            print(f"[✓] Creato {res.name}")

    def dependencies_from_class(self, target: Any) -> dict:
        """Ispeziona il costruttore della classe per estrarne le annotazioni dei tipi."""
        init_fn = getattr(target, "__init__", None)
        if not init_fn or init_fn is object.__init__:
            return {target: []}

        try:
            hints = get_type_hints(init_fn)
        except Exception:
            hints = getattr(init_fn, "__annotations__", {})

        sig = inspect.signature(init_fn)
        dependencies = []

        for name, param in sig.parameters.items():
            if name == "self" or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            annotation = hints.get(name)
            if annotation is None:
                continue
            args = get_args(annotation)
            dependencies.extend(args if args else [annotation])

        return {target: dependencies}

    def resolve_order(self, nodes: list, dependencies: dict) -> list:
        """Calcola l'ordine topologico di istanziazione per i nodi forniti."""
        node_set = set(nodes)
        graph = {
            node: {dep for dep in dependencies.get(node, []) if dep in node_set}
            for node in nodes
        }
        return list(TopologicalSorter(graph).static_order())

    def component(self, name: str) -> Optional[Resource]:
        return self.components.get(name)

    def components_iter(self):
        return self.components.values()

    def components_ports(self) -> list[Resource]:
        return [
            r for r in self.components.values() if r.name.startswith("framework.adapter.")
        ]

    def resource_by_path(self, path: str) -> Optional[Resource]:
        target = Path(path).resolve()
        for res in self.components.values():
            if Path(res.path).resolve() == target:
                return res
        return None

    def check(self):
        if self.errors:
            raise RuntimeError("\n".join(self.errors))


# ============================================================
# APPLICATION
# ============================================================

class Application:
    """Gestisce il ciclo di vita dell'applicazione, segnali OS e worker asincroni."""

    def __init__(self, loader: Any, managers: list, session: Any = None):
        self._loader = loader
        self._managers = managers
        self._stop_event = asyncio.Event()
        self._running_tasks: list[asyncio.Task] = []
        self._session = session

    async def _message_consumer_worker(self):
        """Worker in background per la gestione degli eventi di reload."""
        import framework.service.flow as flow

        try:
            while not self._stop_event.is_set():
                messenger = self._loader.get_managers().get("messenger")
                if messenger is None:
                    await asyncio.sleep(0.2)
                    continue

                message_result = await messenger.receive(self._session, domain="event")
                if not flow.is_result(message_result):
                    continue
                if not message_result.get("success"):
                    continue
                message = flow.output(message_result)
                for name, mgr in list(self._loader.get_managers().items()):
                    if hasattr(mgr, "reload"):
                        try:
                            await mgr.reload(self._session, message)
                        except Exception as exc:
                            print(f"[!] Errore durante reload in {name}: {exc}")
        except asyncio.CancelledError:
            print("[*] Worker di messaggistica terminato.")

    async def startup(self):
        """Avvia l'applicazione e gestisce i segnali di arresto."""
        import framework.service.flow as flow

        print("[*] Avvio dei manager del framework...")
        if self._loader.kwargs.get("dev"):
            self._running_tasks.append(
                asyncio.create_task(self._message_consumer_worker())
            )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop_event.set)
            except NotImplementedError:
                pass

        for manager in self._managers:
            if not hasattr(manager, "startup"):
                continue
            result = await manager.startup(self._session)
            if flow.is_result(result):
                if not result.get("success"):
                    continue
                result = flow.output(result)
            if not result:
                continue

            coros = result if isinstance(result, list) else [result]
            for c in coros:
                if asyncio.iscoroutine(c) or inspect.isawaitable(c):
                    self._running_tasks.append(asyncio.create_task(c))

        print("[+] Framework completamente attivo. In ascolto...")
        await self._stop_event.wait()

    async def shutdown(self):
        """Esegue il graceful shutdown di tutti i componenti registrati."""
        import framework.service.flow as flow

        print("\n[*] Spegnimento controllato dei servizi...")
        for manager in reversed(self._managers):
            if hasattr(manager, "shutdown"):
                result = await manager.shutdown(self._session)
                if flow.is_result(result) and not result.get("success"):
                    print(f"[!] Shutdown fallito per {manager}: {result.get('errors')}")

        for task in self._running_tasks:
            if not task.done():
                task.cancel()

        print("[*] Framework spento correttamente.")


# ============================================================
# LOADER (COMPOSITION ROOT)
# ============================================================

class Loader:
    """Composition Root responsabile dell'infezione delle dipendenze e del wiring."""

    services = {
        "flow": "src/framework/service/flow.py",
        "factory": "src/framework/service/factory.py",
        "language": "src/framework/service/language.py",
        "scheme": "src/framework/service/scheme.py",
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
    }

    def __init__(self):
        self.framework = Framework()
        self.infra = Infrastructure()
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

    async def _discover_adapters(self, config: dict):
        """Scopre e carica tutti gli adapter configurati."""
        for port_key in self.ports:
            if port_key == "manager":
                continue
            enabled = config.get(port_key, {})
            if not isinstance(enabled, dict):
                continue

            for adapter_name, adapter_cfg in enabled.items():
                configs = adapter_cfg if isinstance(adapter_cfg, list) else [adapter_cfg]
                resource = Resource(
                    name=f"framework.adapter.{port_key}.{adapter_name}",
                    path=f"src/infrastructure/{port_key}/{adapter_name}.py",
                    kind="ADAPTER",
                    config=configs,
                )
                await self.framework.load(resource)

    def _build(self, cls: Type, config: dict = None) -> Handle:
        config = config or {}
        args = self._resolve_dependencies(cls)
        return Handle(cls(*args, **config))

    def _build_managers(self, resources: list[Resource]) -> list[Handle]:
        """Costruisce e registra i manager rispettando l'ordine di dipendenza."""
        discovered = [
            (getattr(res.module, "Manager", None), res)
            for res in resources
            if hasattr(res.module, "Manager")
        ]
        if not discovered:
            return []

        classes = [cls for cls, _ in discovered]
        dependencies = {}
        for cls in classes:
            dependencies.update(self.framework.dependencies_from_class(cls))

        order = self.framework.resolve_order(classes, dependencies)
        res_map = {cls: res for cls, res in discovered}
        instances = []

        for cls in order:
            if cls is Loader:
                continue
            res = res_map[cls]
            obj = self._build(cls, res.config or {})
            self.container.put(cls, obj, singleton=True)
            instances.append(obj)
            print(f"[✓] Manager {cls.__module__}.{cls.__name__}")

        return instances

    def _build_adapters(
        self, resources: list[Resource], save: bool = True
    ) -> list[Handle]:
        """Costruisce gli adapter istanziati e li assegna alle rispettive porte."""
        created = []
        for res in resources:
            parts = res.name.split(".")
            if len(parts) < 4:
                continue
            interface = self._port_interface(parts[2])
            adapter_cls = getattr(res.module, "Adapter", None)
            if not interface or not adapter_cls:
                continue

            configs = res.config if isinstance(res.config, list) else [res.config]
            for cfg in configs:
                cfg = cfg or {}
                obj = self._build(adapter_cls, cfg)
                created.append(obj)
                if save:
                    self.container.add_port(interface, obj)
                print(f"[✓] Adapter {adapter_cls.__name__} name={cfg.get('name')}")

        return created

    async def reload(self, session: Any, changed_path: str) -> bool:
        """Esegue il reload in-memory di adapter o manager modificati."""
        if not changed_path.endswith(".py"):
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
                new_handles = self._build_adapters([resource], save=False)
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
        return await self.infra.load_schemes(directories)

    async def resource(self, path: Any) -> str:
        return await self.infra.resource(path)

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

    async def _discover_components(self, config_toml_path: Any) -> tuple[dict, list[Resource]]:
        """Carica core, manager e adapter senza istanziarli."""
        kwargs = (
            config_toml_path
            if isinstance(config_toml_path, dict)
            else {"config": str(config_toml_path)}
        )
        config_file = kwargs.get("config", "pyproject.toml")
        schemes = await self.load_schemes(
            ["src/framework/scheme", "src/application/model"]
        )
        await self.framework.load_core(
            self.services,
            self.ports,
            extra_by_name={
                "scheme": {
                    "schemes": schemes,
                    "jinja_env": self.infra.jinja_env,
                }
            },
        )
        config = self.infra.load_toml_config(config_file)
        self.current_config = config

        mgr_resources = []
        for name, path in self.managers.items():
            resource = Resource(
                name=f"framework.manager.{name}",
                path=path,
                kind="MANAGER",
                config=config.get("manager", {}).get(name, {}),
            )
            await self.framework.load(resource)
            mgr_resources.append(resource)

        await self._discover_adapters(config)
        return config, mgr_resources

    async def bootstrap(self, config_toml_path: Any) -> Application:
        """Inizializza il framework caricando configurazione e risorse."""
        kwargs = (
            config_toml_path
            if isinstance(config_toml_path, dict)
            else {"config": str(config_toml_path)}
        )
        config_file = kwargs.get("config", "pyproject.toml")
        self.kwargs = kwargs
        self.framework.strict = not (
            kwargs.get("dev")
            or kwargs.get("test") is not None
            or kwargs.get("skip_verify")
        )

        config, mgr_resources = await self._discover_components(config_toml_path)

        # Risoluzione dinamica di Container dopo il caricamento del core.
        import framework.service.flow as flow

        container_mod = sys.modules.get("framework.service.container")
        if not container_mod or not hasattr(container_mod, "Container"):
            raise RuntimeError(
                "Impossibile trovare la classe Container in 'framework.service.container'"
            )

        container_cls = getattr(container_mod, "Container")
        self.container = container_cls()

        # 3. Registrazione del container nel container stesso (per DI)
        self.container.put(container_cls, self.container, singleton=True)

        print("\n[*] Discovery...")

        print("\n[*] Build...")
        managers = self._build_managers(mgr_resources)
        self._build_adapters(self.framework.components_ports())

        def_res = self.framework.component("framework.manager.defender")
        def_cls = getattr(def_res.module, "Manager", None) if def_res else None
        defender = self.container.get(def_cls) if def_cls else None
        session = None

        if defender:
            if hasattr(defender, "startup"):
                startup_result = await defender.startup()
                if flow.is_result(startup_result) and not startup_result.get("success"):
                    raise RuntimeError(startup_result.get("errors"))
            if hasattr(defender, "session_create"):
                session = flow.output(await defender.session_create())
                print(f"[*] Sessione creata: {session}")

        app = Application(self, managers, session)
        self.app = app
        return app

    async def run_tests(self, filter_value: str | None = None) -> bool:
        """Esegue la suite di test DSL tramite il Manager del Tester.
        
        :param filter_value: Filtro opzionale per limitare i test eseguiti
        """
        managers = self.get_managers()
        tester = managers.get("tester")
        if tester is None:
            print("[!] Manager 'tester' non trovato nel container")
            return False
        
        # Passa il filtro come constant al metodo run()
        import framework.service.flow as flow

        result = await tester.run(filter=filter_value)
        return flow.output(result) if flow.is_result(result) else result

    async def verify_contracts(self, config_toml_path: Any) -> bool:
        """Verifica i contract senza costruire o avviare l'applicazione."""
        self.kwargs = (
            config_toml_path
            if isinstance(config_toml_path, dict)
            else {"config": str(config_toml_path)}
        )
        self.framework.strict = True

        try:
            await self._discover_components(config_toml_path)
        except Exception as exc:
            print(f"[!] Verifica contract fallita: {exc}")
            return False

        print("[✓] Tutti i contract sono verificati in modalità strict.")
        return True

    async def import_module(self, module_path: str):
        """Importa un modulo Python dinamicamente tramite l'infrastruttura."""
        return await self.infra.import_module(module_path)

    async def install(self, config_or_path: Any = "pyproject.toml") -> bool:
        """
        Analizza i contract del framework e degli adapter/port attivi
        e installa tutte le dipendenze dichiarate tramite 'requires'.

        NON esegue il bootstrap completo del framework.
        NON istanzia container, manager o adapter.

        Utilizza il normale Framework.load_module() per caricare
        autonomamente Contract.
        """

        # ============================================================
        # 1. CONFIGURAZIONE
        # ============================================================

        config_file = (
            config_or_path.get("config", "pyproject.toml")
            if isinstance(config_or_path, dict)
            else str(config_or_path)
        )

        print(
            f"\n[*] Caricamento configurazione da "
            f"'{config_file}'..."
        )

        try:
            config = self.infra.load_toml_config(config_file)
        except Exception as exc:
            print(
                f"[!] Errore nel caricare "
                f"'{config_file}': {exc}"
            )
            return False

        # ============================================================
        # 2. ADAPTER ATTIVI
        # ============================================================

        enabled_adapters = []

        for port_name, port_config in config.items():

            if port_name in ("project", "manager"):
                continue

            if not isinstance(port_config, dict):
                continue

            for adapter_name in port_config:
                enabled_adapters.append(
                    (port_name, adapter_name)
                )

        if enabled_adapters:

            print(
                f"[*] Adapter abilitati attivi "
                f"({len(enabled_adapters)}):"
            )

            for port_name, adapter_name in enabled_adapters:
                print(
                    f"  - [{port_name}] "
                    f"{adapter_name}"
                )

        else:
            print(
                "[*] Nessun adapter abilitato trovato."
            )

        # ============================================================
        # 3. CARICA CONTRACT
        # ============================================================

        contract_name = "framework.service.contract"

        contract_mod = sys.modules.get(contract_name)

        if contract_mod is None:

            contract_path = self.services.get("contract")

            if not contract_path:
                print(
                    "[!] Contract non disponibile."
                )
                return False

            print(
                "\n[*] Caricamento autonomo di "
                "'framework.service.contract'..."
            )

            try:
                contract_mod = await self.framework.load_module(
                    contract_name,
                    contract_path,
                )
            except Exception as exc:
                print(
                    f"[!] Impossibile caricare Contract: "
                    f"{exc}"
                )
                return False

        contract_cls = getattr(
            contract_mod,
            "Contract",
            None,
        )

        if contract_cls is None:
            print(
                "[!] Il modulo "
                "'framework.service.contract' "
                "non contiene la classe Contract."
            )
            return False

        print("[✓] Contract caricato.")

        # ============================================================
        # 4. COSTRUISCI LE SORGENTI DA ANALIZZARE
        # ============================================================

        sources = []

        # ------------------------------------------------------------
        # SERVICES
        # ------------------------------------------------------------

        for service_name, service_path in self.services.items():

            if service_name == "contract":
                continue

            sources.append(
                (
                    "service",
                    service_name,
                    service_path,
                )
            )

        # ------------------------------------------------------------
        # PORTS
        # ------------------------------------------------------------

        for port_name, port_path in self.ports.items():

            sources.append(
                (
                    "port",
                    port_name,
                    port_path,
                )
            )

        # ------------------------------------------------------------
        # ADAPTER ATTIVI
        # ------------------------------------------------------------

        for port_name, adapter_name in enabled_adapters:

            adapter_path = (
                f"src/infrastructure/"
                f"{port_name}/"
                f"{adapter_name}.py"
            )

            sources.append(
                (
                    "adapter",
                    f"{port_name}.{adapter_name}",
                    adapter_path,
                )
            )

        # ============================================================
        # 5. ANALISI CONTRACT
        # ============================================================

        all_requires = set()
        contracts_found = 0

        print("\n[*] Analisi dei contract...")

        for component_type, component_name, source_path in sources:

            source = Path(source_path)

            if not source.exists():

                print(
                    f"  [!] [{component_type}] "
                    f"{component_name}: "
                    f"sorgente non trovato: "
                    f"{source_path}"
                )
                continue

            # --------------------------------------------------------
            # Trova contract
            # --------------------------------------------------------

            try:
                contract_path = contract_cls.for_source(
                    source_path
                )
            except Exception as exc:
                print(
                    f"  [!] [{component_type}] "
                    f"{component_name}: "
                    f"errore nel trovare contract: "
                    f"{exc}"
                )
                continue

            # --------------------------------------------------------
            # Nessun contract
            # --------------------------------------------------------

            if not contract_path or not Path(contract_path).exists():

                print(
                    f"  - [{component_type}] "
                    f"{component_name}: "
                    f"nessun contract"
                )
                continue

            # --------------------------------------------------------
            # Leggi contract
            # --------------------------------------------------------

            try:
                data = contract_cls.read(
                    contract_path
                )
            except Exception as exc:
                print(
                    f"  [!] [{component_type}] "
                    f"{component_name}: "
                    f"errore lettura contract: "
                    f"{exc}"
                )
                continue

            if not data:

                print(
                    f"  - [{component_type}] "
                    f"{component_name}: "
                    f"contract vuoto"
                )
                continue

            contracts_found += 1

            # --------------------------------------------------------
            # Requires
            # --------------------------------------------------------

            requires = data.get(
                "requires",
                [],
            )

            if isinstance(requires, str):
                requires = [requires]

            if not isinstance(requires, list):

                print(
                    f"  [!] [{component_type}] "
                    f"{component_name}: "
                    f"'requires' deve essere una "
                    f"stringa o una lista."
                )
                continue

            if not requires:

                print(
                    f"  - [{component_type}] "
                    f"{component_name}: "
                    f"nessun contract"
                    if component_type == "service"
                    else
                    f"  - [{component_type}] "
                    f"{component_name}: "
                    f"nessuna dipendenza"
                )
                continue

            print(
                f"  - [{component_type}] "
                f"{component_name}: "
                f"{len(requires)} requires"
            )

            for requirement in requires:

                if not isinstance(
                    requirement,
                    str,
                ):
                    print(
                        f"    [!] Dipendenza non valida: "
                        f"{requirement!r}"
                    )
                    continue

                requirement = requirement.strip()

                if requirement:
                    all_requires.add(requirement)

        # ============================================================
        # 6. NESSUNA DIPENDENZA
        # ============================================================

        if not all_requires:

            print(
                "\n[*] Nessuna dipendenza "
                "'requires' trovata."
            )

            if contracts_found == 0:
                print(
                    "[!] Nessun contract trovato."
                )

            print(
                "\n[✓] Procedura --install completata.\n"
            )

            return True

        # ============================================================
        # 7. LISTA FINALE
        # ============================================================

        requirements = sorted(all_requires)

        print(
            f"\n[*] Dipendenze 'requires' rilevate "
            f"({len(requirements)}):"
        )

        for requirement in requirements:
            print(f"  - {requirement}")

        # ============================================================
        # 8. INSTALLAZIONE
        # ============================================================

        print(
            "\n[*] Installazione pacchetti "
            "in corso via pip..."
        )

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    *requirements,
                ],
                capture_output=True,
                text=True,
            )
        except Exception as exc:

            print(
                f"[!] Impossibile eseguire pip: "
                f"{exc}"
            )
            return False

        # ============================================================
        # 9. OUTPUT PIP
        # ============================================================

        if result.stdout.strip():
            print(result.stdout)

        if result.returncode != 0:

            print(
                "[!] Errore durante "
                "l'installazione delle dipendenze:"
            )

            if result.stderr.strip():
                print(result.stderr)

            return False

        print(
            "[✓] Dipendenze installate "
            "con successo!"
        )

        print(
            "\n[✓] Procedura --install completata.\n"
        )

        return True

    async def install2(self, config_or_path: Any = "pyproject.toml"):
        """Installa le dipendenze dichiarate dai contratti degli adapter attivi."""
        config_file = (
            config_or_path.get("config", "pyproject.toml")
            if isinstance(config_or_path, dict)
            else str(config_or_path)
        )
        print(f"\n[*] Caricamento configurazione da '{config_file}'...")

        try:
            config = self.infra.load_toml_config(config_file)
        except Exception as exc:
            print(f"[!] Errore nel caricare '{config_file}': {exc}")
            return

        enabled_adapters = [
            (p_key, a_name)
            for p_key, p_val in config.items()
            if p_key not in ("project", "manager") and isinstance(p_val, dict)
            for a_name in p_val.keys()
        ]

        if not enabled_adapters:
            print("[*] Nessun adapter abilitato trovato.")
            return

        print(f"[*] Adapter abilitati attivi ({len(enabled_adapters)}):")
        for p_key, a_name in enabled_adapters:
            print(f"  - [{p_key}] {a_name}")

        contract_mod = sys.modules.get("framework.service.contract")
        contract_cls = getattr(contract_mod, "Contract", None) if contract_mod else globals().get("Contract")
        if not contract_cls:
            print("[!] Contract non disponibile.")
            return

        all_requires = set()
        for p_key, a_name in enabled_adapters:
            src_path = f"src/infrastructure/{p_key}/{a_name}.py"
            data = contract_cls.read(contract_cls.for_source(src_path))
            if data:
                all_requires.update(data.get("requires", []))

        if not all_requires:
            print("\n[*] Nessuna dipendenza 'requires' specificata.")
            return

        reqs = sorted(all_requires)
        print(f"\n[*] Dipendenze 'requires' rilevate ({len(reqs)}):")
        for r in reqs:
            print(f"  - {r}")

        print("[*] Installazione pacchetti in corso via pip...")
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", *reqs],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                print("[✓] Dipendenze installate con successo!")
            else:
                print(f"[!] Errore durante pip install:\n{res.stderr}")
        except Exception as exc:
            print(f"[!] Impossibile eseguire l'installazione: {exc}")

        print("\n[✓] Procedura --install completata.\n")