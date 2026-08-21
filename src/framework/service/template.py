import xml.etree.ElementTree as ET

from jinja2 import DebugUndefined, Environment, FileSystemLoader, select_autoescape


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
        data[controller] = await runtime_session.run(
            controller,
            {"session": runtime_session}|managers,
        )

    #raise Exception(data)

    content = template.render(
        constants | {"sid": runtime_session} | data | {"manager": loader.get_managers()}
    )
    xml = ET.fromstring(content)
    return await render_node(content, xml, constants, runtime_session=runtime_session)
