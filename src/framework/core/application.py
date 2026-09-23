import asyncio
import inspect
import signal
from typing import Any

import framework.core.flow as flow
from framework.service.diagnostic import get_logger

class Application:
    """Gestisce il ciclo di vita dell'applicazione, segnali OS e worker asincroni."""

    def __init__(self, loader: Any, managers: list, session: Any = None):
        self._loader = loader
        self._logger = loader.framework.get_logger("application")
        self._managers = managers
        self._stop_event = asyncio.Event()
        self._running_tasks: list[asyncio.Task] = []
        self._session = session
        self._previous_signal_handlers: dict[signal.Signals, Any] = {}
        self._shutdown_started = False
        self._shutdown_result: flow.Result | None = None
        self._background_errors: list[BaseException] = []

    def _request_shutdown(self, sig: signal.Signals) -> None:
        """Riceve un segnale OS e risveglia il ciclo di vita applicativo."""
        self._logger.info("Segnale di arresto ricevuto", signal=sig.name)
        self._stop_event.set()

    def _handle_task_completion(self, task: asyncio.Task) -> None:
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
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                if sig not in self._previous_signal_handlers:
                    self._previous_signal_handlers[sig] = signal.getsignal(sig)

                def handle_signal(_signum, _frame, current_signal=sig):
                    self._request_shutdown(current_signal)

                signal.signal(sig, handle_signal)
                self._logger.debug("Signal handler installato", signal=sig.name)
            except (NotImplementedError, RuntimeError, ValueError, OSError) as exc:
                self._logger.warning(
                    "Impossibile installare il signal handler",
                    signal=sig.name,
                    exception=exc,
                )

    async def _message_consumer_worker(self):
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

    async def startup(self):
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

            coros = result if isinstance(result, (list, tuple)) else [result]
            for c in coros:
                if asyncio.iscoroutine(c) or inspect.isawaitable(c):
                    task = asyncio.create_task(c, name=f"manager-{type(manager).__name__}")
                    task.add_done_callback(self._handle_task_completion)
                    self._running_tasks.append(task)
                    self._logger.debug(
                        "Task indipendente avviato",
                        task=task.get_name(),
                    )

        self._logger.info("Framework runtime avviato. In ascolto")
        await self._stop_event.wait()
        if self._background_errors:
            raise self._background_errors[0]

    async def shutdown(self):
        """Esegue il graceful shutdown di tutti i componenti registrati."""
        if self._shutdown_started:
            return (
                self._shutdown_result
                if self._shutdown_result is not None
                else flow.success(None)
            )
        self._shutdown_started = True
        self._logger.info("Spegnimento controllato dei servizi")
        errors = []
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

            if errors:
                self._logger.error("Framework spento con errori", errors=errors)
                self._shutdown_result = flow.error(errors)
            else:
                self._logger.info("Framework spento correttamente")
                self._shutdown_result = flow.success(None)

        return self._shutdown_result