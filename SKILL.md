# OmniPort Framework — SKILL.md

Questo documento istruisce qualunque LLM (agente app-builder o assistente per lo sviluppo del framework stesso) su come scrivere codice per OmniPort in modo sicuro, verificabile e coerente con le convenzioni del progetto. È la fonte di verità: in caso di dubbio, questo file vince su intuizioni generiche di "buon senso" da altri progetti.

---

## 🏗️ Principi Architetturali

OmniPort segue una **Hexagonal Architecture** (Ports & Adapters): la logica di business è isolata dall'infrastruttura, secondo il pattern **MVC — Model / View / Controller**, con i controller DSL caricati dinamicamente.

1. **Core (`src/application/`)**: logica di dominio pura, definizioni UI, modelli dati. Zona di modifica primaria.
2. **Infrastructure (`src/infrastructure/`)**: implementazioni concrete (adapter web, persistenza, sensori, autenticazione...). Modificabile solo per aggiungere/correggere un adapter specifico, mai per cambiare il contratto della Port che implementa.
3. **Framework (`src/framework/`)**: il kernel — loader, container DI, manager. Modificabile **solo** in "Framework Maintenance Mode" (vedi sotto), mai in modalità app-building.

---

## 🛑 Regole di Scope — due modalità operative

Non tutti gli agenti che leggono questo file hanno lo stesso livello di fiducia. Prima di scrivere una riga di codice, stabilisci in quale modalità stai operando.

### Modalità 1 — App Builder (default, per chi costruisce/modifica un'app sopra il framework)
Sei **autorizzato SOLO** a:
1. Creare o modificare file dentro `src/application/` e sue sottocartelle.
2. Modificare `pyproject.toml` per configurare il progetto o attivare/disattivare adapter.

Sei **vietato** a toccare `src/framework/` o `src/infrastructure/` in questa modalità, anche se pensi di aver trovato un bug lì — segnalalo, non correggerlo.

### Modalità 2 — Framework Maintenance (solo su autorizzazione esplicita dell'umano, per file specifici)
Attivabile **solo** quando l'umano indica esplicitamente quale file di `src/framework/` o `src/infrastructure/` sei autorizzato a modificare (es. "lavora solo su `src/framework/manager/tester.py`"). In questa modalità:
- Lavori su **un solo file/manager per volta**. Non toccare altri componenti "già che ci sei", nemmeno per fix banali — segnalali e basta.
- Segui obbligatoriamente la **Disciplina Test-First e Contract** descritta sotto.
- Non hai comunque il permesso di introdurre nuovi pattern architetturali (nuove classi base, nuovi meccanismi di DI, ecc.) senza che sia l'umano a richiederlo esplicitamente.

---

## 🧪 Disciplina Test-First e Contract (obbligatoria in Modalità 2, consigliata sempre)

Il framework ha già il meccanismo per impedire che codice non verificato arrivi in produzione: **usalo, non aggirarlo.**

1. **Prima di modificare un manager/componente, scrivi o aggiorna il suo `*.test.dsl`** nella stessa cartella (es. `src/framework/manager/tester.test.dsl` per `tester.py`). Il test è la specifica: se non riesci a scrivere un test per il comportamento che stai per aggiungere, non hai ancora capito bene cosa deve fare.
2. **Implementa il fix/feature.**
3. **Verifica con il filtro dedicato**, non con l'intera suite:
   ```bash
   python3 public/main.py --test managers/<nome_manager>
   ```
   (filtri disponibili: `managers`, `ports`, `services`, `infrastructure`, oppure un path diretto)
4. Se tutti gli export dichiarati sono testati con successo, `Contract.record_tested` rigenera il contract JSON accanto al file. Il contract contiene l'API dichiarata e gli hash di test/produzione; non aggiungere metadati variabili come timestamp o commit Git, perché producono diff inutili a ogni generazione.
5. **Non usare mai `--skip-verify` come soluzione a un test che fallisce.** È un flag di emergenza per l'umano, non un modo per far "sparire" un errore che hai introdotto. Se un test fallisce dopo una tua modifica, il problema è nella modifica, non nel test.
6. **Un manager modificato = un commit = un contract aggiornato.** Non accumulare modifiche a più componenti in un solo commit: rende impossibile capire quale hash corrisponde a quale comportamento verificato.

