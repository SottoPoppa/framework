import xml.etree.ElementTree as ET
import os
from pathlib import Path

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateError,
    TemplateNotFound,
    Undefined,
    nodes,
    select_autoescape,
)
import framework.core.flow as flow
import framework.service.scheme as scheme

class DeferredUndefined(Undefined):
    """Mantiene le espressioni da valutare dopo un nodo dati asincrono."""

    def __init__(self, hint=None, obj=None, name=None, exc=None, expression=None):
        super().__init__(hint=hint, obj=obj, name=name, exc=exc)
        self._expression = expression or name or ""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return type(self)(expression=f"{self._expression}.{name}")

    def __getitem__(self, key):
        if isinstance(key, str):
            expression = f"{self._expression}[{key!r}]"
        else:
            expression = f"{self._expression}[{key}]"
        return type(self)(expression=expression)

    def __str__(self):
        return "{{ " + self._expression + " }}"

    def __html__(self):
        return str(self)

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())


def _result_output(value):
    """Restituisce il payload sia da un Result sia dalla sua forma serializzata."""
    if flow.is_result(value):
        return flow.output(value)
    if isinstance(value, dict):
        output = value.get("output")
        if isinstance(output, dict) and "is_success" in output:
            return output.get("value") if output["is_success"] else output.get("error")
    return value


def _result_success(value):
    """Indica se un valore rappresenta un risultato riuscito."""
    if flow.is_result(value):
        return value.is_success
    if isinstance(value, dict):
        output = value.get("output")
        if isinstance(output, dict) and "is_success" in output:
            return bool(output["is_success"])
    return True


def _template_filters():
    return {
        "value": _result_output,
        "check": _result_success,
        "get": lambda d, key: d.get(key) if isinstance(d, dict) else None,
    }


def get_jinja(infrastructure=None, **options):
    """Restituisce un ambiente Jinja, usando la cache se disponibile."""
    key = tuple(sorted((name, id(value)) for name, value in options.items()))
    if infrastructure is None:
        environment = Environment(**options)
    else:
        environment = infrastructure.jinja_environments.get(key)
        if environment is None:
            environment = Environment(**options)
            infrastructure.jinja_environments[key] = environment
    environment.filters.update(_template_filters())
    return environment


def _select_environment(infrastructure, target: str):
    default = get_jinja(infrastructure)
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
    for environment in infrastructure.jinja_environments.values():
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


def render_jinja(infrastructure, target: str, context=None, environment=None) -> str:
    if not isinstance(target, str):
        return target
    if "{{" not in target and "{%" not in target and "{#" not in target:
        return target
    environment = environment or _select_environment(infrastructure, target)
    payload = {
        "env": lambda name, default="": os.environ.get(name, default),
        **(context or {}),
    }
    return environment.from_string(target).render(**payload)


async def format(target, infrastructure=None, **constants):
    """Formatta una stringa usando l'ambiente Jinja dell'infrastruttura."""
    try:
        if not target:
            return target
        if not isinstance(target, str):
            target = str(target)
        if "{" not in target:
            return target
        environment = get_jinja(
            infrastructure,
            autoescape=select_autoescape(["html", "xml"]),
        )
        return render_jinja(
            infrastructure,
            target,
            context=constants,
            environment=environment,
        )
    except Exception as e:
        raise ValueError(f"Errore formattazione: {e}")


async def render(
    infrastructure,
    managers,
    runtime_session,
    render_node,
    text=None,
    file=None,
    controllers=None,
    source_name=None,
    prepare_context=None,
    **constants,
):
    if text is None and file is None:
        raise ValueError("No text or file provided")
    if text is None:
        text = infrastructure.resource(file)
    elif isinstance(text, ET.Element):
        text = ET.tostring(text, encoding="unicode")
    elif not isinstance(text, str):
        text = str(text)
    source_name = source_name or file or "template string"

    environment = get_jinja(
        infrastructure,
        loader=FileSystemLoader("src/application/view/layout/"),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=DeferredUndefined,
    )
    try:
        template = environment.from_string(text)
    except TemplateError as error:
        line = getattr(error, "lineno", None)
        location = f" riga {line}" if line else ""
        raise flow.LocatedError(
            f"Errore sintassi Jinja in '{source_name}'{location}: {error}",
            source_file=source_name,
            source_line=line,
            source_function="Jinja template",
        ) from error
    data = {}
    manager_context = {"manager": managers}
    for controller in controllers or []:
        runtime_session.context["session"] = runtime_session
        run_result = await runtime_session.run(
            controller,
            {"session": runtime_session} | manager_context,
        )
        data[controller] = flow.output(run_result)

    #raise Exception(data)

    render_context = constants | data | manager_context
    if prepare_context is not None:
        render_context = await prepare_context(runtime_session, text, render_context)
    content = template.render(render_context)
    try:
        xml = ET.fromstring(content)
    except ET.ParseError as error:
        line, column = getattr(error, "position", (None, None))
        rendered_line = None
        if line and 1 <= line <= len(content.splitlines()):
            rendered_line = content.splitlines()[line - 1].strip()
        raise flow.LocatedError(
            f"Errore XML in '{source_name}': {error}",
            source_file=source_name,
            source_line=line,
            source_column=column,
            source_function="rendered XML",
            source_code=rendered_line,
            source_context=(
                f"> {line}: {rendered_line}" if line and rendered_line else None
            ),
        ) from error
    return await render_node(
        content,
        xml,
        {"_jinja_context": render_context},
        runtime_session=runtime_session,
    )
