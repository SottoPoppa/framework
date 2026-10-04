import asyncio
import inspect
import signal
from typing import Any, cast

import framework.core.flow as flow

class Application:
    """Gestisce il ciclo di vita dell'applicazione, segnali OS e worker asincroni."""

    def __init__(
        self, loader: Any, managers: list[Any], session: Any = None
    ) -> None:
        self._loader = loader
        self._logger = loader.framework.get_logger("application")
        self._managers = managers
        self._stop_event = asyncio.Event()
        self._running_tasks: list[asyncio.Future[Any]] = []
        self._session = session
        self._previous_signal_handlers: dict[signal.Signals, Any] = {}
        self._signal_loop: asyncio.AbstractEventLoop | None = None
        self._loop_signal_handlers: set[signal.Signals] = set()
        self._shutdown_started = False
        self._shutdown_result: flow.Result[Any, Any] | None = None
        self._background_errors: list[BaseException] = []

    def _request_shutdown(self, sig: signal.Signals) -> None:
        """Riceve un segnale OS e risveglia il ciclo di vita applicativo."""
        self._logger.info("Segnale di arresto ricevuto", signal=sig.name)
        self._stop_event.set()

    def _handle_os_signal(self, signum: int, _frame: Any) -> None:
        loop = self._signal_loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(
                self._request_shutdown,
                signal.Signals(signum),
            )

    def _handle_task_completion(self, task: asyncio.Future[Any]) -> None:
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._background_errors.append(exception)
            self._logger.error("Task applicativo terminato con errore", exception=exception)
            self._stop_event.set()
            return

        result = task.result()
        if flow.is_result(result) and not flow.check(result):
            error = flow.output(result)
            task_error = (
                error if isinstance(error, BaseException) else flow.FlowError(error)
            )
            self._background_errors.append(task_error)
            self._logger.error("Task applicativo terminato con Failure", error=error)
            self._stop_event.set()

    def _install_signal_handlers(self) -> None:
        """Installa i segnali dopo il wiring, quando i manager hanno finito lo startup."""
        loop = asyncio.get_running_loop()
        self._signal_loop = loop
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                if sig not in self._previous_signal_handlers:
                    self._previous_signal_handlers[sig] = signal.getsignal(sig)

                loop.add_signal_handler(sig, self._request_shutdown, sig)
                self._loop_signal_handlers.add(sig)
                self._logger.debug("Signal handler installato", signal=sig.name)
            except (NotImplementedError, RuntimeError, ValueError, OSError):
                try:
                    signal.signal(sig, self._handle_os_signal)
                    self._logger.debug("Signal handler installato", signal=sig.name)
                except (NotImplementedError, RuntimeError, ValueError, OSError) as fallback_exc:
                    self._logger.warning(
                        "Impossibile installare il signal handler",
                        signal=sig.name,
                        exception=fallback_exc,
                    )

    async def _message_consumer_worker(self) -> None:
        """Worker in background per la gestione degli eventi di reload."""
        try:
            while not self._stop_event.is_set():
                messenger = self._loader.get_managers().get("messenger")
                if messenger is None:
                    await asyncio.sleep(0.2)
                    continue

                message_result = await messenger.receive(self._session, domain="event")
                if flow.is_result(message_result) and not flow.check(message_result):
                    self._logger.error(
                        "Ricezione messaggio fallita",
                        error=flow.output(message_result),
                    )
                    await asyncio.sleep(0.2)
                    continue

                message = flow.output(message_result)
                if message is None:
                    await asyncio.sleep(0.2)
                    continue

                for name, mgr in list(self._loader.get_managers().items()):
                    if not hasattr(mgr, "reload"):
                        continue
                    try:
                        result = await mgr.reload(self._session, message)
                        if flow.is_result(result) and not flow.check(result):
                            self._logger.error(
                                "Errore durante reload",
                                manager=name,
                                error=flow.output(result),
                            )
                    except Exception as exc:
                        self._logger.error(
                            "Errore durante reload",
                            exception=exc,
                            manager=name,
                        )
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self._logger.info("Worker di messaggistica terminato")

    async def startup(self) -> None:
        """Avvia l'applicazione e gestisce i segnali di arresto."""
        self._logger.info("Avvio dei manager del framework")
        if self._loader.kwargs.get("dev"):
            message_task = asyncio.create_task(
                self._message_consumer_worker(),
                name="message-consumer",
            )
            self._running_tasks.append(message_task)
            self._logger.debug(
                "Task indipendente avviato",
                task=message_task.get_name(),
            )

        self._install_signal_handlers()

        for manager in self._managers:
            if not hasattr(manager, "startup"):
                continue
            result = await manager.startup(self._session)
            if flow.is_result(result):
                if not flow.check(result):
                    self._logger.error(
                        "Avvio del manager fallito",
                        manager=type(manager).__name__,
                        error=flow.output(result),
                    )
                    flow.unwrap(result)
                result = flow.output(result)
            if not result:
                continue

            coros: list[Any] = (
                list(cast(list[Any] | tuple[Any, ...], result))
                if isinstance(result, (list, tuple))
                else [result]
            )
            for c in coros:
                if asyncio.iscoroutine(c) or inspect.isawaitable(c):
                    task_name = f"manager-{type(manager).__name__}"
                    task = asyncio.ensure_future(c)
                    set_name = getattr(task, "set_name", None)
                    if callable(set_name):
                        set_name(task_name)
                    task.add_done_callback(self._handle_task_completion)
                    self._running_tasks.append(task)
                    self._logger.debug(
                        "Task indipendente avviato",
                        task=task_name,
                    )

        self._logger.info("Framework runtime avviato. In ascolto")
        await self._stop_event.wait()
        if self._background_errors:
            raise self._background_errors[0]

    async def shutdown(self) -> flow.Result[Any, Any]:
        """Esegue il graceful shutdown di tutti i componenti registrati."""
        if self._shutdown_started:
            return (
                self._shutdown_result
                if self._shutdown_result is not None
                else flow.success(None)
            )
        self._shutdown_started = True
        self._logger.info("Spegnimento controllato dei servizi")
        errors: list[BaseException] = []
        try:
            for manager in reversed(self._managers):
                if not hasattr(manager, "shutdown"):
                    continue
                try:
                    result = await manager.shutdown(self._session)
                except Exception as exc:
                    errors.append(exc)
                    self._logger.error(
                        "Shutdown fallito",
                        manager=type(manager).__name__,
                        exception=exc,
                    )
                    continue
                if flow.is_result(result) and not flow.check(result):
                    error = flow.output(result)
                    errors.append(error)
                    self._logger.error(
                        "Shutdown fallito",
                        manager=type(manager).__name__,
                        result=error,
                    )
        finally:
            tasks = [task for task in self._running_tasks if not task.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                task_results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in task_results:
                    if isinstance(result, BaseException) and not isinstance(
                        result, asyncio.CancelledError
                    ):
                        errors.append(result)
                        self._logger.error(
                            "Task applicativo fallito durante lo shutdown",
                            exception=result,
                        )

            for sig, handler in self._previous_signal_handlers.items():
                if self._signal_loop is not None and sig in self._loop_signal_handlers:
                    try:
                        self._signal_loop.remove_signal_handler(sig)
                    except Exception as exc:
                        errors.append(exc)
                        self._logger.error(
                            "Rimozione del signal handler fallita",
                            signal=sig.name,
                            exception=exc,
                        )
                try:
                    signal.signal(sig, handler)
                except Exception as exc:
                    errors.append(exc)
                    self._logger.error(
                        "Ripristino del signal handler fallito",
                        signal=sig.name,
                        exception=exc,
                    )
            self._previous_signal_handlers.clear()
            self._loop_signal_handlers.clear()
            self._signal_loop = None

            if errors:
                self._logger.error("Framework spento con errori", errors=errors)
                self._shutdown_result = flow.error(errors)
            else:
                self._logger.info("Framework spento correttamente")
                self._shutdown_result = flow.success(None)

        return self._shutdown_result