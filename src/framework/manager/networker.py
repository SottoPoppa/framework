from typing import Any

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
        loader: loader.Loader | None,
        framework: framework_module.Framework | None,
        **constants: Any,
    ) -> None:
        self.networks = networks
        self.framework = framework
        self.logger: Any = (
            framework.get_logger("networker")
            if framework is not None
            else get_logger("networker")
        )

    @staticmethod
    def _provider_name(provider: network.Port) -> str:
        return (
            getattr(provider, "name", None)
            or getattr(provider, "adapter", None)
            or type(provider).__name__
        )

    def _select_provider(
        self,
        requirements: dict[str, Any],
    ) -> network.Port | None:
        best: network.Port | None = None
        best_score = -1

        for provider in self.networks:
            capabilities = dict(getattr(provider, 'capabilities', {}) or {})
            platform = getattr(provider, 'platform', None)
            if platform is not None:
                capabilities.setdefault('platform', platform)
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

        return best

    @flow.result(inputs='intent')
    async def provision(
        self,
        session: object,
        intent: dict[str, Any],
    ) -> flow.FlowResult:
        requirements = intent.get('requirements', {})
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
    async def route(
        self,
        session: object,
        application: dict[str, Any],
        requirements: dict[str, Any],
    ) -> flow.FlowResult:
        provider = self._select_provider(requirements)
        if provider is None:
            self.logger.warning(
                "Networker: nessun provider disponibile per route",
                requirements=requirements,
            )
            return flow.error(f"Nessun provider SD-WAN selezionato per i requisiti: {requirements}")
        result = await provider.route(payload=application, requirements=requirements)
        self.logger.debug(
            "Networker: route completata",
            provider=self._provider_name(provider),
        )
        return result

    @flow.result()
    async def compute(self, session: object) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for provider in self.networks:
            result = await provider.compute()
            results.append(result)
        self.logger.debug("Networker: compute completato", providers=len(results))
        return results

    @flow.result()
    async def monitor(self, session: object) -> flow.FlowResult:
        statuses: list[flow.FlowResult] = []
        for provider in self.networks:
            if hasattr(provider, 'monitor'):
                statuses.append(await provider.monitor())
        self.logger.debug("Networker: monitor completato", providers=len(statuses))
        return flow.success({"networks": statuses})

    @flow.result()
    async def status(self, session: object) -> flow.FlowResult:
        network_status: dict[str, flow.FlowResult] = {}
        for provider in self.networks:
            if hasattr(provider, 'status'):
                result = await provider.status()
                network_status[self._provider_name(provider)] = result
        self.logger.debug("Networker: status completato", providers=len(network_status))
        return flow.success(network_status)
