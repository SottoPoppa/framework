import importlib
import json
import os
import tomllib
import uuid
from pathlib import Path
from typing import Any, Optional
from jinja2 import Environment, BaseLoader
from framework.service.diagnostic import get_logger
import sys
import types


class Infrastructure:
    """Gestisce I/O, schemi JSON, templating Jinja e risorse statiche."""

    def __init__(self):
        self.logger = get_logger("infrastructure")
        self.jinja_env = Environment(loader=BaseLoader())
        self.jinja_env.filters["tojson"] = json.dumps
        self.jinja_env.globals["uuid4"] = lambda: str(uuid.uuid4())

    def get_logger(self, component: str):
        """Restituisce un logger coerente con il sistema diagnostico del framework."""
        return get_logger(component)

    def render_jinja(self, target: str, context: Optional[dict] = None) -> str:
        """Renderizza una stringa Jinja con i global registrati in Infrastructure."""
        if not isinstance(target, str):
            return target
        if "{{" not in target and "{%" not in target and "{#" not in target:
            return target

        def env(name: str, default: str = "") -> str:
            return os.environ.get(name, default)

        payload = {
            "env": env,
            **(context or {}),
        }
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
                    self.logger.error(
                        "Schema JSON non valido",
                        exception=exc,
                        file=str(json_file),
                    )


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
        if final:
            self.logger.info("Schemi caricati", schemas=sorted(final))
        else:
            self.logger.warning("Nessuno schema trovato")
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