### Contratto Flow per Manager e Adapter

I metodi pubblici che attraversano un confine tra Manager, Port e Adapter devono
restituire sempre un risultato Flow. Il formato comune è:

```python
{
    "success": True | False,
    "outputs": valore | None,
    "errors": [],
    "action": "nome_metodo",
    "component": "modulo.python",
    "history": []
}
```

Regole operative:

1. Usa `@flow.result()` sui metodi pubblici dei Manager e sulle API pubbliche degli Adapter.
2. Se un Port definisce una mappa `_method_decorators`, applicala automaticamente in `__init_subclass__` agli override degli Adapter concreti.
3. Usa `flow.output(result)` per estrarre il valore contenuto in `outputs`; non accedere direttamente al valore come se il risultato fosse già il payload.
4. Propaga un risultato fallito senza trasformarlo in un valore normale: `if not result.get("success"): return result`.
5. Non decorare automaticamente ogni helper privato o funzione pura. Gli helper asincroni interni vanno decorati solo se rappresentano davvero un confine di pipeline.
6. Non annidare risultati Flow. Se un metodo decorato riceve o restituisce già un Flow, deve mantenerne il contenuto e aggiungere soltanto la traccia.
7. Per aggiungere provenienza usa `flow.trace(...)`, che aggiorna `action`, `component`, `pipeline`, `node` e `history` senza creare un secondo risultato.

Esempio di chiamata corretta:

```python
result = await manager.operation(session, **constants)
if not result["success"]:
    return result
value = flow.output(result)
```

Quando si aggiunge `@flow.result()` a un metodo esistente, cerca e aggiorna
anche tutti i chiamanti che usavano direttamente il valore restituito. Questa
verifica è obbligatoria per lifecycle, sessioni e operazioni di I/O.

---

## 🚫 Anti-pattern vietati

Questi pattern sono stati trovati nel codice esistente durante una review e sono **esplicitamente vietati** da qui in avanti. Se li incontri in un file che stai già autorizzato a toccare, correggili; se li incontri altrove, segnalali senza correggerli (rispetta lo scope).

1. **Metodi "versione 2"** (`post2`, `install2`, `foo_v2`...): mai lasciare una seconda versione di un metodo accanto all'originale. O sostituisci l'originale con la logica corretta, o elimini la versione superata. Un metodo `_2` permanente è debito tecnico, non un'opzione valida.
2. **Init fantasma:** mai scrivere logica di inizializzazione reale dentro una stringa triple-quote (`'''...'''`) lasciata inerte in `__init__` o altrove. O il codice viene eseguito per davvero (assegnazioni dirette su `self.`), o va rimosso. Prima di consegnare un file, verifica che ogni `self.<attributo>` usato altrove nella classe sia effettivamente assegnato in un punto del codice che viene eseguito.
3. **Naming misto italiano/inglese negli identificatori:** i nomi di classi, metodi, funzioni e variabili sono **sempre in inglese**. L'italiano è benvenuto in commenti, docstring e messaggi di log/errore mostrati all'utente, mai negli identificatori di codice.
4. **Sinonimi CRUD non decisi:** per operazioni di persistenza usa sempre `create` / `read` / `update` / `delete` come verbi di base. Se un'operazione ha davvero una semantica diversa da un CRUD standard (es. un riepilogo leggero vs una lettura completa), dalle un nome esplicito che comunichi la differenza (es. `summary()` vs `read()`), non un sinonimo generico lasciato ambiguo.
5. **Prefissi incoerenti su un gruppo di metodi legati alla stessa risorsa:** se un manager gestisce il ciclo di vita di una sessione, tutti i metodi relativi condividono lo stesso prefisso — `session_create`, `session_get`, `session_activate`, `session_terminate`, `session_reinstate` — non un mix di nomi con e senza prefisso.
6. **Verbi generici senza contesto** (`resolve`, `compute`, `check`, `process`): il nome del metodo deve dire cosa risolve/calcola/controlla. Preferisci `resolve_route()` a `resolve()`, `validate_components()` a `check()`.
7. **Debug lasciato nel codice di produzione:** niente `raise Exception(f"[debug] ...")`, `print()` di debug commentati a metà, o branch morti lasciati "per sicurezza". Se serve loggare, usa `framework.service.diagnostic`.

