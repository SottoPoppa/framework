import framework.port.presentation as presentation
import framework.port.manager as manager
import framework.core.flow as flow
import framework.core.flow as flow
from framework.manager.loader import Loader
import framework.core.framework as framework_module
from collections.abc import Awaitable, Callable
from typing import Any, cast

class Manager(manager.Port):
    def __init__(
        self,
        presentations: list[presentation.Port],
        loader: Loader,
        framework: framework_module.Framework,
        **constants: Any,
    ) -> None:
        self.presentations: list[Any] = presentations
        self.loader = loader
        self.framework = framework
        self.logger = framework.get_logger("presenter")
        #self.executor = constants.get('executor')

    @flow.result(inputs=(), outputs=())
    async def startup(self, session: Any) -> list[Any]:
        loops: list[Any] = []
        self.logger.info("Presenter startup", presentations=len(self.presentations))
        for presentation in self.presentations:
            current: Any = presentation
            if callable(getattr(current, "start", None)):
                async def run_presentation(current: Any = current) -> Any:
                    self.logger.info(
                        "Avvio presentation adapter",
                        adapter=getattr(current, "name", None) or type(current).__name__,
                        type=type(current).__name__,
                    )
                    result = await cast(
                        Callable[..., Awaitable[Any]], current.start
                    )(session)
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
    async def shutdown(self, session: Any) -> None:
        for presentation in self.presentations:
            stop = getattr(presentation, "stop", None)
            if callable(stop):
                await cast(Callable[..., Awaitable[Any]], stop)(session)

    @flow.result(inputs=(), outputs=())
    async def get_view(self, session: Any, path: str) -> Any:
        return await self.loader.resource(path)

    @flow.result(inputs=(), outputs=())
    async def get_attribute(
        self, session: Any, **constants: Any
    ) -> Any:
        driver = self._get_driver(session)
        return await driver.get_attribute(constants.get('widget'),constants.get('field')) if driver else None

    def _get_driver(self, session: Any = None) -> Any | None:
        session_id = getattr(session, "sid", None)
        if session_id is None:
            session_data = getattr(session, "session_data", None)
            if isinstance(session_data, dict):
                session_id = cast(dict[str, Any], session_data).get("id")
            elif session_data is not None:
                get_value = getattr(session_data, "get", None)
                session_id = get_value("id") if callable(get_value) else getattr(session_data, "id", None)
        if session_id is None:
            get_value = getattr(session, "get", None)
            if callable(get_value):
                session_id = get_value("id")

        if session_id is not None:
            for presentation in self.presentations:
                if session_id in getattr(presentation, "sessions", {}):
                    return presentation
                adapter_session = getattr(presentation, "session", None)
                if getattr(adapter_session, "sid", None) == session_id:
                    return presentation
        return self.presentations[-1] if self.presentations else None

    def _runtime_session(self, session: Any) -> Any:
        if callable(getattr(session, "run", None)) and callable(
            getattr(session, "emit", None)
        ):
            return session

        managers = self.loader.get_managers()
        defender = managers.get("defender")
        runtime_session = defender.session_get(session) if defender else None
        if runtime_session is None:
            raise RuntimeError("SessionHandle non disponibile per SessionData")
        return runtime_session

    @flow.result(inputs=(), outputs=())
    async def selector(self, session: Any, **constants: Any) -> Any:
        driver = self._get_driver(session)
        return await driver.selector(**constants) if driver else None

    @flow.result(inputs=(), outputs=())
    async def render(
        self,
        session: Any,
        node_id: str,
        context: dict[str, Any] | None = None,
    ) -> Any:
        driver = self._get_driver(session)
        if driver and hasattr(driver, 'rebuild'):
            runtime_session = self._runtime_session(session)
            driver = self._get_driver(runtime_session) or driver
            return await driver.rebuild(runtime_session, node_id, context)
        return None
    
    @flow.result(inputs=(), outputs=())
    async def navigate(self, session: Any, **constants: Any) -> Any:
        driver = self._get_driver(session)
        return await driver.apply_route(**constants) if driver else None
        
    @flow.result(inputs=(), outputs=())
    async def rebuild(
        self,
        session: Any,
        node_id: str,
        context: dict[str, Any] | None = None,
    ) -> Any:
        driver = self._get_driver(session)
        if driver and hasattr(driver, 'rebuild'):
            runtime_session = self._runtime_session(session)
            driver = self._get_driver(runtime_session) or driver
            return await driver.rebuild(runtime_session, node_id, context)
        return None

    @flow.result(inputs=(), outputs=())
    async def reload(self, session: Any, path: str) -> Any:
        driver = self._get_driver(session)
        if driver and hasattr(driver, 'render_view') and hasattr(driver, 'routes') and hasattr(driver, 'url'):
            route_data = driver.routes.get(driver.url, {}).get('GET', {})
            view_path = route_data.get('view')
            infrastructure = self.loader.infrastructure
            if view_path and infrastructure.same_resource(path, view_path):
                return await driver.render_view(driver.url)
