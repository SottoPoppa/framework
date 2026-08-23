![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)

# OmniPort Framework

Un framework Python ad architettura esagonale (ports & adapters), pensato per essere costruito e modificato da agenti AI in sicurezza quanto da sviluppatori umani.

> "Smetti di scrivere codice per una sola piattaforma. Definisci l'intento, scegli il Port."

---

## Cos'è

OmniPort separa nettamente tre livelli:

- **`application/`** — la logica di dominio: modelli, controller (DSL), viste (XML), policy. È l'unica zona pensata per essere toccata di continuo, anche da un agente AI.
- **`framework/`** — il kernel: caricamento dinamico dei moduli, container di dependency injection, orchestrazione. Non va modificato.
- **`infrastructure/`** — gli adapter concreti (persistenza, presentazione web/console, autenticazione, messaggistica, sensori/attuatori...). Intercambiabili senza toccare la logica di dominio.

Il tutto orchestrato da un unico file di configurazione dichiarativa (`pyproject.toml`) e da un `Loader` che fa discovery, dependency injection e installazione delle dipendenze in base a cosa è effettivamente abilitato.

---

## Perché esiste — casi d'uso reali

### 1. Backend per piattaforme "vibe coding" / app-builder guidati da AI
**Problema tipico:** un utente non tecnico chiede a un agente AI di costruire/modificare un'app via chat. L'agente ha libertà totale sul codice → rompe cose, inventa API, o scrive codice mai testato che finisce comunque in produzione.
**Come lo risolvi:** perimetro fisso (`src/application/` è l'unica zona modificabile dall'agente, regola imposta via `SKILL.md`), DSL/XML invece di codice libero (meno gradi di libertà sintattica = meno spazio per "allucinazioni", file più corti da rileggere/riscrivere ad ogni iterazione = meno token), e il gate `Contract.verify_module()` che blocca l'avvio in modalità strict se un componente è stato modificato dopo l'ultimo test superato, a meno di usare esplicitamente `--dev`, `--test` o `--skip-verify`. È il caso d'uso "bandiera" del progetto ed è quello meglio coperto dal codice.

### 2. Prototipo che deve poter cambiare infrastruttura senza riscritture
**Problema tipico:** inizi con un MVP che salva dati su filesystem (vedi `[[persistence.filesystem]]` nel `pyproject.toml` di esempio), poi devi passare a Redis o a un DB vero, senza toccare la logica di dominio.
**Come lo risolvi:** gli adapter di persistenza sono intercambiabili dietro la stessa porta; cambi la sezione `[persistence.*]` nel toml e il `Loader` fa discovery del nuovo adapter, legge il suo contract per installare solo le dipendenze dichiarate (`requires`) e lo inietta al posto del vecchio — niente `requirements.txt` monolitico con ogni dipendenza possibile del framework.

### 3. Stessa logica di dominio esposta su più canali
**Problema tipico:** vuoi la stessa business logic accessibile sia da dashboard web sia da CLI/TUI interna per l'ops team, senza duplicare codice.
**Come lo risolvi:** ci sono adapter di presentazione sia web (`starlette`) sia console/TUI — la logica in `application/controller/` resta unica, cambia solo l'adapter di presentazione montato.

### 4. Dashboard/pannelli reattivi senza build pipeline JS
**Problema tipico:** per avere UI che si aggiorna in tempo reale di solito serve un frontend SPA (React/Vue) + API separata + gestione dello stato lato client — tanta complessità per un pannello interno o un monitor.
**Come lo risolvi:** il binding `bind="dsl_alias:node_path"` via WebSocket collega direttamente un nodo XML allo stato del DAG del DSL lato server: cambia lo stato, l'elemento si aggiorna, senza scrivere JS. Buon fit per pannelli di controllo, monitoraggio, admin tool interni.

### 5. Dati da sensori / automazione con logica a trigger temporali
**Problema tipico:** un sistema che deve reagire periodicamente a eventi o leggere sensori (IoT, home automation, monitoraggio) e agire di conseguenza, con la UI di controllo integrata.
**Come lo risolvi:** cartelle dedicate `sensation/` e `actuation/` in `infrastructure/`, e il DSL supporta trigger schedulati nativi (`tick(schedule: 5) -> azione;`) — il pattern trigger→action si presta bene a "leggi sensore ogni N secondi → valuta → aziona".