---

## 🔁 Metodo operativo di sviluppo (per sessioni di lavoro con un LLM)

1. **Un solo target per sessione.** Un manager, un adapter, un controller — mai "sistema un po' di cose sparse".
2. **Contesto minimo e mirato:** fornisci all'LLM solo il file target, il suo `*.test.dsl` (se esiste) e i moduli da cui dipende direttamente (import diretti). Non l'intero repo.
3. **Se esiste un contract JSON accanto al file**, forniscilo come contesto: mostra all'LLM quali componenti sono già certificati, così non li tocca per sbaglio mentre lavora sul resto.
4. **Passata separate per tipo di modifica:** bugfix, rename/refactor e nuova feature sono tre passate diverse, non un unico prompt onnicomprensivo. Diff piccoli e a scopo singolo sono più facili da revisionare e da far passare nel gate dei test.
5. **Ordine di priorità consigliato quando più componenti hanno problemi:** prima i bug che rompono l'esecuzione (AttributeError, import mancanti, metodi che referenziano attributi mai inizializzati), poi la disciplina test-first mancante, poi rename/naming, infine nuove feature.

---

## 📁 Struttura Directory (`src/application/`)

- `action/`: logica di dominio in `.dsl` (o `.py` per casi non esprimibili nel DSL).
- `model/`: entità e schemi in `.json`.
- `repository/`: pattern di accesso ai dati.
- `view/`: definizioni UI in `.xml`.
  - `page/`: pagine applicative principali.
  - `layout/`: layout condivisi.
  - `component/`: componenti riutilizzabili.
- `policy/`: regole di sicurezza e business (`.toml`).
- `locales/`: file di traduzione/i18n.

---

## ✍️ DSL (Domain Specific Language)

Prima di creare o modificare business logic in un file `.dsl`, leggi sempre `src/application/dsl.md` per la sintassi completa e le funzioni built-in disponibili.

**Costrutti principali:**
- Assegnazione statica tipizzata: `any:var_name := value;` (per gli schemi usare `type:name := {...}`)
- Pipe: `input |> function1(args) |> function2;`
- Task/trigger: `trigger(kwargs) -> action_or_pipe;`
- Trigger schedulati: `tick(schedule: 5) -> azione;`
- Schemi tipizzati:
  ```
  type:user_schema := {
      "name": { "type": "string", "required": true };
      "age":  { "type": "integer", "default": 18 };
  };
  ```

**Vincoli sintattici stretti:**
- Niente virgole finali in dizionari `{}` o liste/tuple `()`, `[]`.
- Il valore nullo del DSL è `none`, non `null` e non `None`.
- Le dichiarazioni `:=` devono avere il prefisso di tipo (`any:name := ...`); `name := ...` non è una forma affidabile del grammar attuale.
- Le chiamate a moduli Python importati sono affidabili per funzioni/metodi già esposti; il runner DSL dei test non costruisce in modo affidabile istanze Python arbitrarie né consente di patchare i loro attributi con assegnazioni imperative.
- Commenti su singola riga con `//`. I blocchi `/* ... */` non si annidano: il primo `*/` incontrato chiude il blocco, indipendentemente dall'intenzione.

---

## 🖼️ Sistema di Presentazione XML

La UI si definisce in XML, renderizzato in HTML/Tailwind dall'adapter di presentazione. Per l'elenco completo di tag e attributi, fai sempre riferimento a `src/application/view.md`.

**Escaping obbligatorio:** `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`.

**Tag principali:** `<Window>`, `<Navigation>`, `<Row>`/`<Column>`, `<Text>` (tipo H1-H6/p/span via attributo `type`), `<Action>`, `<Container>`, `<Divider>`, `<Icon>`, `<SVG>`. Ogni file XML in `view/component/` diventa un tag custom usabile altrove (es. `<MyCard />`), con `{{ inner | safe }}` per iniettare i children.

**Attributi comuni (mappati su Tailwind):** `width`/`height`, `padding`/`margin` (valori separati da virgola), `justify`/`align`, `background` (hex o gradiente), `matter` (`glass`, `glass-max`), `font` (`bold`, `mono`, `black`, `extrabold`).

