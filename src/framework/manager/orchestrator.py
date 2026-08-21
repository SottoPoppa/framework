import asyncio
from typing import List, Dict, Any, Callable
import re
import traceback

import framework.service.language as language
import framework.service.flow as flow
import framework.service.scheme as scheme
import framework.manager.messenger as messenger
import framework.port.manager as manager

class Manager(manager.Port):
    _session_exempt_methods = {"_select_provider"}
    def __init__(self, messenger: messenger.Manager,**constants):
        self.defender = constants.get('defender')
        self.messenger = constants.get('messenger')
        self.interpreter = language.Interpreter(scheme.schemes)

    # ── INTERPRETER ────────────────────────────────────────────────────────────────

    async def stop(self, session):
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

    async def add_file(self, session, name, source):
        return await self.interpreter.add_file(name, source)

    async def create_session(self, session, env={}):
        return await self.interpreter.session_create(session, env|self.language.DSL_FUNCTIONS)

    async def run_session(self, session, file, env={}):
        return await self.interpreter.run_session(session, file, env|self.language.DSL_FUNCTIONS)
        
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

    @flow.result(safe_kwargs=True)
    async def first_completed(self, session, **constants):
        """Attende il primo task completato e restituisce il suo risultato."""
        operations = constants.get('operations', [])
        #await self.messenger.post(domain='debug',message="⏳ Attesa della prima operazione completata...")

        while operations:
            finished, unfinished = await asyncio.wait(operations, return_when=asyncio.FIRST_COMPLETED)

            for operation in finished:
                transaction = operation.result()
                if flow.check(transaction):
                    # framework_log("DEBUG", f"Transazione completata: {type(transaction)}", emoji="💼")
                    if 'success' in constants:
                        transaction = await constants['success'](transaction=transaction,profile=operation.get_name())
                    for task in unfinished:
                        task.cancel()
                    return flow.success(flow.output(transaction))

                operations = unfinished

            error_msg = "⚠️ Nessuna transazione valida completata"
            #await messenger.post(domain='debug',message=error_msg)
            return flow.error(error_msg)

    @flow.result(safe_kwargs=True)
    async def all_completed(self, session, **constants) -> Dict[str, Any]:
        tasks: List[asyncio.Future] = constants.get('tasks', [])
    
        # Lista per raccogliere i dettagli degli errori da ogni task
        detailed_errors = []
        
        # return_exceptions=True: le eccezioni sono restituite come risultati
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 1. Analisi dei Risultati Dettagliata
        for result in results:
            if isinstance(result, Exception):
                
                # Questa funzione stampa il traceback completo sul tuo log/console
                traceback.print_exception(type(result), result, result.__traceback__)
                
                # Un task è fallito. Registra il traceback completo.
                
                # Ottieni il traceback completo (come stringa)
                error_trace = traceback.format_exception(type(result), result, result.__traceback__)
                full_error_log = "".join(error_trace)
                
                # Aggiungi il dettaglio all'elenco degli errori
                detailed_errors.append(full_error_log)

        
        # Se ci sono errori dettagliati, il risultato complessivo è un fallimento logico
        if any(result.get('success', False) is not True for result in results):
            return {"success": False, "results": results, "errors": detailed_errors}
        
        return {"success": True, "results": results}

    @flow.result(safe_kwargs=True)
    async def chain_completed(self, session, **constants) -> Dict[str, Any]:
        """Esegue i task in sequenza, aspettando il completamento di ciascuno prima di passare al successivo."""
        tasks = constants.get('tasks', [])
        results = []

        #await self.messenger.post(domain='debug',message="🔄 Avvio esecuzione sequenziale delle operazioni...")

        try:
            for task in tasks:
                try:
                    result = await task(**constants)
                    results.append(result)
                    #await messenger.post(domain='debug', message=f"✅ Task completato: {result}")
                except Exception as e:
                    #await messenger.post(domain='debug', message=f"❌ Errore nel task {task}: {e}")
                    pass

            return {"state": True, "result": results, "error": None}

        except Exception as e:
            error_msg = f"❌ Errore in chain_completed: {str(e)}"
            #await messenger.post(domain='debug', message=error_msg)
            return {"state": False, "result": None, "error": error_msg}

    @flow.result(safe_kwargs=True)
    async def together_completed(self, session, **constants) -> Dict[str, Any]:
        """Esegue tutti i task contemporaneamente senza attendere il completamento di tutti."""
        tasks = constants.get('tasks', [])

        #await messenger.post(domain='debug', message="🚀 Avvio esecuzione simultanea delle operazioni...")

        try:
            for task in tasks:
                asyncio.create_task(task)

            #await messenger.post(domain='debug', message="✅ Tutti i task sono stati avviati in background.")
            return {"state": True, "result": "Tasks avviati in background", "error": None}

        except Exception as e:
            error_msg = f"❌ Errore in together_completed: {str(e)}"
            #await messenger.post(domain='debug', message=error_msg)
            return {"state": False, "result": None, "error": error_msg}