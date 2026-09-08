import os
import ast
import inspect
import hashlib
import json
import re
from pathlib import Path

class Reflection:
    """Utility di reflection sui moduli Python."""

    @staticmethod
    def imports(code: str) -> list[str]:
        try:
            tree = ast.parse(code)
        except Exception:
            return []

        result = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.add(alias.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result.add(node.module)

        return list(result)

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def class_methods(cls, names: set[str] | None = None) -> dict[str, str]:
        """Sorgente dei metodi definiti direttamente su `cls`.

        Senza `names` conserva il comportamento storico e considera solo i
        metodi pubblici. Con una selezione esplicita permette a un contract di
        certificare anche un metodo privato dichiarato intenzionalmente.
        """
        methods = {}
        for name, member in vars(cls).items():
            if names is None and name.startswith('_'):
                continue
            if names is not None and name not in names:
                continue
            fn = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
            if not inspect.isfunction(fn):
                continue
            try:
                methods[name] = inspect.getsource(fn)
            except (OSError, TypeError):
                continue
        return methods

    @staticmethod
    def module_components(module, names: set[str] | None = None) -> dict[str, str]:
        """Sorgente di tutti i componenti pubblici definiti DIRETTAMENTE in
        `module` (esclude import): funzioni a livello di modulo e metodi
        delle classi definite nel modulo.

        Generalizza `class_methods` a qualunque tipo di file (adapter,
        manager, service, ...): non presuppone che il modulo esponga una
        classe con un nome specifico.

        Chiavi risultanti:
            'nome_funzione'            per funzioni a livello di modulo
            'NomeClasse.nome_metodo'   per metodi di classi nel modulo
        """
        components: dict[str, str] = {}
        selected = set(names) if names is not None else None
        for name, member in vars(module).items():
            if selected is None and name.startswith('_'):
                continue
            if selected is not None and name not in selected and not any(
                item.startswith(f"{name}.") for item in selected
            ):
                continue
            if inspect.isfunction(member) and getattr(member, "__module__", None) == module.__name__:
                try:
                    components[name] = inspect.getsource(member)
                except (OSError, TypeError):
                    continue
            elif inspect.isclass(member) and member.__module__ == module.__name__:
                class_names = None
                if selected is not None:
                    class_names = {
                        item.split(".", 1)[1]
                        for item in selected
                        if item.startswith(f"{name}.")
                    }
                for method_name, source in Reflection.class_methods(member, class_names).items():
                    components[f"{name}.{method_name}"] = source
        return components

    @staticmethod
    def dependencies(cls):
        return {
            name: p.annotation
            for name, p in inspect.signature(cls.__init__).parameters.items()
            if name != "self"
            and p.annotation is not inspect.Parameter.empty
        }

    @staticmethod
    def is_port_list(annotation):
        return (
            getattr(annotation, "__origin__", None)
            is list
        )

    @staticmethod
    def file_dependencies(file_path: str, root="src"):
        source_path = Path(file_path)
        root_path = Path(root)

        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return []

        def rooted_path(path):
            try:
                relative = Path(path).relative_to(root_path)
                return str(root_path / relative)
            except ValueError:
                return str(path)

        deps = {rooted_path(file_path)}

        def add(path):
            if path.exists():
                deps.add(rooted_path(path))

        def add_import(module):
            module_path = Path(root_path, *module.split("."))
            add(module_path.with_suffix(".py"))

        if source_path.suffix == ".py":
            try:
                tree = ast.parse(source)
            except SyntaxError:
                return sorted(deps)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        add_import(alias.name)

                elif isinstance(node, ast.ImportFrom):
                    if node.module is None:
                        continue

                    base = Path(root_path, *node.module.split("."))
                    module = base.with_suffix(".py")
                    if module.exists():
                        add(module)
                        continue

                    for alias in node.names:
                        if alias.name != "*":
                            add((base / alias.name).with_suffix(".py"))

        elif source_path.suffix == ".dsl":
            imports = re.search(
                r"\bimports\s*:\s*\{(?P<body>.*?)\}",
                source,
                flags=re.DOTALL,
            )
            if imports:
                for kind, reference in re.findall(
                    r"\b(import|resource)\s*\(\s*[\"']([^\"']+)[\"']\s*\)",
                    imports.group("body"),
                ):
                    if kind == "import":
                        add_import(reference)
                    else:
                        add(Path(root_path, reference))

        elif source_path.suffix == ".json":
            try:
                json.loads(source)
            except json.JSONDecodeError:
                return sorted(deps)

            for reference in re.findall(
                r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}",
                source,
            ):
                candidates = (
                    source_path.parent / f"{reference}.json",
                    root_path / "framework" / "scheme" / f"{reference}.json",
                    root_path / "application" / "model" / f"{reference}.json",
                )
                for candidate in candidates:
                    if candidate.exists():
                        add(candidate)
                        break

        return sorted(deps)

    @staticmethod
    def dependencies(cls):
        return {
            name: p.annotation
            for name, p in inspect.signature(cls.__init__).parameters.items()
            if (
                name != "self"
                and p.annotation is not inspect.Parameter.empty
            )
        }

    @staticmethod
    def is_port_list(annotation):
        return (
            getattr(annotation, "__origin__", None)
            is list
        )