### 6. Autorizzazione centralizzata invece che sparsa nel codice
**Problema tipico:** regole di accesso (`if user.role == 'admin'`) sparse in ogni controller, difficili da auditare.
**Come lo risolvi:** `policy/presentation/web.toml` centralizza route (`[[store.data.routes]]`) e regole `[[policies]]` valutate su `input.path` / `input.principal` — un unico posto dove capire chi può accedere a cosa.

### 7. Passaggio di consegne da AI a sviluppatore umano
**Problema tipico:** un MVP generato da AI arriva a un team umano che deve prenderlo in carico, ma è un "muro di codice" illeggibile e non si sa cosa è stato davvero testato.
**Come lo risolvi:** la separazione esagonale rende chirurgico l'intervento umano (tocchi solo l'adapter o l'azione che ti interessa), e i contract dicono esplicitamente, componente per componente, cosa è certificato da un test e cosa no — documentazione di stato dei test che sopravvive al fatto che l'abbia scritta un'IA o un umano.

---

## Architettura

```
/
├── public/
│   └── main.py              # entry point CLI
├── src/
│   ├── framework/
│   │   ├── manager/
│   │   │   └── loader.py    # kernel: Framework, Loader, Handle, Application
│   │   ├── port/             # interfacce (inversione di controllo)
│   │   ├── scheme/           # schemi JSON del core
│   │   └── service/          # container DI, contract, introspection
│   ├── infrastructure/
│   │   ├── persistence/      # filesystem, redis, ecc.
│   │   ├── presentation/     # web (starlette), console/tui
│   │   ├── authentication/
│   │   ├── authorization/
│   │   ├── encryption/
│   │   ├── message/           # bus, pub/sub
│   │   ├── sensation/          # input da sensori/hardware
│   │   ├── actuation/          # azioni sul mondo reale/simulato
│   │   └── inference/          # ML/AI
│   └── application/            # ← unica zona pensata per modifiche continue
│       ├── model/               # entità (JSON schema)
│       ├── action/               # logica di dominio (.dsl)
│       ├── view/
│       │   ├── page/               # pagine
│       │   ├── layout/             # layout condivisi
│       │   └── component/          # componenti riutilizzabili (.xml)
│       ├── policy/                # regole di business e routing (.toml)
│       ├── repository/            # pattern repository
│       └── locales/               # i18n
└── pyproject.toml               # configurazione dichiarativa del progetto
```

**Pattern architetturale:** Hexagonal Architecture (Ports & Adapters) basata sul classico **MVC — Model / View / Controller**, con controller DSL caricati dinamicamente.

**Dependency Injection:** container custom con registrazione esplicita dei provider, risoluzione lazy, supporto a singleton/factory, e ordine di inizializzazione calcolato automaticamente via `graphlib.TopologicalSorter` sulle dipendenze dichiarate nei contract.

**Caricamento dinamico:** i moduli vengono caricati a runtime con `importlib.util.spec_from_file_location`, registrati in `sys.modules` come pacchetti sintetici, e possono essere ricaricati a caldo (hot-reload) tramite la classe `Handle`, che sostituisce l'oggetto interno preservandone lo stato.

---

## Installazione

### Requisiti
- Python ≥ 3.8 (per il supporto nativo TOML serve 3.11+, altrimenti viene usato `tomli` come fallback)

### 1. Clona la repository
```bash
git clone https://github.com/SottoPoppa/framework.git
cd framework
```

### 2. Crea e attiva un ambiente virtuale
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Setup completo (consigliato al primo avvio)
```bash
python3 public/main.py --setup
```
Questo comando:
1. installa il framework stesso in modalità editable (`pip install -e .`);
2. legge i contract degli adapter abilitati in `pyproject.toml` e installa via pip solo le dipendenze da essi dichiarate (`requires`).

In alternativa, se hai già fatto `pip install -e .` a mano, puoi limitarti a:
```bash
python3 public/main.py --install
```

### 4. Configura la sicurezza e avvia l'applicazione

Per l'adapter Starlette, `manager.defender.key` è obbligatoria per firmare la sessione. Sostituisci il valore di esempio con una chiave segreta non versionata in un ambiente reale. Le origini CORS sono vuote per default e devono essere configurate esplicitamente quando servono.