### ⚡ Reattività Server-Driven (WebSocket)
Qualunque elemento XML può reagire a cambi di stato del DSL senza JavaScript tramite l'attributo `bind="dsl_alias:node_path"` (es. `bind="counter:counter_logic.count"`).

**Regola obbligatoria:** ogni elemento con `bind=` deve avere un `id="..."` esplicito, altrimenti il framework va in crash intenzionalmente per prevenire memory leak nel DAG.

Gli alias reactive cercano esclusivamente `src/application/controller/<alias>.dsl`. I controller applicativi devono risiedere nella directory `controller/`.

---

## ⚙️ Configurazione `pyproject.toml`

```toml
[project]
name = "my_app"
key = "SECRET_KEY"

[project.policy]
presentation = "web.toml"  # → src/application/policy/presentation/web.toml

[presentation.backend]
adapter = "starlette"
port = "5000"

# CORS deny-by-default: configurare solo le origini necessarie.
cors_origins = []
cors_credentials = false
```

Ogni blocco (`persistence`, `presentation`, `message`, `manager`, ...) attiva un adapter corrispondente in `src/infrastructure/`. Il `Loader` fa discovery solo degli adapter effettivamente presenti nel file — installa via `--install`/`--setup` solo le dipendenze dichiarate nei loro contract, non un requirements.txt monolitico.

---

## 🌐 Routing e Policy

Route e regole di accesso vivono in `src/application/policy/presentation/web.toml`.

1. **Aggiungere una rotta:** entry `[[store.data.routes]]`. Il path `view` è relativo a `src/application/view/page/` — non includere il prefisso `page/` (usa `view = "portfolio.xml"`, non `view = "page/portfolio.xml"`).
2. **Definire una policy:** entry `[[policies]]`, con condizioni valutate su `input.path` / `input.principal`.

---

## 🛠️ Comandi Utili

Assicurati sempre che il virtual environment sia attivo prima di eseguire comandi.

| Comando | Effetto |
|---|---|
| `source venv/bin/activate` | Attiva il virtual environment |
| `python3 public/main.py` | Avvia il server |
| `python3 public/main.py --setup` | `pip install -e .` + installazione dipendenze degli adapter attivi — al primo avvio |
| `python3 public/main.py --install` | Installa solo le dipendenze degli adapter attivi (senza editable install) |
| `python3 public/main.py --test [FILTRO]` | Esegue i test, opzionalmente filtrati (`managers`, `ports`, `services`, `infrastructure/message`, ecc.) |
| `python3 public/main.py --verify` | Verifica tutti i contract in modalità strict senza costruire né avviare l'applicazione |
| `python3 public/main.py --dev` | Modalità dev: disattiva il controllo strict dei contract |
| `python3 public/main.py --skip-verify` | Bypassa il controllo "codice testato" — solo per emergenze umane, mai come default in un workflow LLM |

### Comportamento dei comandi CLI

I flag principali selezionano percorsi distinti nel launcher:

- **Avvio normale** — `python3 public/main.py`: legge `pyproject.toml`, carica core, manager e adapter, costruisce il container e avvia `Application`. In modalità normale il controllo strict dei contract è attivo.
- **Setup iniziale** — `python3 public/main.py --setup`: installa il progetto in editable mode con `pip install -e .`, poi analizza e installa le dipendenze dichiarate nei contract degli adapter attivi. Non avvia l'applicazione.
- **Installazione adapter** — `python3 public/main.py --install`: salta l'editable install e installa solo le dipendenze dichiarate dagli adapter attivi. Non esegue il bootstrap completo e non avvia l'applicazione.
- **Test DSL** — `python3 public/main.py --test [FILTRO]`: esegue il bootstrap necessario al tester con strict disattivato, esegue i file `.test.dsl` selezionati e può rigenerare i contract certificati. Restituisce exit code `0` se la suite passa e `1` se un test o un file non viene eseguito.
- **Verifica contract** — `python3 public/main.py --verify`: carica i componenti in strict senza costruire container, adapter o `Application`. Restituisce `0` solo se tutti gli export dichiarati sono presenti e gli hash corrispondono; restituisce `1` in caso di contract stale, export mancanti o errore di discovery.
- **Modalità sviluppo** — `python3 public/main.py --dev`: esegue il normale bootstrap con verifica strict disattivata. Non deve essere usata come sostituto dei test o della verifica dei contract.
- **Bypass emergenziale** — `python3 public/main.py --skip-verify`: esegue il normale bootstrap ignorando il controllo strict dei contract. È riservato a interventi manuali temporanei e non deve essere usato per risolvere test falliti.

