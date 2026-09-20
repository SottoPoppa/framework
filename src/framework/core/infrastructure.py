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

    @staticmethod
    def same_resource(first: str, second: str) -> bool:
        """Confronta due riferimenti normalizzati alla stessa risorsa."""
        if not first or not second:
            return False

        first_parts = [
            part for part in str(first).replace("\\", "/").split("/")
            if part and part != "."
        ]
        second_parts = [
            part for part in str(second).replace("\\", "/").split("/")
            if part and part != "."
        ]
        if not first_parts or not second_parts:
            return False

        shorter, longer = sorted((first_parts, second_parts), key=len)
        return longer[-len(shorter):] == shorter

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

    async def load_schemes(self, directories: list[str]) -> dict:
        """Carica e risolve ricorsivamente i file di schema JSON nelle cartelle."""
        schemes = self._load_scheme_files(directories)
        final = scheme.resolve_schemes(schemes, self.render_jinja)
        if final:
            self.logger.info("Schemi caricati", schemas=sorted(final))
        else:
            self.logger.warning("Nessuno schema trovato")
        return final

    def resource(self, path: str | Path) -> str:
        """Legge un file risorsa dal file-system in modo asincrono/trasparente."""
        path_str = str(path)
        self.logger.debug("Caricamento risorsa", path=path_str)
        
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
            case p if p.endswith(".xml"):
                content = self.get_resource(path_str)
                self.logger.debug(
                    "Risorsa XML caricata",
                    path=path_str,
                    size=len(content),
                )
                return content
            case _:
                # Caso di default se l'estensione non coincide
                raise ValueError(f"Formato file non supportato: {path_str}")