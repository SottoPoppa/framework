# OmniPort — Report di revisione statica

- **Tipo:** code review statica in sola lettura.
- **Esito iniziale:** revisione statica in sola lettura.
- **Follow-up:** import framework-level e `--verify` implementati; test focalizzato del Loader eseguito dopo aver corretto la raccolta della suite.

## Ambito e limiti

L'inventario della workspace contiene 272 file. La revisione ha coperto i percorsi principali di `src/framework/core`, manager, port e service; i percorsi collegati di `src/infrastructure`; controller, policy, repository, modelli e viste applicative; CLI, configurazione e workflow CI. Non è stata letta ogni riga di ogni file né eseguita l'intera suite.

La configurazione versionata abilita TUI, bus e filesystem; gli adapter Starlette e Copilot sono commentati. I finding che li riguardano sono difetti latenti quando quegli adapter vengono attivati, non un'affermazione che siano esposti nell'avvio predefinito.

La diagnostica Pylance iniziale non ha riportato errori. Nel follow-up, `--test src/framework/manager/loader` ha eseguito 4 casi, tutti passati; il Tester ora legge `test_suite` ed `exports` dallo scope runtime, poiché la proiezione pubblica dell'interprete rimuove i callable. Un controllo runtime ha confermato che import diretto e import tramite Loader restituiscono lo stesso modulo. `--verify` è stato eseguito e ha terminato senza startup con exit code `1`, segnalando contract stale/non validi di Messenger, Storekeeper e Authenticator. Non sono state eseguite le suite complete né gli integration test.

## Finding confermati

1. **Risolto nel follow-up del 2026-09-25 — Placeholder Jinja nei repository DSL.** Il messaggio specifico `'session' is undefined` non si riproduceva perché `sessions.dsl` proteggeva il placeholder con `raw`; tuttavia `StrictUndefined` faceva fallire altri repository con template runtime non protetti, come `integration_file.dsl`. `Infrastructure.resource()` ora usa `DeferredUndefined` nel primo render DSL: gli `include` della policy vengono ancora espansi e i placeholder restano disponibili per `Repository.parameters()`. Rimossi i wrapper `raw` da `file.dsl` e `sessions.dsl`; verificato il path finale della sessione tramite Interpreter e Repository.