`--setup`, `--install`, `--test` e `--verify` sono modalità operative alternative all'avvio normale. Per la CI usare almeno `--test` e il controllo del working tree sui contract; usare anche `--verify` quando si vuole controllare esplicitamente il boot strict senza avviare servizi.

### Contract e API dichiarata

Il blocco `exports` del test DSL è il manifest dell'API pubblica certificata del componente. Può esportare una funzione, una classe o un'istanza; quando esporta un oggetto, i metodi usati dalla suite diventano i componenti certificati di quell'export.

```dsl
exports: {
        'messenger': messenger
};
```

La suite deve invocare i metodi tramite l'oggetto esportato:

```dsl
"action": exports.messenger.send;
```

Regole obbligatorie:

- ogni export deve essere risolvibile e non può essere `none`;
- ogni azione della suite deve appartenere a un export dichiarato;
- ogni metodo esportato deve essere esercitato almeno una volta da un test passato;
- un metodo privato può essere certificato solo se è raggiunto tramite un export esplicito;
- il contract viene aggiornato solo quando l'intera API dichiarata è certificata;
- i metodi non presenti nell'API dichiarata restano dettagli interni e non vengono verificati dal contract.

Il contract generato ha questa forma:

```json
{
    "contract_version": 2,
    "exports": {
        "messenger": [
            "Manager._split_domain",
            "Manager.receive",
            "Manager.send"
        ]
    },
    "hashes": {
        "Manager": {
            "send": {
                "test": "<sha256>",
                "production": "<sha256>"
            }
        }
    }
}
```

I campi `tested_at` e `git_commit` non fanno parte del formato generato: sono
metadati variabili e non devono essere reintrodotti nei contract versionati.

La scrittura del contract è atomica e la certificazione ricostruisce gli hash, quindi gli export rimossi non lasciano componenti obsoleti. I contract legacy privi di `exports` restano leggibili e vengono verificati con la reflection pubblica storica.

In modalità `--dev` il framework segnala separatamente export mancanti, non testati o modificati e consente l'avvio. In modalità strict il boot viene bloccato se un export dichiarato manca, non ha un hash di test o è cambiato dopo la certificazione.

---

## 🧪 Come Scrivere Buoni Test DSL (`.test.dsl`)

I test DSL sono obbligatori in Framework Maintenance Mode. Seguire questi pattern garantisce test attendibili, manutenibili e che catturino davvero il comportamento del componente testato.

### Struttura Base

Un file `.test.dsl` ha tre sezioni:

```dsl
// Sezione 1: IMPORTS — Carica i moduli/risorse di cui il test ha bisogno
imports: {
    'module_name': import("framework.manager.some_manager"),
    'helper_data': resource("src/path/to/file.json")
};

// Sezione 2: EXPORTS — Dichiara l'API pubblica da certificare
exports: {
    'component': imports.module_name.Component
};

// Sezione 3: TEST SUITE — Definisce i test veri
tuple:test_suite := (
    { test_case_1_object },
    { test_case_2_object },
    ...
);
```

### Anatomia di un Test Case

```dsl
{
    "action":   exports.component.method,      // Metodo dell'API da testare
    "inputs":   "arg" or ("arg1", "arg2") or {"key": "value"},  // Input(i)
    "outputs":  "expected_result",             // Output atteso
    "assert":   @received == @expected,        // Condizione di successo
    "note":     "Descrizione leggibile del test"  // Documentazione
}
```

**Dettagli:**

