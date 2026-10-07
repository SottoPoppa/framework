from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, Unpack, cast

import framework.port.persistence as persistence
import framework.port.manager as manager
import framework.core.flow as flow
import framework.core.interpreter as interpreter
from framework.service.diagnostic import get_logger
from framework.service.factory import Repository
from framework.scheme.models import StorekeeperScheme

from framework.manager.messenger import Manager as Messenger
from framework.manager.orchestrator import Manager as Orchestrator
from framework.manager.defender import Manager as Defender

if TYPE_CHECKING:
    from framework.scheme.models import StorekeeperSchemeKwargs


class Manager(manager.Port):

    def __init__(
        self,
        providers: list[persistence.Port],
        defender: Defender,
        orchestrator: Orchestrator,
        messenger: Messenger,
        **constants: Any,
    ) -> None:
        self.orchestrator = orchestrator
        self.defender = defender
        self.persistences = providers
        self.repositories: dict[str, Any] = constants.get("repositories", {})
        self.maked: dict[str, Any] = constants.get("maked", {})
        self.messenger = messenger
        self.logger = get_logger("storekeeper")

    @flow.result()
    async def startup(self, session: interpreter.SessionHandle) -> flow.FlowResult:
        self.logger.info("Storekeeper: avvio", providers=len(self.persistences))
        notification = await self.messenger.send(
            session,
            message="Storekeeper avviato.",
            receiver="console",
            domain="info",
        )
        if flow.is_result(notification) and not flow.check(notification):
            self.logger.warning(
                "Storekeeper: notifica di avvio non inviata",
                error=flow.output(notification),
            )

        started: list[persistence.Port] = []
        for provider in self.persistences:
            start = getattr(provider, "start", None)
            if not callable(start):
                continue
            try:
                result = await cast(
                    Callable[..., Awaitable[Any]], start
                )(session)
            except Exception as exc:
                self.logger.error(
                    "Storekeeper: avvio provider fallito",
                    provider=type(provider).__name__,
                    exception=exc,
                )
                await self._stop_providers(started, session)
                return flow.error(exc)
            if flow.is_result(result) and not flow.check(result):
                self.logger.error(
                    "Storekeeper: avvio provider fallito",
                    provider=type(provider).__name__,
                    error=flow.output(result),
                )
                await self._stop_providers(started, session)
                return result
            started.append(provider)
        self.logger.info("Storekeeper: avvio completato")
        return flow.success(None)

    @flow.result()
    async def shutdown(self, session: interpreter.SessionHandle) -> flow.FlowResult:
        self.logger.info("Storekeeper: arresto")
        notification = await self.messenger.send(
            session,
            message="Storekeeper arrestato.",
            receiver="console",
            domain="info",
        )
        if flow.is_result(notification) and not flow.check(notification):
            self.logger.warning(
                "Storekeeper: notifica di arresto non inviata",
                error=flow.output(notification),
            )
        errors = await self._stop_providers(self.persistences, session)
        if errors:
            return flow.error(errors)
        self.logger.info("Storekeeper: arresto completato")
        return flow.success(None)

    async def _stop_providers(
        self, providers: Sequence[persistence.Port], session: object
    ) -> list[object]:
        errors: list[object] = []
        for provider in reversed(providers):
            stop = getattr(provider, "stop", None)
            if not callable(stop):
                continue
            try:
                result = await cast(
                    Callable[..., Awaitable[Any]], stop
                )(session)
            except Exception as exc:
                errors.append(exc)
                self.logger.error(
                    "Storekeeper: arresto provider fallito",
                    provider=type(provider).__name__,
                    exception=exc,
                )
                continue
            if flow.is_result(result) and not flow.check(result):
                error = flow.output(result)
                errors.append(error)
                self.logger.error(
                    "Storekeeper: arresto provider fallito",
                    provider=type(provider).__name__,
                    error=error,
                )
        return errors

    @flow.result()
    async def _load_repository(self, repository_name: str) -> flow.FlowResult:
        """Carica e mette in cache il repository DSL richiesto."""
        if repository_name not in self.maked:
            path = f'src/application/repository/{repository_name}.dsl'
            code_result = await self.defender.loader.resource(path)
            if flow.is_result(code_result) and not flow.check(code_result):
                self.logger.error(
                    "Storekeeper: caricamento del repository fallito",
                    repository=repository_name,
                    error=flow.output(code_result),
                )
                return code_result
            code = flow.output(code_result)
            load_result = await self.defender.interpreter.load_file(path, code)
            if flow.is_result(load_result) and not flow.check(load_result):
                self.logger.error(
                    "Storekeeper: compilazione del repository fallita",
                    repository=repository_name,
                    error=flow.output(load_result),
                )
                return load_result
            session_result = await self.defender.session_create()
            if flow.is_result(session_result) and not flow.check(session_result):
                self.logger.error(
                    "Storekeeper: creazione sessione repository fallita",
                    repository=repository_name,
                    error=flow.output(session_result),
                )
                return session_result
            repository_session = flow.output(session_result)
            async with repository_session:
                run_result = await repository_session.run(path)
                if flow.is_result(run_result) and not flow.check(run_result):
                    self.logger.error(
                        "Storekeeper: esecuzione repository fallita",
                        repository=repository_name,
                        error=flow.output(run_result),
                    )
                    return run_result
                repository_data = flow.output(run_result)
            self.repositories[repository_name] = repository_data
            self.maked[repository_name] = Repository(
                **self.repositories[repository_name]['repository']
            )
        repository = self.maked.get(repository_name)
        if repository is None:
            self.logger.warning("Storekeeper: repository non trovato", repository=repository_name)
            return flow.error(
                f"Repository '{repository_name}' non trovato o dati non disponibili."
            )
        return flow.success(repository)

    @flow.result()
    async def _prepare_provider(
        self,
        provider: persistence.Port,
        repository: Repository,
        storekeeper: StorekeeperScheme,
        constants: dict[str, Any],
        session: object,
    ) -> flow.FlowResult:
        """Prepara il task di un provider compatibile, se disponibile."""
        configured_profile = provider.config.get('name')
        if not configured_profile:
            return flow.error(f"Provider {provider} non ha un profilo configurato.")
        profile = str(configured_profile).casefold()

        if profile not in repository.location:
            return flow.error(
                f"Provider {provider} repository_name {storekeeper.repository} "
                f"profile {profile} non ha un profilo trovato."
            )

        operation = storekeeper.operation
        try:
            task_args: dict[str, Any] = await repository.parameters(
                **constants | {'provider': profile, 'session': session}
            )
        except Exception as error:
            self.logger.error(
                "Storekeeper: parametri provider non disponibili",
                provider=profile,
                exception=error,
            )
            return flow.error(
                error
            )

        method = getattr(provider, operation, None)
        if not callable(method):
            return flow.error(
                f"Il metodo '{operation}' non è disponibile per il provider {profile}."
            )

        task: asyncio.Task[Any] = asyncio.create_task(
            cast(Callable[..., Coroutine[Any, Any, Any]], method)(
                session=session, storekeeper=task_args
            ),
            name=profile,
        )
        setattr(task, "parameters", task_args)
        return flow.success(task)

    @flow.result()
    async def _prepare_operations(
        self,
        repository: Repository,
        storekeeper: StorekeeperScheme,
        constants: dict[str, Any],
        session: object,
    ) -> flow.FlowResult:
        """Crea i task per tutti i provider compatibili con il repository."""
        tasks: list[asyncio.Task[Any]] = []
        repository_profiles: set[str] = set(repository.location)
        providers: list[persistence.Port] = list(self.persistences)
        operation = storekeeper.operation.upper()
        resource = storekeeper.repository
        policy: dict[str, Any] | None = (
            self.defender.get_policy("persistence") if self.defender else None
        )
        security: Any = (
            policy.get("security", {})
            if isinstance(policy, dict)
            else {}
        )
        if self.defender and not await self.defender.authorized(
            session,
            "persistence",
            action=operation,
            resource=resource,
            request=constants,
        ):
            self.logger.warning(
                "Storekeeper: operazione negata dalla policy",
                operation=operation,
                repository=resource,
            )
            return flow.error("Persistence policy denied the operation")
        if self.defender and security:
            providers = self.defender.authorized_adapters(
                session, "persistence", policy, self.persistences
            )
            if not providers:
                self.logger.warning(
                    "Storekeeper: nessun provider autorizzato",
                    operation=operation,
                    repository=resource,
                )
                return flow.error("Nessun persistence provider autorizzato dalla policy di sicurezza")
        for provider in providers:
            provider_profile = str(provider.config.get('name', '')).casefold()
            if provider_profile not in repository_profiles:
                continue
            try:
                prepared_task: flow.FlowResult = await self._prepare_provider(
                    provider, repository, storekeeper, constants, session
                )
                if not flow.check(prepared_task):
                    for pending in tasks:
                        pending.cancel()
                    return prepared_task
                tasks.append(
                    cast(asyncio.Task[Any], flow.output(prepared_task))
                )
            except Exception as error:
                for pending_task in tasks:
                    pending_task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.logger.error(
                    "Storekeeper: preparazione provider fallita",
                    provider=type(provider).__name__,
                    exception=error,
                )
                return flow.error(error)
        if not tasks:
            self.logger.warning(
                "Storekeeper: nessun provider compatibile",
                operation=operation,
                repository=resource,
            )
            return flow.error(
                f"Nessun provider compatibile per il repository "
                f"'{storekeeper.repository}'. "
                f"Profili richiesti: {sorted(repository_profiles)}."
            )
        return flow.success(tasks)

    @flow.result()
    async def preparation(
        self, session: object, storekeeper: Mapping[str, Any]
    ) -> flow.FlowResult:
        constants = dict(storekeeper)
        scheme_values = {
            key: value
            for key, value in constants.items()
            if key in StorekeeperScheme.SCHEME
        }
        storekeeper_scheme = StorekeeperScheme.from_mapping(scheme_values)

        repository_result: flow.FlowResult = await self._load_repository(
            storekeeper_scheme.repository
        )
        if not flow.check(repository_result):
            return repository_result
        repository: Repository = cast(Repository, flow.output(repository_result))

        preparation: flow.FlowResult = await self._prepare_operations(
            repository, storekeeper_scheme, constants, session
        )
        if not flow.check(preparation):
            return preparation
        return flow.success((repository, flow.output(preparation)))
    
    @flow.result()
    async def _execute(
        self,
        operation: Literal["view", "read", "create", "delete", "update"],
        session: object,
        constants: Mapping[str, Any],
    ) -> flow.FlowResult:
        state = await self.preparation(
            session, dict(constants) | {"operation": operation}
        )
        if not flow.check(state):
            self.logger.warning(
                "Storekeeper: preparazione fallita",
                operation=operation,
                repository=constants.get("repository"),
            )
            return state

        repository, operations = cast(
            tuple[Repository, list[asyncio.Task[Any]]], flow.output(state)
        )
        result = await self.orchestrator.first_completed(
            session,
            operations=operations,
            success=repository.results,
        )
        self.logger.debug(
            "Storekeeper: operazione completata",
            operation=operation,
            repository=constants.get("repository"),
            success=flow.check(result),
        )
        return result

    # overview/view/get
    @flow.result()
    async def overview(
        self,
        session: object,
        **constants: Unpack[StorekeeperSchemeKwargs],
    ) -> flow.FlowResult:
        return await self._execute('view', session, constants)

    # gather/read/get
    @flow.result()
    async def gather(
        self,
        session: object,
        **constants: Unpack[StorekeeperSchemeKwargs],
    ) -> flow.FlowResult:
        return await self._execute('read', session, constants)

    # store/create/put
    @flow.result()
    async def store(
        self,
        session: object,
        **constants: Unpack[StorekeeperSchemeKwargs],
    ) -> flow.FlowResult:
        return await self._execute('create', session, constants)

    # remove/delete
    @flow.result()
    async def remove(
        self,
        session: object,
        **constants: Unpack[StorekeeperSchemeKwargs],
    ) -> flow.FlowResult:
        return await self._execute('delete', session, constants)

    # change/update/patch
    @flow.result()
    async def change(
        self,
        session: object,
        **constants: Unpack[StorekeeperSchemeKwargs],
    ) -> flow.FlowResult:
        return await self._execute('update', session, constants)