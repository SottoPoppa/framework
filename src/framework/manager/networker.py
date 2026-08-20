import framework.port.network as network
import framework.service.flow as flow

class Manager:
    def __init__(self, networks: list[network.Port], **constants):
        self.networks = networks

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

        return best

    @flow.result(inputs='intent')
    async def provision(self, intent: dict):
        requirements = intent.get('requirements', {})
        provider = self._select_provider(requirements)
        if provider is None:
            return flow.error(f"Nessun provider SD-WAN disponibile per i requisiti: {requirements}")
        return await provider.provision(intent=intent)

    @flow.result(inputs=('application', 'requirements'))
    async def route(self, application: dict, requirements: dict):
        provider = self._select_provider(requirements)
        if provider is None:
            return flow.error(f"Nessun provider SD-WAN selezionato per i requisiti: {requirements}")
        return await provider.route(application=application, requirements=requirements)

    @flow.result()
    async def compute(self):
        results = []
        for provider in self.networks:
            result = await provider.compute()
            results.append(result)
        print("Results from all providers:", results)
        return results

    @flow.result()
    async def monitor(self):
        statuses = []
        for provider in self.networks:
            if hasattr(provider, 'monitor'):
                statuses.append(await provider.monitor())
        return flow.success({"networks": statuses})

    @flow.result()
    async def status(self):
        network_status = {}
        for provider in self.networks:
            if hasattr(provider, 'status'):
                result = await provider.status()
                network_status[provider.name] = result
        return flow.success(network_status)