- **`"action"`**: Puntatore a una funzione o a un metodo raggiunto tramite `exports`. **Obbligatorio.**
- **`"inputs"`**: Può essere:
  - Una tupla (se la funzione richiede più argomenti): `("arg1", "arg2", arg3)`
  - Un singolo valore (se la funzione richiede un solo argomento): `"string_arg"` o `123`
  - Un dizionario (se la funzione è lazy e accetta kwargs): `{"key": "value", "other": true}`
  - Una tupla di tuple per funzioni che prendono liste di tuple: `(("a", 1), ("b", 2))`
- **`"outputs"`**: L'output atteso. Il framework lo assegnerà a `@expected`.
- **`"assert"`**: Qualunque espressione DSL che ritorni `true`/`false`. I valori testati sono disponibili come:
  - `@received` — il valore effettivo tornato dalla funzione
  - `@expected` — il valore dichiarato in `"outputs"`
    - Puoi scrivere asserzioni complesse: `@received == @expected & @received != none` (AND), `@received == "OK" | @received == "SKIP"` (OR)
- **`"note"`**: Descrizione breve e leggibile del test, mostrata nei log quando passa o fallisce. **Obbligatoria.**

### Pattern Consigliati

#### ✅ Test Semplice: Eguaglianza Diretta
```dsl
{
    "action": exports.resolve_filter;
    "inputs": "managers";
    "outputs": "src/framework/manager";
    "assert": @received == @expected;
    "note": "resolve_filter('managers') ritorna il percorso corretto";
}
```

#### ✅ Test con Multipli Argomenti
```dsl
{
    "action": exports.union;
    "inputs": ({"a": 1}, {"b": 2});
    "outputs": {"a": 1, "b": 2};
    "assert": @received == @expected;
    "note": "union() unisce due dizionari correttamente";
}
```

#### ✅ Test con Asserzione Complessa
```dsl
{
    "action": exports.validate_user;
    "inputs": {"name": "Alice", "age": 25};
    "outputs": true;
    "assert": @received == @expected & @received != none;
    "note": "validate_user accetta utente valido";
}
```

#### ✅ Test di Edge Case
```dsl
{
    "action": exports.get_item;
    "inputs": ("items", "missing_key");
    "outputs": none;
    "assert": @received == @expected;
    "note": "get_item ritorna null per chiave mancante (no crash)";
}
```

#### ✅ Test di Negazione
```dsl
{
    "action": exports.is_admin;
    "inputs": {"role": "user"};
    "outputs": false;
    "assert": @received == @expected & @received != true;
    "note": "is_admin ritorna false per utente non-admin";
}
```

### 🚫 Anti-Pattern nei Test DSL

1. **Asserzioni che sempre passano** (dead test):
   ```dsl
   // ❌ SBAGLIATO — @received e @expected sono sempre uguali qui
   {
       "action": exports.something;
       "inputs": "x";
       "outputs": "anything";
       "assert": true;  // Always pass!
   }
   ```
   **Soluzione:** Scrivi un'asserzione che **effettivamente** confronta i valori.

2. **Test che verificano logica del framework, non del componente:**
   ```dsl
   // ❌ SBAGLIATO — state il verificando che import() funziona nel DSL
   {
       "action": imports.module_name;  // Non è una funzione!
       "inputs": ();
       "outputs": true;
    "assert": @received != none;
   }
   ```
   **Soluzione:** Testa una **funzione** del modulo importato, non il modulo stesso.

3. **Note generiche o assenti:**
   ```dsl
   // ❌ SBAGLIATO
   {
       "action": exports.foo;
       "inputs": "bar";
       "outputs": "baz";
       "assert": @received == @expected;
       "note": "test";  // Troppo vago
   }
   ```
   **Soluzione:** Descrivi **cosa** si sta testando e **perché** è importante:
   ```dsl
   "note": "foo() with input 'bar' returns 'baz' (nominal path)";
   ```

4. **Teste.test.dsl completamente vuoto:**
   ```dsl
   // ❌ SBAGLIATO
   tuple:test_suite := ();  // Indefinitamente!
   ```
   **Soluzione:** Se il componente è appena stato creato, scrivi **almeno un test**, anche se banale:
   ```dsl
   {
       "action": exports.my_function;
       "inputs": "test_input";
       "outputs": "test_output";
       "assert": @received == @expected;
       "note": "Verificare che my_function è disponibile e non crasha";
   }
   ```

