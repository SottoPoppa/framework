import xml.etree.ElementTree as ET

from jinja2 import Environment, FileSystemLoader, TemplateError, Undefined, select_autoescape
import framework.core.flow as flow
import framework.core.scheme as scheme

'''jinja_env = Environment(
    loader=FileSystemLoader("src/application/view/layout/"),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=DebugUndefined,
)'''

jinja_env = Environment(
    autoescape=select_autoescape(['html', 'xml'])
)


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


jinja_env.filters.update({
    "value": _result_output,
    "check": _result_success,
    "get": lambda d, key: d.get(key) if isinstance(d, dict) else None,
})

async def format(target, **constants):
    """Formatta una stringa usando Jinja2 e l'environment condiviso (jinja)."""
    try:
        if not target:
            return target
        if not isinstance(target, str):
            target = str(target)
        if '{' not in target:
            return target
        template = jinja_env.from_string(target)
        return template.render(**constants)
    except Exception as e:
        raise ValueError(f"Errore formattazione: {e}")

async def render(loader, runtime_session, render_node, text=None, file=None, controllers=None, **constants):
    if text is None and file is None:
        raise ValueError("No text or file provided")
    if text is None:
        text = await loader.resource(file)
    source_name = file or "template string"

    environment = Environment(
        loader=FileSystemLoader("src/application/view/layout/"),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=DeferredUndefined,
    )
    environment.filters.update(jinja_env.filters)
    try:
        template = environment.from_string(text)
    except TemplateError as error:
        line = getattr(error, "lineno", None)
        location = f" riga {line}" if line else ""
        raise ValueError(
            f"Errore sintassi Jinja in '{source_name}'{location}: {error}"
        ) from error
    data = {}
    managers = {"manager": loader.get_managers()}
    for controller in controllers or []:
        runtime_session.context["session"] = runtime_session
        run_result = await runtime_session.run(
            controller,
            {"session": runtime_session}|managers,
        )
        data[controller] = flow.output(run_result)

    #raise Exception(data)

    render_context = constants | data | {"manager": loader.get_managers()}
    content = template.render(render_context)
    try:
        xml = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError(
            f"Errore XML in '{source_name}': {error}"
        ) from error
    return await render_node(
        content,
        xml,
        {"_jinja_context": render_context},
        runtime_session=runtime_session,
    )
