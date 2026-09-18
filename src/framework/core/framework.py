import ast
import importlib
import importlib.util
import inspect
import subprocess
import sys
import types
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any, Optional, Type, TypedDict, get_args, get_type_hints

@dataclass
class Resource:
    """Rappresenta una risorsa/modulo gestita dal kernel del framework."""
    name: str
    path: str
    module: Any = None
    kind: Optional[str] = None
    config: dict = field(default_factory=dict)
    extend: dict = field(default_factory=dict)


class InstallContext(TypedDict, total=False):
    config_file: str
    config: dict
    enabled_adapters: list[tuple[str, str]]
    contract_cls: Type
    sources: list[tuple[str, str, str]]
    all_requires: set[str]
    contracts_found: int
    requirements: list[str]

class Framework:
    """Kernel per importazione dinamica, estrazione dipendenze e contratti."""

    def __init__(self):
        self.logger_resource = Resource(
            name="framework.service.diagnostic",
            path="src/framework/service/diagnostic.py",
            module=importlib.import_module("framework.service.diagnostic"),
        )
        self.logger = self.logger_resource.module.get_logger("framework")
        self.components: dict[str, Resource] = {}
        self.strict: bool = False

    async def bootstrap(self):
        """Bootstrap the framework components."""
        cores = [
            Resource(name="framework.core.flow", path="src/framework/core/flow.py"),
            Resource(name="framework.core.application", path="src/framework/core/application.py"),
            Resource(name="framework.core.infrastructure", path="src/framework/core/infrastructure.py"),
            Resource(name="framework.manager.loader", path="src/framework/manager/loader.py"),
        ]

        self.logger.info("Bootstrap del framework avviato", components=len(cores))
        for core in cores:
            await self.add(core)
        self.logger.info("Bootstrap del framework completato", components=len(cores))

        instance_infrastructure = self.components.get("framework.core.infrastructure").module.Infrastructure()
        #instance_application = self.components.get("framework.core.application").module.Application()



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
        except Exception as exc:
            self.logger.debug("Impossibile analizzare gli import dal sorgente", exception=exc)
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
            module = sys.modules[name]
            if extra:
                module.__dict__.update(extra)
            self.logger.debug("Modulo già caricato riutilizzato", module=name, path=path)
            return module

        file_path = Path(path)
        self.logger.info("Caricamento modulo", module=name, path=str(file_path), force=force)
        spec = importlib.util.spec_from_file_location(name, file_path)
        if spec is None or spec.loader is None:
            self.logger.error("Impossibile creare ModuleSpec", path=path)
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
        except Exception as exc:
            sys.modules.pop(name, None)
            self.logger.error("Errore durante il caricamento del modulo", exception=exc, module=name, path=path)
            raise

        self.logger.info("Modulo caricato", module=name, path=path)
        return module

    async def add(self, resource: Resource, extra: dict = None):
        """Registra un nuovo modulo risorsa nel registry."""
        module = await self.load_module(resource.name, resource.path, extra)
        resource.module = module
        self.components[resource.name] = resource

        self.logger.info("Risorsa registrata", resource=resource.name, path=resource.path)

        contract_mod = sys.modules.get("framework.service.contract")
        contract = getattr(contract_mod, "Contract", None) if contract_mod else globals().get("Contract")
        if contract is not None:
            contract.verify_module(resource.path, module, self.strict)

        return resource

    async def reload(self, resource: Resource):
        """Ricarica forzatamente una risorsa."""
        module = await self.load_module(
            resource.name, resource.path, resource.extend, force=True
        )
        resource.module = module
        self.logger.info("Risorsa ricaricata", resource=resource.name, path=resource.path)
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
        self.logger.info("Ordine di caricamento del core calcolato", components=len(order))

        for name in order:
            res = pending[name]
            short_name = res.name.rsplit(".", 1)[-1]
            await self.add(res, extra_by_name.get(short_name))

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

