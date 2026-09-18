import asyncio
import inspect
import signal
from typing import Any

import framework.core.flow as flow

class Application:
    """Gestisce il ciclo di vita dell'applicazione, segnali OS e worker asincroni."""

    def __init__(self, loader: Any, managers: list, session: Any = None):
        self._loader = loader
        self._managers = managers
        self._stop_event = asyncio.Event()
        self._running_tasks: list[asyncio.Task] = []
        self._session = session

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
                            print(f"[!] Errore durante reload in {name}: {exc}")
        except asyncio.CancelledError:
            print("[*] Worker di messaggistica terminato.")

    async def startup(self):
        """Avvia l'applicazione e gestisce i segnali di arresto."""
        print("[*] Avvio dei manager del framework...")
        if self._loader.kwargs.get("dev"):
            self._running_tasks.append(
                asyncio.create_task(self._message_consumer_worker())
            )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop_event.set)
            except NotImplementedError:
                pass

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

        print("[+] Framework completamente attivo. In ascolto...")
        await self._stop_event.wait()

    async def shutdown(self):
        """Esegue il graceful shutdown di tutti i componenti registrati."""
        print("\n[*] Spegnimento controllato dei servizi...")
        for manager in reversed(self._managers):
            if hasattr(manager, "shutdown"):
                result = await manager.shutdown(self._session)
                if flow.is_result(result) and not flow.check(result):
                    print(f"[!] Shutdown fallito per {manager}: {flow.output(result)}")

        for task in self._running_tasks:
            if not task.done():
                task.cancel()

        print("[*] Framework spento correttamente.")