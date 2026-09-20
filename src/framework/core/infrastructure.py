import importlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Optional
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound, nodes
from framework.service.diagnostic import get_logger
import sys
import types


class Infrastructure:
    """Gestisce I/O, schemi JSON, templating Jinja e risorse statiche."""

    def __init__(self):
        self.logger = get_logger("infrastructure")
        self._jinja_environments = {}

    def get_jinja(self, **options) -> Environment:
        """Restituisce un ambiente Jinja riusando la configurazione già vista."""
        key = tuple(sorted((name, id(value)) for name, value in options.items()))
        environment = self._jinja_environments.get(key)
        if environment is not None:
            return environment

        environment = Environment(**options)
        self._jinja_environments[key] = environment
        return environment

    def get_logger(self, component: str):
        """Restituisce un logger coerente con il sistema diagnostico del framework."""
        return get_logger(component)

    def get_resource(self, path: str) -> str:
        """Legge il contenuto di una risorsa statica come stringa."""
        return Path(path).read_text(encoding="utf-8")

    def _select_jinja_environment(self, target: str) -> Environment:
        """Sceglie l'ambiente in cache adatto ai riferimenti del template."""
        default = self.get_jinja()
        try:
            references = [
                node.template.value
                for node in default.parse(target).find_all(
                    (nodes.Include, nodes.Extends, nodes.Import, nodes.FromImport)
                )
                if isinstance(node.template, nodes.Const)
                and isinstance(node.template.value, str)
            ]
        except Exception:
            return default

        if not references:
            return default

        for environment in self._jinja_environments.values():
            loader = getattr(environment, "loader", None)
            if loader is None:
                continue
            try:
                for reference in references:
                    loader.get_source(environment, reference)
            except TemplateNotFound:
                continue
            return environment
        return default

    def render_jinja(
        self,
        target: str,
        context: Optional[dict] = None,
        environment: Optional[Environment] = None,
    ) -> str:
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

        environment = environment or self._select_jinja_environment(target)

        return environment.from_string(target).render(**payload)

    def convert_str_to_toml(self, content) -> dict:
        """Legge un file TOML e renderizza eventuali placeholder Jinja prima del parse."""
        return tomllib.loads(content)

    def _load_scheme_files(self, directories: list[str]) -> dict[str, Any]:
        """Legge gli schemi JSON presenti nelle directory indicate."""
        schemes: dict[str, Any] = {}
        for directory in map(Path, directories):
            if not directory.exists():
                continue
            for json_file in directory.glob("*.json"):
                try:
                    schemes[json_file.stem] = json.loads(
                        json_file.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError as exc:
                    self.logger.error(
                        "Schema JSON non valido",
                        exception=exc,
                        file=str(json_file),
                    )
        return schemes

    def _render_scheme_value(
        self,
        value: Any,
        schemes: dict[str, Any],
        resolved: dict[str, Any],
    ) -> Any:
        """Risolve riferimenti e placeholder Jinja dentro un valore di schema."""
        if isinstance(value, dict):
            return {
                key: self._render_scheme_value(item, schemes, resolved)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._render_scheme_value(item, schemes, resolved)
                for item in value
            ]
        if not isinstance(value, str) or "{{" not in value:
            return value

        stripped = value.strip()
        if stripped.startswith("{{") and stripped.endswith("}}") and "|" not in stripped:
            reference = stripped[2:-2].strip()
            if reference in schemes:
                return self._resolve_scheme(reference, schemes, resolved)
            global_value = self.get_jinja().globals.get(reference)
            return global_value() if callable(global_value) else global_value

        context = {**self.get_jinja().globals, **schemes, **resolved}
        return self.get_jinja().from_string(value).render(**context)

    def _resolve_scheme(
        self,
        name: str,
        schemes: dict[str, Any],
        resolved: dict[str, Any],
    ) -> Any:
        """Risolve uno schema e i riferimenti agli altri schemi."""
        if name in resolved:
            return resolved[name]
        if name not in schemes:
            return None

        resolved[name] = {}
        resolved[name] = self._render_scheme_value(
            schemes[name], schemes, resolved
        )
        return resolved[name]

    async def load_schemes(self, directories: list[str]) -> dict:
        """Carica e risolve ricorsivamente i file di schema JSON nelle cartelle."""
        schemes = self._load_scheme_files(directories)
        resolved: dict[str, Any] = {}
        final = {
            name: self._resolve_scheme(name, schemes, resolved)
            for name in schemes
        }
        if final:
            self.logger.info("Schemi caricati", schemas=sorted(final))
        else:
            self.logger.warning("Nessuno schema trovato")
        return final

    def resource(self, path: str | Path) -> str:
        """Legge un file risorsa dal file-system in modo asincrono/trasparente."""
        path_str = str(path)
        
        match path_str:
            case p if p.endswith(".toml"):
                content = self.get_resource(path_str)
                rendered = self.render_jinja(content)
                return self.convert_str_to_toml(rendered)
            case p if p.endswith(".json"):
                content = self.get_resource(path_str)
                rendered = self.render_jinja(content)
                return self.convert_str_to_json(rendered)
            case p if p.endswith(".dsl"):
                content = self.get_resource(path_str)
                environment = self.get_jinja(
                    loader=FileSystemLoader(
                        str(Path(__file__).resolve().parents[3] / "src" / "application" / "policy")
                    ),
                    autoescape=False,
                    keep_trailing_newline=True,
                    undefined=StrictUndefined,
                )
                return self.render_jinja(content)
            case _:
                # Caso di default se l'estensione non coincide
                raise ValueError(f"Formato file non supportato: {path_str}")