5. **Input non rappresentativi:**
   ```dsl
   // ❌ MEDIOCRE — Testa solo con stringhe, mai numeri, liste, dicts
   {
       "action": exports.process;
       "inputs": "always_a_string";
       ...
   }
   ```
   **Soluzione:** Testa con dati che rappresentano il vero utilizzo e i margini:
   ```dsl
   { "inputs": "normal_case"; ... },
   { "inputs": 123; ... },
   { "inputs": (); ... },  // Edge case: input vuoto
   { "inputs": {"complex": "dict"}; ... }
   ```

### Checklist — Test DSL Completo

Prima di dichiarare un file `.test.dsl` finito, verifica:

- ✅ **Sezione `imports`**: Carica tutti i moduli/risorse necessari con `import()` (moduli Python) o `resource()` (file).
- ✅ **Sezione `exports`**: Dichiara tutta l'API pubblica da certificare; può contenere funzioni, classi o istanze.
- ✅ **Metodi esportati**: Ogni metodo raggiunto da un export oggetto è usato da almeno un test passato.
- ✅ **Almeno 2-3 test per funzione testata**: Nominal case + edge case + negation/error.
- ✅ **Ogni test ha una `"note"` descrittiva**: Chi legge i log capisce cosa si sta testando.
- ✅ **Asserzioni realistiche**: Confrontano `@received` con `@expected`, non sono triviali.
- ✅ **Esecuzione**: Testa localmente con `python3 public/main.py --test <filtro>` e vedi PASSED.
- ✅ **Niente leftover debug**: Niente `print()`, niente commenti commented-out, niente `raise Exception("debug")`.

### Esecuzione e Workflow

```bash
# Esegui i test di un manager specifico
python3 public/main.py --test managers/tester

# Esegui tutti i test di un'area (tutti i manager)
python3 public/main.py --test managers

# Esegui tutti i test del framework
python3 public/main.py --test

# Se un test fallisce, l'output mostra:
#   expected: <valore atteso>
#   received: <valore ottenuto>
# Usa questi due valori per debuggare il problema nel codice testato.
```

Quando l'intera suite passa, `Contract.record_tested()` rigenera il file `.contract.json` accanto al componente. Il boot strict verifica esclusivamente gli export dichiarati nel contract e confronta gli hash `test` e `production`.

### Verifica strict senza avvio dell'applicazione

Il comando:

```bash
python3 public/main.py --verify
```

carica schemi, servizi core, manager e adapter configurati in modalità strict e verifica i contract tramite `Contract.verify_module`. Non costruisce il container, non istanzia gli adapter, non crea `Application` e non avvia servizi di rete.

Il comando restituisce:

- exit code `0` se tutti i contract sono coerenti e gli export dichiarati risultano testati;
- exit code `1` se un contract contiene export mancanti, hash non aggiornati o componenti non certificati;
- exit code `1` anche in caso di errore durante la discovery o il caricamento dei moduli.

`--verify` non sostituisce `--test`: il primo controlla la coerenza tra codice e contract, mentre il secondo esegue le suite DSL e può rigenerare i contract. In CI è consigliato eseguire prima `--test`, verificare che il working tree non contenga contract modificati e poi usare `--verify` come controllo strict finale.

---

## 🚀 Workflow per Agenti — riepilogo end-to-end

1. **Stabilisci la modalità** (App Builder o Framework Maintenance) e rispetta il relativo scope.
2. **Se serve nuova logica di dominio:** definisci il modello in `src/application/model/`, scrivi l'azione in `.dsl` (consultando `dsl.md`), costruisci la vista in `.xml` (consultando `view.md`).
3. **Se stai modificando un manager esistente (Framework Maintenance Mode):** scrivi/aggiorna il `*.test.dsl` per primo, poi implementa, poi verifica con `--test <filtro>` — mai saltare questo passaggio.
4. **Controlla contro la lista degli anti-pattern** prima di considerare il lavoro finito: nessun metodo `_2`, nessun init fantasma, nessun identificatore in italiano, naming CRUD coerente, nessun debug residuo.
5. **Collega tutto in `pyproject.toml`** se hai aggiunto un nuovo adapter o modificato la configurazione.
6. **Un commit per componente**, con il contract aggiornato incluso nel commit.
