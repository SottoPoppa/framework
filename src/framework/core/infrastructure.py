import json
from pathlib import Path
from typing import Any, Optional
from framework.service.diagnostic import get_logger
import framework.service.scheme as scheme
import framework.service.template as template


class Infrastructure:
    """Gestisce I/O, schemi JSON, templating Jinja e risorse statiche."""

    def __init__(self):
        self.logger = get_logger("infrastructure")
        self.jinja_environments = {}

    def get_jinja(self, **options):
        """Restituisce un ambiente Jinja dalla cache locale."""
        return template.get_jinja(self, **options)

    def get_logger(self, component: str):
        """Restituisce un logger coerente con il sistema diagnostico del framework."""
        return get_logger(component)

    def get_resource(self, path: str) -> str:
        """Legge il contenuto di una risorsa statica come stringa."""
        return Path(path).read_text(encoding="utf-8")

    def render_jinja(
        self,
        target: str,
        context: Optional[dict] = None,
        environment: Optional[Any] = None,
    ) -> str:
        """Renderizza una stringa Jinja con i global registrati in Infrastructure."""
        if not isinstance(target, str):
            return target
        if "{{" not in target and "{%" not in target and "{#" not in target:
            return target

        return template.render_jinja(self, target, context, environment)

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
                return scheme.convert(rendered, format="toml")
            case p if p.endswith(".json"):
                content = self.get_resource(path_str)
                rendered = self.render_jinja(content)
                return scheme.convert(rendered, format="json")
            case p if p.endswith(".dsl"):
                content = self.get_resource(path_str)
                environment = self.get_jinja(
                    loader=template.FileSystemLoader(
                        str(Path(__file__).resolve().parents[3] / "src" / "application" / "policy")
                    ),
                    autoescape=False,
                    keep_trailing_newline=True,
                    undefined=template.StrictUndefined,
                )
                return self.render_jinja(content, environment=environment)
            case _:
                # Caso di default se l'estensione non coincide
                raise ValueError(f"Formato file non supportato: {path_str}")