# -----------------------------------------
# Installazione e gestione delle risorse
# -----------------------------------------

    def _install_context(self, config_or_path: Any) -> InstallContext:
        config_file = (
            config_or_path.get("config", "pyproject.toml")
            if isinstance(config_or_path, dict)
            else str(config_or_path)
        )
        self.logger.info("Caricamento configurazione per installazione", path=config_file)
        return {"config_file": config_file}

    def _read_install_config(
        self, context: InstallContext, infrastructure: Any
    ) -> InstallContext:
        try:
            config = infrastructure.load_toml_config(context["config_file"])
        except Exception as exc:
            raise RuntimeError(
                f"Errore nel caricare '{context['config_file']}': {exc}"
            ) from exc
        return {**context, "config": config}

    def _find_enabled_adapters(self, context: InstallContext) -> InstallContext:
        enabled = [
            (port_name, adapter_name)
            for port_name, port_config in context["config"].items()
            if port_name not in {"project", "manager", "tool"}
            and isinstance(port_config, dict)
            for adapter_name in port_config
        ]
        return {**context, "enabled_adapters": enabled}

    async def _load_install_contract(
        self, context: InstallContext, services: dict
    ) -> InstallContext:
        contract_name = "framework.service.contract"
        contract_mod = sys.modules.get(contract_name)
        if contract_mod is None:
            contract_path = services.get("contract")
            if not contract_path:
                raise RuntimeError("Contract non disponibile.")
            contract_mod = await self.load_module(contract_name, contract_path)
        contract_cls = getattr(contract_mod, "Contract", None)
        if contract_cls is None:
            raise RuntimeError(
                "Il modulo 'framework.service.contract' non contiene la classe Contract."
            )
        return {**context, "contract_cls": contract_cls}

    def _install_sources(
        self,
        context: InstallContext,
        cores: dict,
        services: dict,
        ports: dict,
    ) -> InstallContext:
        sources = [("core", name, path) for name, path in cores.items()]
        sources.extend(
            ("service", name, path)
            for name, path in services.items()
            if name != "contract"
        )
        sources.extend(("port", name, path) for name, path in ports.items())
        sources.extend(
            (
                "adapter",
                f"{port_name}.{adapter_name}",
                f"src/infrastructure/{port_name}/{adapter_name}.py",
            )
            for port_name, adapter_name in context["enabled_adapters"]
        )
        return {**context, "sources": sources}

    def _analyze_install_contracts(self, context: InstallContext) -> InstallContext:
        contract_cls = context["contract_cls"]
        all_requires: set[str] = set()
        contracts_found = 0
        for component_type, component_name, source_path in context["sources"]:
            source = Path(source_path)
            if not source.exists():
                self.logger.warning(
                    "Sorgente del componente non trovato",
                    component_type=component_type,
                    component=component_name,
                    path=source_path,
                )
                continue
            try:
                contract_path = contract_cls.for_source(source_path)
                data = (
                    contract_cls.read(contract_path)
                    if contract_path and Path(contract_path).exists()
                    else None
                )
            except Exception as exc:
                self.logger.error(
                    "Errore nella lettura del contract",
                    exception=exc,
                    component=component_name,
                )
                continue
            if not data:
                continue
            contracts_found += 1
            requires = data.get("requires", [])
            if isinstance(requires, str):
                requires = [requires]
            if not isinstance(requires, list):
                self.logger.warning(
                    "Campo requires non valido nel contract", component=component_name
                )
                continue
            for requirement in requires:
                if isinstance(requirement, str) and requirement.strip():
                    all_requires.add(requirement.strip())
        return {
            **context,
            "all_requires": all_requires,
            "contracts_found": contracts_found,
        }

    def _prepare_installation(self, context: InstallContext) -> InstallContext:
        return {**context, "requirements": sorted(context["all_requires"])}

    def _run_installation(self, context: InstallContext) -> bool:
        requirements = context["requirements"]
        if not requirements:
            self.logger.info(
                "Installazione completata senza dipendenze",
                contracts=context["contracts_found"],
            )
            return True
        self.logger.info(
            "Installazione dipendenze avviata", requirements=len(requirements)
        )
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", *requirements],
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            raise RuntimeError(f"Impossibile eseguire pip: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError("Errore durante l'installazione delle dipendenze.")
        self.logger.info("Dipendenze installate con successo")
        return True

    async def install(
        self,
        config_or_path: Any = "pyproject.toml",
        *,
        infrastructure: Any,
        cores: dict,
        services: dict,
        ports: dict,
    ) -> bool:
        """Analizza i contract e installa le dipendenze dichiarate in requires."""
        context = self._install_context(config_or_path)
        context = self._read_install_config(context, infrastructure)
        context = self._find_enabled_adapters(context)
        context = await self._load_install_contract(context, services)
        context = self._install_sources(context, cores, services, ports)
        context = self._analyze_install_contracts(context)
        context = self._prepare_installation(context)
        return self._run_installation(context)

