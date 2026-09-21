import framework.port.network as network
import framework.port.manager as manager
import framework.core.flow as flow
import framework.manager.loader as loader
import framework.core.framework as framework_module
from framework.service.diagnostic import get_logger

class Manager(manager.Port):
    def __init__(
        self,
        networks: list[network.Port],
        loader: loader.Loader,
        framework: framework_module.Framework,
        **constants,
    ):
        self.networks = networks
        self.framework = framework
        self.logger = (
            framework.get_logger("networker")
            if framework is not None and hasattr(framework, "get_logger")
            else get_logger("networker")
        )

    @staticmethod
    def _provider_name(provider) -> str:
        return (
            getattr(provider, "name", None)
            or getattr(provider, "adapter", None)
            or type(provider).__name__
        )

    def _select_provider(self, requirements: dict) -> object | None:
        best = None
        best_score = -1

        for provider in self.networks:
            capabilities = dict(getattr(provider, 'capabilities', {}) or {})
            if hasattr(provider, 'platform') and provider.platform is not None:
                capabilities.setdefault('platform', provider.platform)
            if hasattr(provider, 'PLATFORM') and getattr(provider, 'PLATFORM') is not None:
                capabilities.setdefault('platform', getattr(provider, 'PLATFORM'))
            if hasattr(provider, 'requires') and isinstance(getattr(provider, 'requires'), dict):
                for k, v in getattr(provider, 'requires').items():
                    capabilities.setdefault(k, v)

            score = 0
            match = True
            for key, expected in requirements.items():
                actual = capabilities.get(key)
                if actual == expected:
                    score += 2
                elif actual is not None:
                    score += 1
                else:
                    match = False
                    break

            if match and score > best_score:
                best = provider
                best_score = score

        self.logger.debug(
            "Networker: provider selezionato",
            requirements=requirements,
            provider=self._provider_name(best) if best is not None else None,
        )
        return best

    @flow.result(inputs='intent')
    async def provision(self, session, intent: dict):
        requirements = intent.get('requirements', {})
        self.logger.debug("Networker: provision avviato", requirements=requirements)
        provider = self._select_provider(requirements)
        if provider is None:
            self.logger.warning(
                "Networker: nessun provider disponibile per provision",
                requirements=requirements,
            )
            return flow.error(f"Nessun provider SD-WAN disponibile per i requisiti: {requirements}")
        result = await provider.provision(intent=intent)
        self.logger.debug(
            "Networker: provision completato",
            provider=self._provider_name(provider),
        )
        return result

    @flow.result(inputs=('application', 'requirements'))
    async def route(self, session, application: dict, requirements: dict):
        self.logger.debug("Networker: route avviato", requirements=requirements)
        provider = self._select_provider(requirements)
        if provider is None:
            self.logger.warning(
                "Networker: nessun provider disponibile per route",
                requirements=requirements,
            )
            return flow.error(f"Nessun provider SD-WAN selezionato per i requisiti: {requirements}")
        result = await provider.route(application=application, requirements=requirements)
        self.logger.debug(
            "Networker: route completata",
            provider=self._provider_name(provider),
        )
        return result

    @flow.result()
    async def compute(self, session):
        self.logger.debug("Networker: compute avviato", providers=len(self.networks))
        results = []
        for provider in self.networks:
            result = await provider.compute()
            results.append(result)
        self.logger.debug("Networker: compute completato", providers=len(results))
        return results

    @flow.result()
    async def monitor(self, session):
        self.logger.debug("Networker: monitor avviato", providers=len(self.networks))
        statuses = []
        for provider in self.networks:
            if hasattr(provider, 'monitor'):
                statuses.append(await provider.monitor())
        self.logger.debug("Networker: monitor completato", providers=len(statuses))
        return flow.success({"networks": statuses})

    @flow.result()
    async def status(self, session):
        self.logger.debug("Networker: status avviato", providers=len(self.networks))
        network_status = {}
        for provider in self.networks:
            if hasattr(provider, 'status'):
                result = await provider.status()
                network_status[self._provider_name(provider)] = result
        self.logger.debug("Networker: status completato", providers=len(network_status))
        return flow.success(network_status)