```bash
python3 public/main.py
```

### Flag disponibili
| Flag | Effetto |
|---|---|
| `--config PATH` | Percorso del file di configurazione (default: `pyproject.toml`) |
| `--debug` | Abilita la modalità debug |
| `--dev` | Abilita la modalità dev (disattiva il controllo strict dei contract) |
| `--install` | Installa solo le dipendenze dichiarate dagli adapter attivi, senza bootstrap completo |
| `--setup` | `pip install -e .` + `--install`, per la prima configurazione dell'ambiente |
| `--test [FILTRO]` | Esegue i test del framework, opzionalmente filtrati (es. `services`, `managers`, `infrastructure/message`) |
| `--test-integration [FILTRO]` | Esegue gli scenari `*.integration.test.dsl` sul runtime bootstrap-ato |
| `--skip-verify` | Bypassa il controllo "codice testato" degli adapter all'avvio — usare con cautela |

---

## Configurazione (`pyproject.toml`)

Gli integration test che richiedono adapter dedicati possono usare una configurazione separata, per esempio `pyproject.integration.toml`, senza aggiungere provider di test alla configurazione applicativa:

```bash
python3 public/main.py --config pyproject.integration.toml --test-integration managers/storekeeper
```

Il progetto si configura dichiarativamente, senza codice imperativo:

```toml
[project]
name = "hub"
version = "0.1.0"

[manager.defender]
soglia_tentativi = 5
timeout_blocchi = 3600

[[persistence.filesystem]]
name = "log"

[[presentation.console]]
name = "tui"
```

Ogni blocco (`persistence`, `presentation`, `message`, `manager`, ...) attiva un adapter corrispondente in `src/infrastructure/`. Il `Loader` fa discovery automatico solo degli adapter effettivamente presenti nel file.

Un adapter API può usare un provider OAuth nominato nella stessa configurazione:

```toml
[[authentication.oauth]]
name = "provider"
token_url = "https://auth.example.com/oauth/token"
grant_type = "password"
client_id = "client-id"
client_secret = "client-secret"
username = "user@example.com"
password = "password"

[[persistence.api]]
name = "external-api"
url = "https://api.example.com"
auth = "provider"
```

Prima di ogni richiesta, l'adapter API usa il `Defender Manager` per eseguire
il login OAuth quando necessario e aggiunge il token alla richiesta. Il token
viene mantenuto nella sessione e rinnovato quando scade.

Il file TOML supporta anche il rendering tramite template Jinja2 prima del parsing.

```toml
[project]
name = "{{ uuid4() }}"
```

Per i segreti e i parametri di connessione usare la variabile `env` e non
inserire i valori direttamente nel repository:

```toml
client_id = '{{ env["GLPI_CLIENT_ID"] }}'
client_secret = '{{ env["GLPI_CLIENT_SECRET"] }}'
password = '{{ env["GLPI_PASSWORD"] }}'
app_token = '{{ env["GLPI_APP_TOKEN"] }}'
```

Prima di avviare l'applicazione, esportare le variabili nell'ambiente del
processo, per esempio:

```bash
export GLPI_TOKEN_URL="https://glpi.example.com/api.php/token"
export GLPI_GRANT_TYPE="password"
export GLPI_CLIENT_ID="..."
export GLPI_CLIENT_SECRET="..."
export GLPI_AUTH_STYLE="body"
export GLPI_USERNAME="..."
export GLPI_PASSWORD="..."
export GLPI_SCOPE="api"
export GLPI_VERIFY_SSL="false"
export GLPI_API_URL="https://glpi.example.com/"
export GLPI_AUTH_NAME="glpi-oauth"
export GLPI_APP_TOKEN="..."
export GLPI_TIMEOUT="30"
```

Il loader passa l'ambiente come dizionario Jinja; gli adapter convertono poi i
valori numerici e booleani (`timeout` e `verify_ssl`) nel tipo necessario.

### Repository, modelli e mapping dei provider

Un repository DSL definisce sia i percorsi dei provider sia il modello canonico
usato per normalizzare le risposte:

```dsl
factory:repository := {
    location: {
        "GITHUB": [
            "repos/{{ owner }}/{{ name }}"
        ]
    };

    model: "repository";

    mapper: {
        "name": {"GITHUB": "name"};
        "owner": {"GITHUB": "owner.login"};
        "stars": {"GITHUB": "stargazers_count"}
    }
};
```

`mapper` usa la forma:

```text
chiave_del_modello: {
    PROFILO_PROVIDER: percorso_nella_risposta
}
```

Il flusso di una risposta è:

```text
provider response
    → mapper del profilo
    → chiavi canoniche del modello
    → scheme.normalize()
    → Repository.results()
```

Per esempio, una risposta GitHub come:

```json
{
    "name": "framework",
    "owner": {"login": "SottoPoppa"},
    "stargazers_count": 12
}
```

viene trasformata nel modello applicativo:

```json
{
    "name": "framework",
    "owner": "SottoPoppa",
    "stars": 12
}
```

I percorsi annidati, come `owner.login`, sono supportati. Il modello indicato
da `model` viene poi validato e completato con i valori di default definiti
nello schema JSON.

## Risultati Flow

I metodi pubblici dei Manager e le API degli Adapter usano un contratto comune
basato su `framework.service.flow`. Una chiamata restituisce un dizionario con
esito, payload ed eventuali errori:

```python
result = await manager.operation(session, **constants)

if result["success"]:
	value = flow.output(result)
else:
	errors = result["errors"]
```

Il payload non va letto direttamente dal risultato: usa sempre
`flow.output(result)`. I metodi pubblici sono normalmente marcati con
`@flow.result()`. I Port possono applicare automaticamente lo stesso
decorator agli Adapter concreti tramite `__init_subclass__`.

Il risultato può includere metadati di tracciamento come `action`, `component`,
`pipeline`, `node` e `history`. Il campo `transactions` contiene i risultati
Flow dei confini chiamati internamente. La catena attraversa DSL, framework e
infrastructure, permettendo di ricostruire la chiamata senza perdere il
risultato completo di ogni passaggio.

Nel DSL e nell'interprete, le chiamate restituiscono il risultato Flow
completo. Il payload va estratto esplicitamente:

```python
result = await interpreter.call(action)
payload = flow.output(result)
transactions = result["transactions"]
```

Anche `SessionHandle.run()` restituisce un Flow. I risultati dei nodi DAG sono
disponibili sia nella mappa `flow.output(run_result)` sia nelle transazioni del
risultato. In modalità `--dev`, ogni risultato Flow include anche `replay` con
azione, componente, argomenti e keyword argument necessari a ripetere la
chiamata. Fuori da `--dev` gli input non vengono registrati, così password,
token e altri dati sensibili non finiscono nella cronologia.

### Test DSL

Durante un test, `@received` contiene il risultato Flow completo restituito da
`interpreter.call()`, non solo il payload. I campi principali sono:

```dsl
@received.success
@received.outputs
@received.errors
@received.transactions
@received.replay
```

`@expected` contiene sempre il valore dichiarato in `outputs`. Per verificare
il payload si usa quindi `@received.outputs`; per verificare anche l'esito:

```dsl
"outputs": {"name": "Alice"};
"assert": @received.success == true & @received.outputs.name == @expected.name;
```

Gli errori possono essere verificati senza estrarre il payload:

```dsl
"assert": @received.success == false & @received.errors != none;
```

Una suite con zero test non è considerata valida. Il comando di test deve
riportare un numero di test eseguiti maggiore di zero.

Gli helper privati e le funzioni pure non devono essere decorati senza motivo:
il contratto Flow va applicato ai confini pubblici tra componenti.

---

## Stato del progetto

Progetto sperimentale in sviluppo attivo. Roadmap aperta:

- [ ] Rifattorizzare il loader dei moduli per maggiore efficienza
- [ ] Supporto multi-lingua completo
- [ ] Caricamento dinamico con attesa tramite Jinja2
- [ ] Iniezione delle dipendenze più completa
- [ ] Pipeline DevOps per deployment continuo
- [ ] Binding dati frontend/backend più completo
- [ ] Suite di test obbligatoria

---

## Licenza

Distribuito sotto licenza **AGPL v3**.

## Contribuire

Contributi, segnalazioni di bug e suggerimenti sono benvenuti. Apri pure una issue o una pull request.