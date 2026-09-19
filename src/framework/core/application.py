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
        self._logger = get_logger("application")
        self._managers = managers
        self._stop_event = asyncio.Event()
        self._running_tasks: list[asyncio.Task] = []
        self._session = session
        self._previous_signal_handlers: dict[signal.Signals, Any] = {}
        self._shutdown_started = False

    def _request_shutdown(self, sig: signal.Signals) -> None:
        """Riceve un segnale OS e risveglia il ciclo di vita applicativo."""
        self._logger.info("Segnale di arresto ricevuto", signal=sig.name)
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
                if not flow.is_result(message_result):
                    continue
                if not flow.check(message_result):
                    continue
                message = flow.output(message_result)
                for name, mgr in list(self._loader.get_managers().items()):
                    if hasattr(mgr, "reload"):
                        try:
                            await mgr.reload(self._session, message)
                        except Exception as exc:
                            self._logger.error(
                                "Errore durante reload",
                                exception=exc,
                                manager=name,
                            )
        except asyncio.CancelledError:
            self._logger.info("Worker di messaggistica terminato")

    async def startup(self):
        """Avvia l'applicazione e gestisce i segnali di arresto."""
        self._logger.info("Avvio dei manager del framework")
        if self._loader.kwargs.get("dev"):
            self._running_tasks.append(
                asyncio.create_task(self._message_consumer_worker())
            )

        self._install_signal_handlers()

        for manager in self._managers:
            if not hasattr(manager, "startup"):
                continue
            result = await manager.startup(self._session)
            if flow.is_result(result):
                if not flow.check(result):
                    continue
                result = flow.output(result)
            if not result:
                continue

            coros = result if isinstance(result, list) else [result]
            for c in coros:
                if asyncio.iscoroutine(c) or inspect.isawaitable(c):
                    self._running_tasks.append(asyncio.create_task(c))

        self._logger.info("Framework completamente attivo. In ascolto")
        await self._stop_event.wait()

    async def shutdown(self):
        """Esegue il graceful shutdown di tutti i componenti registrati."""
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._logger.info("Spegnimento controllato dei servizi")
        try:
            for manager in reversed(self._managers):
                if not hasattr(manager, "shutdown"):
                    continue
                result = await manager.shutdown(self._session)
                if flow.is_result(result) and not flow.check(result):
                    self._logger.error(
                        "Shutdown fallito",
                        manager=type(manager).__name__,
                        result=flow.output(result),
                    )
        finally:
            tasks = [task for task in self._running_tasks if not task.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            for sig, handler in self._previous_signal_handlers.items():
                signal.signal(sig, handler)
            self._previous_signal_handlers.clear()

            self._logger.info("Framework spento correttamente")