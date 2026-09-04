import xml.etree.ElementTree as ET

from jinja2 import DebugUndefined, Environment, FileSystemLoader, select_autoescape
import framework.core.flow as flow

'''jinja_env = Environment(
    loader=FileSystemLoader("src/application/view/layout/"),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=DebugUndefined,
)'''

jinja_env = Environment()


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
    "result_value": _result_output,
    "result_success": _result_success,
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

    environment = Environment(
        loader=FileSystemLoader("src/application/view/layout/"),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=DebugUndefined,
    )
    environment.filters.update(jinja_env.filters)
    template = environment.from_string(text)
    data = {}
    managers = {"manager": loader.get_managers()}
    for controller in controllers or []:
        run_result = await runtime_session.run(
            controller,
            {"session": runtime_session}|managers,
        )
        data[controller] = flow.output(run_result)

    #raise Exception(data)

    content = template.render(
        constants | data | {"manager": loader.get_managers()}
    )
    xml = ET.fromstring(content)
    return await render_node(content, xml, constants, runtime_session=runtime_session)
