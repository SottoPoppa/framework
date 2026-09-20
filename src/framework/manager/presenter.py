import framework.port.presentation as presentation
import framework.port.manager as manager
import framework.core.flow as flow
from framework.manager.loader import Loader
import framework.core.framework as framework_module

class Manager(manager.Port):
    _session_exempt_methods = {
        "sono_stessa_risorsa",
    }
    def __init__(
        self,
        presentations: list[presentation.Port],
        loader: Loader,
        framework: framework_module.Framework,
        **constants,
    ):
        self.presentations = presentations
        self.loader = loader
        self.framework = framework
        #self.executor = constants.get('executor')

    @flow.result(inputs=(), outputs=())
    async def startup(self, session):
        loops = []
        for presentation in self.presentations:
            if hasattr(presentation, 'start'):
                res = await presentation.start(session)
                if flow.is_result(res):
                    if not res.get('success'):
                        return res
                    res = flow.output(res)
                if res:
                    loops.append(res)
        return loops

    @flow.result(inputs=(), outputs=())
    async def shutdown(self , session):
        for presentation in self.presentations:
            if hasattr(presentation, 'stop'):
                await presentation.stop(session)

    @flow.result(inputs=(), outputs=())
    async def get_view(self, session, path):
        return await self.loader.resource(path)

    @flow.result(inputs=(), outputs=())
    async def get_attribute(self, session, **constants):
        driver = self._get_driver()
        return await driver.get_attribute(constants.get('widget'),constants.get('field')) if driver else None

    def _get_driver(self):
        return self.presentations[-1] if self.presentations else None

    @flow.result(inputs=(), outputs=())
    async def selector(self, session, **constants):
        driver = self._get_driver()
        return await driver.selector(**constants) if driver else None

    @flow.result(inputs=(), outputs=())
    async def render(self, session, node_id, context=None):
        driver = self._get_driver()
        if driver and hasattr(driver, 'rebuild'):
            return await driver.rebuild(session, node_id, context)
        return None
    
    @flow.result(inputs=(), outputs=())
    async def navigate(self, session, **constants):
        driver = self._get_driver()
        return await driver.apply_route(**constants) if driver else None
        
    @flow.result(inputs=(), outputs=())
    async def rebuild(self, session, node_id, context=None):
        driver = self._get_driver()
        if driver and hasattr(driver, 'rebuild'):
            return await driver.rebuild(session, node_id, context)
        return None

    def sono_stessa_risorsa(self, p1: str, p2: str) -> bool:
        if not p1 or not p2:
            return False

        # 1. Uniforma le barre e rimuove slash iniziali/finali o './'
        parts1 = [p for p in p1.replace("\\", "/").split("/") if p and p != "."]
        parts2 = [p for p in p2.replace("\\", "/").split("/") if p and p != "."]

        if not parts1 or not parts2:
            return False

        # 2. Prende il percorso più corto come riferimento
        if len(parts1) <= len(parts2):
            short, long = parts1, parts2
        else:
            short, long = parts2, parts1

        # 3. Verifica che la coda (i segmenti finali) del percorso più lungo 
        #    corrisponda esattamente a tutti i segmenti del percorso più corto
        return long[-len(short):] == short

    @flow.result(inputs=(), outputs=())
    async def reload(self, session, path):
        driver = self._get_driver()
        if driver and hasattr(driver, 'render_view') and hasattr(driver, 'routes') and hasattr(driver, 'url'):
            route_data = driver.routes.get(driver.url, {}).get('GET', {})
            view_path = route_data.get('view')
            if view_path and self.sono_stessa_risorsa(path, view_path):
                await driver.render_view(driver.url)
