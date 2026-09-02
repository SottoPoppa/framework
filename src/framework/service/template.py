import xml.etree.ElementTree as ET

from jinja2 import DebugUndefined, Environment, FileSystemLoader, select_autoescape
import framework.core.flow as flow

'''jinja_env = Environment(
    loader=FileSystemLoader("src/application/view/layout/"),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=DebugUndefined,
)'''

jinja_env = Environment()

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
        constants | {"sid": runtime_session} | data | {"manager": loader.get_managers()}
    )
    xml = ET.fromstring(content)
    return await render_node(content, xml, constants, runtime_session=runtime_session)
