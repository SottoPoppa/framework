import asyncio
import inspect
from typing import List, Dict, Any, Callable
import re
import traceback

import framework.core.interpreter as interpreter
import framework.core.flow as flow
import framework.service.scheme as scheme
from framework.service.diagnostic import get_logger
import framework.manager.messenger as messenger
import framework.port.manager as manager

class Manager(manager.Port):
    _session_exempt_methods = {"_select_provider"}
    def __init__(self, messenger: messenger.Manager,**constants):
        self.defender = constants.get('defender')
        self.messenger = constants.get('messenger')
        self.interpreter = interpreter.Interpreter(scheme.schemes)
        self.logger = get_logger("orchestrator")
        self._background_tasks: set[asyncio.Task] = set()

    # ── INTERPRETER ────────────────────────────────────────────────────────────────

    async def stop(self, session):
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.interpreter.stop()
    
    async def start(self, session):
        
        '''await self.interpreter.start()
        codice_dsl = """
        moltiplicatore: 2;

        // Task 1: Genera un numero casuale tra 1 e 10 ogni secondo
        //genera_numero(schedule: 1) -> print("sds");

        // Task 2: Dipende automaticamente da 'genera_numero' tramite il costrutto @
        // Prende il valore, lo passa alla funzione 'print' tramite la pipe |>
        stampa_valore(schedule: 1) -> print(10) ;
        """

        filename = "mio_workflow.dsl"
        session_id = "sessione_utente_42"

        try:
            # 4. Registra il file DSL
            
            # L'interprete esegue il parsing dell'AST e istruisce il DAG sulle dipendenze e i timer
            await self.interpreter.load_file(filename, codice_dsl)
            async with self.interpreter.open_session(env={"input": "dati_A"}) as s:
                risultati = await s.run(filename)
                print(risultati)
            # self.interpreter.open_session({},session_id)
            # 5. Crea una sessione persistente per l'utente
            # Puoi passare un dizionario 'env' con variabili di stato iniziali

            session = self.interpreter.open_session(
                env={"user_id": "asds"},
                sid="sadsad"          # sid esplicito per ritrovare la sessione
            )

            # prima richiesta
            r1 = await session.run(filename, env={"step": "login"})

            # aggiorna il contesto senza rieseguire tutto
            session.update("user.authenticated", True)
            session.update("user.role", "admin")

            # seconda richiesta — il contesto aggiornato è già disponibile
            r2 = await session.run(filename, env={"step": "dashboard"})

            # triggera un nodo specifico manualmente
            await session.emit(filename, "notifica", value={"msg": "Benvenuto"})

            # aspetta che un nodo specifico finisca
            await session.wait(filename, "notifica")

            # leggi il contesto corrente
            print(session.context)


        except Exception as e:
            print(f"Errore durante l'esecuzione: {e}")'''

    async def load_file(self, session, name, source):
        return await self.interpreter.load_file(name, source)

    def _runtime_session(self, session, env=None):
        if callable(getattr(session, "run", None)) and callable(
            getattr(session, "emit", None)
        ):
            return session

        session_data = getattr(session, "session_data", session)
        session_id = (
            session_data.get("id")
            if isinstance(session_data, dict)
            else getattr(session_data, "id", session_data)
        )
        state = session_data.to_dict() if callable(
            getattr(session_data, "to_dict", None)
        ) else session_data if isinstance(session_data, dict) else None
        return self.interpreter.open_session(
            env=env,
            sid=session_id,
            state=state,
        )

    async def open_session(self, session, env=None):
        return self._runtime_session(session, env)

    async def run(self, session, file, env=None):
        return await self._runtime_session(session).run(file, env or {})
        
    # ── PROVIDER ────────────────────────────────────────────────────────────────

    def _select_provider(self, requirements: Dict[str, Any]) -> Any:
        """Seleziona il provider che meglio soddisfa i requirements."""
        if not self.providers:
            return None
            
        if not requirements:
            return self.providers[-1] # Default behavior (last one) or first? Original code used -1.
            
        best_provider = None
        best_score = -1
        
        for provider in self.providers:
            score = 0
            capabilities = getattr(provider, 'capabilities', {})
            
            # Calcola score basato su requirements e capabilities
            # Esempio semplice: +1 per ogni match esatto
            match = True
            for req_key, req_val in requirements.items():
                cap_val = capabilities.get(req_key)
                if cap_val != req_val:
                    match = False
                    break
            
            if match:
                # Se tutti i requirements sono soddisfatti, questo è un candidato.
                # Potremmo avere logiche più complesse di scoring.
                return provider
                
        # Se nessun match esatto, ritorna l'ultimo (fallback) o None?
        # Per ora fallback all'ultimo come comportamento di default
        return self.providers[-1]

    # ── API ────────────────────────────────────────────────────────────────

    @flow.result()
    async def first_completed(self, session, **constants):
        """Attende il primo task completato e restituisce il suo risultato."""
        operations = [
            asyncio.ensure_future(operation)
            for operation in constants.get("operations", [])
        ]
        if not operations:
            return None
        errors = []
        pending = set(operations)
        try:
            while pending:
                finished, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for operation in operations:
                    if operation not in finished:
                        continue
                    try:
                        transaction = operation.result()
                    except asyncio.CancelledError:
                        continue
                    except Exception as exc:
                        errors.append(exc)
                        self.logger.error(
                            "Orchestrator: operazione terminata con eccezione",
                            exception=exc,
                        )
                        continue

                    if flow.is_result(transaction):
                        if not flow.check(transaction):
                            error = flow.output(transaction)
                            errors.append(error)
                            self.logger.error(
                                "Orchestrator: operazione fallita",
                                error=error,
                            )
                            continue
                        transaction = flow.output(transaction)

                    success = constants.get("success")
                    if callable(success):
                        try:
                            transaction = await success(
                                transaction=transaction,
                                profile=getattr(operation, "get_name", lambda: None)(),
                            )
                        except Exception as exc:
                            errors.append(exc)
                            self.logger.error(
                                "Orchestrator: trasformazione del risultato fallita",
                                exception=exc,
                            )
                            continue
                        if flow.is_result(transaction):
                            if not flow.check(transaction):
                                error = flow.output(transaction)
                                errors.append(error)
                                self.logger.error(
                                    "Orchestrator: trasformazione del risultato fallita",
                                    error=error,
                                )
                                continue
                            transaction = flow.output(transaction)

                    return flow.success(transaction)

            error_msg = errors or "Nessuna transazione valida completata"
            self.logger.warning(
                "Orchestrator: first_completed senza risultato valido",
                errors=error_msg,
            )
            return flow.error(error_msg)
        finally:
            for task in operations:
                if not task.done():
                    task.cancel()
            if operations:
                await asyncio.gather(*operations, return_exceptions=True)

    @flow.result()
    async def all_completed(self, session, **constants) -> Dict[str, Any]:
        tasks: List[asyncio.Future] = constants.get('tasks', [])
    
        results = await asyncio.gather(*tasks, return_exceptions=True)
        detailed_errors = []
        for result in results:
            if isinstance(result, BaseException):
                self.logger.error(
                    "Orchestrator: task fallito",
                    exception=result,
                )
                error_trace = traceback.format_exception(type(result), result, result.__traceback__)
                detailed_errors.append("".join(error_trace))
                continue
            if flow.is_result(result):
                if not flow.check(result):
                    error = flow.output(result)
                    detailed_errors.append(error)
                    self.logger.error(
                        "Orchestrator: task Flow fallito",
                        error=error,
                    )
                continue
            if isinstance(result, dict) and result.get("success") is False:
                detailed_errors.append(result.get("error", result))

        if detailed_errors:
            self.logger.warning("Orchestrator: all_completed fallito", tasks=len(tasks))
            return flow.error(detailed_errors)
        
        return flow.success({"results": results})

    @flow.result()
    async def chain_completed(self, session, **constants) -> Dict[str, Any]:
        """Esegue i task in sequenza, aspettando il completamento di ciascuno prima di passare al successivo."""
        tasks = constants.get('tasks', [])
        results = []
        for task in tasks:
            try:
                result = await task(**constants)
            except Exception as exc:
                self.logger.error(
                    "Orchestrator: chain_completed fallito",
                    exception=exc,
                )
                return flow.error(exc)

            if flow.is_result(result):
                if not flow.check(result):
                    self.logger.error(
                        "Orchestrator: task sequenziale fallito",
                        error=flow.output(result),
                    )
                    return result
                result = flow.output(result)
            elif isinstance(result, dict) and result.get("success") is False:
                self.logger.error(
                    "Orchestrator: task sequenziale fallito",
                    error=result.get("error", result),
                )
                return flow.error(result.get("error", result))
            results.append(result)

        return flow.success({"state": True, "result": results, "error": None})

    @flow.result()
    async def together_completed(self, session, **constants) -> Dict[str, Any]:
        """Esegue tutti i task contemporaneamente senza attendere il completamento di tutti."""
        tasks = constants.get('tasks', [])
        try:
            for task in tasks:
                awaitable = task(**constants) if callable(task) else task
                if not inspect.isawaitable(awaitable):
                    raise TypeError(f"Task non awaitable: {task!r}")
                background = asyncio.ensure_future(awaitable)
                self._background_tasks.add(background)
                background.add_done_callback(self._background_completed)
            return flow.success({"state": True, "result": "Tasks avviati in background", "error": None})

        except Exception as e:
            self.logger.error("Orchestrator: together_completed fallito", exception=e)
            return flow.error(e)

    def _background_completed(self, task: asyncio.Task) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception as exc:
            self.logger.error(
                "Orchestrator: task in background terminato con eccezione",
                exception=exc,
            )
            return
        if flow.is_result(result) and not flow.check(result):
            self.logger.error(
                "Orchestrator: task in background fallito",
                error=flow.output(result),
            )