import framework.port.presentation as presentation
import framework.port.manager as manager
import framework.core.flow as flow
from framework.service.diagnostic import get_logger
from framework.manager.loader import Loader
import framework.core.framework as framework_module

class Manager(manager.Port):
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
        self.logger = framework.get_logger("presenter")
        #self.executor = constants.get('executor')

    @flow.result(inputs=(), outputs=())
    async def startup(self, session):
        loops = []
        self.logger.info("Presenter startup", presentations=len(self.presentations))
        for presentation in self.presentations:
            if hasattr(presentation, 'start'):
                async def run_presentation(current=presentation):
                    self.logger.info(
                        "Avvio presentation adapter",
                        adapter=getattr(current, "name", None) or type(current).__name__,
                        type=type(current).__name__,
                    )
                    result = await current.start(session)
                    self.logger.info(
                        "Presentation adapter terminato",
                        result_type=type(result).__name__,
                    )
                    if flow.is_result(result) and not flow.check(result):
                        raise RuntimeError(flow.output(result))
                    return flow.output(result) if flow.is_result(result) else result

                loops.append(run_presentation())
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

    @flow.result(inputs=(), outputs=())
    async def reload(self, session, path):
        driver = self._get_driver()
        if driver and hasattr(driver, 'render_view') and hasattr(driver, 'routes') and hasattr(driver, 'url'):
            route_data = driver.routes.get(driver.url, {}).get('GET', {})
            view_path = route_data.get('view')
            infrastructure = self.loader.infrastructure
            if view_path and infrastructure.same_resource(path, view_path):
                await driver.render_view(driver.url)