2. **Alta, con Starlette attivo — Viene montata una sola route.** [mount_route](src/infrastructure/presentation/web/starlette.py#L1132) ritorna dentro il ciclo che visita le route; [start](src/infrastructure/presentation/web/starlette.py#L827) la invoca una sola volta. Le route successive non vengono registrate.

3. **Alta — L'Authenticator confronta un risultato Flow con una forma non implementata.** [authenticator.py](src/framework/manager/authenticator.py#L69) controlla `session_result.get('success')`, ma il runtime espone `flow.Result` con `output` e `is_success` ([flow.py](src/framework/core/flow.py#L317)). Di conseguenza il risultato positivo del provider non viene fuso nella sessione; anche `invalidate()` può uscire prima di cancellare `providers` e `user` ([authenticator.py](src/framework/manager/authenticator.py#L102)).

4. **Alta, con Starlette attivo — Gli handler di login e registrazione usano ancora il vecchio formato Flow.** `signin()` e `signup()` leggono `session['success']` e `session['outputs']` ([starlette.py](src/infrastructure/presentation/web/starlette.py#L905)); il valore restituito dai metodi decorati è invece un `flow.Result`. Le richieste possono terminare con `KeyError`.

5. **Risolto nel follow-up — Import dinamico collocato nel Framework.** Il Tester registra `Loader.import_module` come funzione DSL ([tester.py](src/framework/manager/tester.py#L270)); il Loader delega ora a `Framework.import_module()` ([framework.py](src/framework/core/framework.py)), che usa `importlib.import_module()`. La suite mirata del Loader ha eseguito 4 casi con esito positivo.

6. **Media, con Starlette attivo — Logout e recovery invocano metodi inesistenti.** `signout()` chiama `Defender.terminate` e `signaid()` `Authenticator.reinstate` ([starlette.py](src/infrastructure/presentation/web/starlette.py#L881), [starlette.py](src/infrastructure/presentation/web/starlette.py#L945)). L'Authenticator espone invece `invalidate` e `regenerate` ([authenticator.py](src/framework/manager/authenticator.py#L89), [authenticator.py](src/framework/manager/authenticator.py#L116)).

7. **Media — Il cambio Kanban a “In Progress” può sospendere la chiamata di persistenza.** [kanban.dsl](src/application/controller/kanban.dsl#L42) legge `@session.sid`, mentre la proiezione pura inserita nel contesto dall'[interprete](src/framework/core/interpreter.py#L80) espone il campo `id` definito in [session.py](src/framework/core/session.py#L96).

8. **Media — La chat consulta un nome di nodo non pubblicato dal controller terminal.** [chat.dsl](src/application/controller/chat.dsl#L5) legge `terminal.selected`; il trigger in [terminal.dsl](src/application/controller/terminal.dsl#L4) si chiama `select`. Il compilatore usa il trigger come nome del nodo ([compiler.py](src/framework/core/compiler.py#L109)); il Runner pubblica i risultati sotto il nome del nodo ([runner.py](src/framework/core/runner.py#L330)), quindi il riferimento cross-controller non trova il risultato atteso.

9. **Media — Un nodo DAG con più predecessori può eseguire più volte.** [runner.py](src/framework/core/runner.py#L187) controlla gli stati terminali prima di attendere le dipendenze, ma non ricontrolla lo stato dopo l'attesa e prima dell'esecuzione ([runner.py](src/framework/core/runner.py#L201)). Due predecessori possono quindi avviare lo stesso figlio e duplicarne gli effetti.

10. **Media — `first_completed()` lascia task pendenti dopo un esito fallito.** Il ramo di errore assegna i task non terminati a `operations` e ritorna senza cancellarli ([orchestrator.py](src/framework/manager/orchestrator.py#L156), [orchestrator.py](src/framework/manager/orchestrator.py#L158)). Un provider lento può completare una scrittura dopo che il chiamante ha ricevuto un errore.

11. **Media — Un errore di normalizzazione può essere convertito in successo.** `Repository.results()` restituisce `flow.error()` quando lo schema rifiuta il payload ([factory.py](src/framework/service/factory.py#L161)); il callback di `first_completed()` non ricontrolla il risultato e lo racchiude in `flow.success()` ([orchestrator.py](src/framework/manager/orchestrator.py#L149)).

12. **Media — Le API secondarie dell'Orchestrator non propagano correttamente gli esiti Flow.** `all_completed()` cerca la chiave `success` ([orchestrator.py](src/framework/manager/orchestrator.py#L194)); `chain_completed()` ignora le eccezioni dei task e restituisce comunque successo ([orchestrator.py](src/framework/manager/orchestrator.py#L214), [orchestrator.py](src/framework/manager/orchestrator.py#L218)). I test d'integrazione presenti coprono il caso senza task, non quello con risultati Flow riusciti o falliti.

13. **Risolto nel follow-up — `--verify` termina senza startup.** [public/main.py](public/main.py) delega a `Framework.verify_contracts()` ([framework.py](src/framework/core/framework.py)) e ritorna prima di `app.startup()`; il Loader esegue la discovery strict ([loader.py](src/framework/manager/loader.py)). L'esecuzione ha restituito exit code `1` per contract stale/non validi: `messenger.py` (`Manager.receive`), `storekeeper.py` (`Manager.startup`, `Manager.shutdown`) e `authenticator.py` (`Manager.activate`, `authenticate`, `invalidate`, `regenerate`, `startup`, `shutdown`). La modalità standalone funziona, ma l'intero set di contract non è ancora verde.

14. **Media — Un refresh OAuth fallito può lasciare passare il token scaduto.** [oauth.py](src/infrastructure/authentication/oauth2/oauth.py#L1432) controlla `result is None`, mentre `refresh()` restituisce un Flow error in caso di errore ([oauth.py](src/infrastructure/authentication/oauth2/oauth.py#L1251)). Il codice può quindi proseguire leggendo dalla sessione i token non aggiornati.

15. **Media, con le route interessate montate — Alcune route dichiarano viste non presenti.** La configurazione include, per esempio, `ecommerce.xml` e `auth/login.xml` ([routes.dsl](src/application/policy/presentation/routes.dsl#L4), [routes.dsl](src/application/policy/presentation/routes.dsl#L9)); sotto `src/application/view/page/` sono presenti solo `login.xml`, `chat.xml`, `kanban.xml` e `terminal.xml`.

16. **Bassa — Il parser DSL non decodifica le sequenze escape delle stringhe.** [parser.py](src/framework/core/parser.py#L124) rimuove le virgolette ma non interpreta `\n` o `\"`; le stringhe che usano questi escape conservano i caratteri letterali.

17. **Bassa, se istanziato — `Encefalo()` solleva `TypeError`.** Il costruttore chiama `enumerate()` senza iterable in più punti, a partire da [encefalo.py](src/infrastructure/network/neural/encefalo.py#L118). Non è risultato attivo nella configurazione esaminata.

## Rischi condizionati

- **Path traversal e lettura non autorizzata di file:** il repository `file` inserisce `filter.eq.filename` nel percorso ([file.dsl](src/application/repository/file.dsl#L5)); l'adapter filesystem concatena i percorsi senza confinamento canonico ([filesystem.py](src/infrastructure/persistence/filesystem/filesystem.py#L117)) e la policy contiene un allow per la lettura della risorsa `file` ([persistence.dsl](src/application/policy/persistence/persistence.dsl#L25)). Il rischio si attiva se un input non fidato può invocare quell'operazione.
- **Esecuzione di comandi sul sistema:** con il terminale Copilot abilitato, il codice approva automaticamente le richieste di permesso ([copilot.py](src/infrastructure/message/agent/copilot.py#L263)) e usa una shell ([copilot.py](src/infrastructure/message/agent/copilot.py#L389)). La directory iniziale e la blacklist non sono una sandbox; l'impatto dipende dalla raggiungibilità del tool da prompt o task non fidati. L'opzione è commentata nel `pyproject.toml` corrente.
- **Configurazione di sicurezza di esempio:** il `pyproject.toml` versiona una chiave con valore di sviluppo ([pyproject.toml](pyproject.toml#L14)); la policy presentation disabilita TLS e CSRF ([presentation.dsl](src/application/policy/presentation/presentation.dsl#L10), [presentation.dsl](src/application/policy/presentation/presentation.dsl#L11)) e la policy authentication non richiede password hashing, MFA o token rotation ([authentication.dsl](src/application/policy/authentication/authentication.dsl#L26)). Non usare questi valori come configurazione di produzione.
- **Dati della sessione nel markup:** [login.xml](src/application/view/page/login.xml#L3) renderizza l'intero oggetto `session`. Se contiene token o altri dati privati, questi diventano visibili nel markup. La route è attualmente condizionata anche dal problema di montaggio delle route.
- **Argomenti conservati nei risultati Flow:** `@flow.result()` registra sempre gli argomenti e le keyword argument in `Result.input`. Se il risultato o le sue `transactions` vengono serializzati o esposti, possono includere sessioni, token o altri dati sensibili. La review non ha verificato un'esposizione automatica di questo campo.

## Decisione applicata

La collisione iniziale è stata risolta: `GET_INDEX` resta su `/` e `GET_KANBAN` usa `/kanban` ([routes.dsl](src/application/policy/presentation/routes.dsl#L2), [routes.dsl](src/application/policy/presentation/routes.dsl#L25)). Il bootstrap e il matching verificano che entrambe le viste siano raggiungibili.

## Disallineamenti documentali

Le guide descrivevano un Flow-dizionario con `success`/`outputs`, mentre il runtime usa `flow.Result`; inoltre la sessione espone `id`, non `sid`. Questi riferimenti sono stati allineati. Nel follow-up anche `import()` e `--verify` sono stati corretti; la verifica strict resta bloccata dai contract indicati nel finding 13.