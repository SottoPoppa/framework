import asyncio

import framework.port.persistence as persistence
import framework.port.manager as manager
import framework.core.flow as flow
from framework.service.factory import Repository

from framework.manager.messenger import Manager as Messenger
from framework.manager.orchestrator import Manager as Orchestrator
from framework.manager.defender import Manager as Defender


class Manager(manager.Port):

    def __init__(
        self,
        providers: list[persistence.Port],
        defender: Defender,
        orchestrator: Orchestrator,
        messenger: Messenger,
        **constants,
    ):
        self.orchestrator = orchestrator
        self.defender = defender
        self.persistences = providers
        self.repositories = constants.get("repositories", {})
        self.maked = constants.get("maked", {})
        self.messenger = messenger

    @flow.result()
    async def startup(self, session):
        await self.messenger.send(session, message="Storekeeper avviato.", domain="console:info")
        for provider in self.persistences:
            start = getattr(provider, 'start', None)
            if callable(start):
                await start(session)
        return flow.success(None)

    @flow.result()
    async def shutdown(self, session):
        await self.messenger.send(session, message="Storekeeper arrestato.", domain="console:info")
        return flow.success(None)

    @flow.result()
    async def _load_repository(self, repository_name: str):
        """Carica e mette in cache il repository DSL richiesto."""
        if repository_name not in self.maked:
            path = f'src/application/repository/{repository_name}.dsl'
            code = await self.defender.loader.resource(path)
            await self.defender.interpreter.load_file(path, code)
            session_result = await self.defender.session_create()
            async with flow.output(session_result) as repository_session:
                run_result = await repository_session.run(path)
                self.repositories[repository_name] = flow.output(run_result)
            self.maked[repository_name] = Repository(
                **self.repositories[repository_name]['repository']
            )
        repository = self.maked.get(repository_name)
        if repository is None:
            return flow.error(
                f"Repository '{repository_name}' non trovato o dati non disponibili."
            )
        return flow.success(repository)

    @flow.result()
    async def _prepare_provider(self, provider, repository, storekeeper, session):
        """Prepara il task di un provider compatibile, se disponibile."""
        configured_profile = provider.config.get('name')
        if not configured_profile:
            return flow.error(f"Provider {provider} non ha un profilo configurato.")
        profile = str(configured_profile).casefold()

        if profile not in repository.location:
            return flow.error(
                f"Provider {provider} repository_name {storekeeper.get('repository')} "
                f"profile {profile} non ha un profilo trovato."
            )

        operation = storekeeper.get('operation')
        try:
            task_args = await repository.parameters(
                **storekeeper | {'provider': profile, 'session': session}
            )
        except Exception as error:
            return flow.error(
                f"Errore durante l'ottenimento dei parametri per {profile}: {error}"
            )

        method = getattr(provider, operation, None)
        if not callable(method):
            return flow.error(
                f"Il metodo '{operation}' non è disponibile per il provider {profile}."
            )

        task = asyncio.create_task(
            method(session=session, storekeeper=task_args),
            name=profile,
        )
        task.parameters = task_args
        return flow.success(task)

    @flow.result()
    async def _prepare_operations(self, repository, storekeeper, session):
        """Crea i task per tutti i provider compatibili con il repository."""
        tasks = []
        repository_profiles = set(repository.location)
        providers = self.persistences
        policy = self.defender.get_policy("persistence") if self.defender else None
        security = policy.get("security", {}) if isinstance(policy, dict) else {}
        if self.defender and not self.defender.authorized(
            "persistence",
            session=session,
            context=storekeeper.get("context", {}),
            action=str(storekeeper.get("operation", "")).upper(),
            resource=storekeeper.get("repository", ""),
        ):
            return flow.error("Persistence policy denied the operation")
        if self.defender and security:
            providers = self.defender.authorized_adapters(
                session, "persistence", policy, self.persistences
            )
            if not providers:
                return flow.error("Nessun persistence provider autorizzato dalla policy di sicurezza")
        for provider in providers:
            provider_profile = str(provider.config.get('name', '')).casefold()
            if provider_profile not in repository_profiles:
                continue
            try:
                task = await self._prepare_provider(
                    provider, repository, storekeeper, session
                )
                if not flow.check(task):
                    for pending in tasks:
                        pending.cancel()
                    return task
                tasks.append(flow.output(task))
            except Exception as error:
                for task in tasks:
                    task.cancel()
                return flow.error(
                    f"Errore imprevisto durante la preparazione per il provider "
                    f"{provider}: {error}"
                )
        if not tasks:
            return flow.error(
                f"Nessun provider compatibile per il repository "
                f"'{storekeeper.get('repository')}'. "
                f"Profili richiesti: {sorted(repository_profiles)}."
            )
        return flow.success(tasks)

    @flow.result()
    async def preparation(self, session, storekeeper):
        repository_name = storekeeper.get('repository')
        if not repository_name:
            return flow.error("Nome del repository non specificato.")

        repository_result = await self._load_repository(repository_name)
        if not flow.check(repository_result):
            return repository_result
        repository = flow.output(repository_result)

        preparation = await self._prepare_operations(repository, storekeeper, session)
        if not flow.check(preparation):
            return preparation
        return flow.success((repository, flow.output(preparation)))
    
    @flow.result()
    async def _execute(self, operation, session, constants):
        state = await self.preparation(session, constants | {'operation': operation})
        if not flow.check(state):
            return state

        repository, operations = flow.output(state)
        return await self.orchestrator.first_completed(
            session,
            operations=operations,
            success=repository.results,
        )

    # overview/view/get
    @flow.result()
    async def overview(self, session, **constants):
        return await self._execute('view', session, constants)

    # gather/read/get
    @flow.result()
    async def gather(self, session, **constants):
        return await self._execute('read', session, constants)

    # store/create/put
    @flow.result()
    async def store(self, session, **constants):
        return await self._execute('create', session, constants)

    # remove/delete
    @flow.result()
    async def remove(self, session, **constants):
        return await self._execute('delete', session, constants)

    # change/update/patch
    @flow.result()
    async def change(self, session, **constants):
        return await self._execute('update', session, constants)