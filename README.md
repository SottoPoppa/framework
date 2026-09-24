![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)

# OmniPort Framework

Un framework Python ad architettura esagonale (ports & adapters), pensato per essere costruito e modificato da agenti AI in sicurezza quanto da sviluppatori umani.

> "Smetti di scrivere codice per una sola piattaforma. Definisci l'intento, scegli il Port."

Revisione statica del codice e limiti dell'analisi: [report.md](report.md).

---

## Cos'è

OmniPort separa nettamente tre livelli:

- **`application/`** — la logica di dominio: modelli, controller (DSL), viste (XML), policy. È l'unica zona pensata per essere toccata di continuo, anche da un agente AI.
- **`framework/`** — il kernel: caricamento dinamico dei moduli, container di dependency injection, orchestrazione. Non va modificato.
- **`infrastructure/`** — gli adapter concreti (persistenza, presentazione web/console, autenticazione, messaggistica, sensori/attuatori...). Intercambiabili senza toccare la logica di dominio.

Il tutto orchestrato da un unico file di configurazione dichiarativa (`pyproject.toml`) e da un `Loader` che fa discovery, dependency injection e installazione delle dipendenze in base a cosa è effettivamente abilitato. Le Port possono inoltre ricevere una configurazione globale dal DSL applicativo, condivisa da tutte le loro implementazioni.

---

## Perché esiste — casi d'uso reali

### 1. Backend per piattaforme "vibe coding" / app-builder guidati da AI
**Problema tipico:** un utente non tecnico chiede a un agente AI di costruire/modificare un'app via chat. L'agente ha libertà totale sul codice → rompe cose, inventa API, o scrive codice mai testato che finisce comunque in produzione.
**Come lo risolvi:** perimetro di modifica indicato in `SKILL.md`, DSL/XML invece di codice libero e un gate dei contract che, in modalità strict, confronta l'hash del sorgente degli export dichiarati con quello registrato dopo una suite passata. Il gate si applica solo ai componenti con un contract e rileva modifiche al sorgente: non valuta qualità o copertura dei test e non dimostra la correttezza del comportamento. `--dev`, `--test` e `--skip-verify` disattivano il controllo strict. È il caso d'uso "bandiera" del progetto ed è quello meglio coperto dal codice.

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
**Come lo risolvi:** le policy dichiarative in `src/application/policy/presentation/` descrivono route, regole di accesso e configurazione globale della Port. Per esempio, `routes.dsl` dichiara le route e `presentation.dsl` contiene policy e capabilities; non è un file `web.toml` con tabelle `[[store.data.routes]]`.

### 7. Passaggio di consegne da AI a sviluppatore umano
**Problema tipico:** un MVP generato da AI arriva a un team umano che deve prenderlo in carico, ma è un "muro di codice" illeggibile e non si sa cosa è stato davvero testato.
**Come lo risolvi:** la separazione esagonale rende chirurgico l'intervento umano (tocchi solo l'adapter o l'azione che ti interessa), e i contract registrano quali export hanno hash corrispondenti a una suite passata. Sono una traccia di integrità del sorgente, non una misura della copertura né una garanzia indipendente della qualità dei test.

---

## Architettura

```
/
├── public/
│   └── main.py              # entry point CLI
├── src/
│   ├── application/              # dominio e configurazione applicativa
│   │   ├── controller/           # DAG dichiarativi (.dsl)
│   │   ├── model/                # modelli JSON
│   │   ├── policy/               # policy DSL
│   │   ├── repository/           # repository DSL
│   │   └── view/
│   │       ├── page/
│   │       ├── layout/
│   │       ├── component/
│   │       └── template/
│   ├── framework/                # runtime e astrazioni del framework
│   │   ├── core/
│   │   ├── manager/
│   │   ├── port/
│   │   ├── scheme/
│   │   └── service/
│   └── infrastructure/           # adapter concreti
│       ├── actuation/
│       ├── authentication/
│       ├── message/
│       ├── network/
│       ├── persistence/
│       ├── presentation/
│       └── sensation/
└── pyproject.toml                # configurazione dichiarativa del progetto
```

**Pattern architetturale:** Hexagonal Architecture (Ports & Adapters) basata sul classico **MVC — Model / View / Controller**, con controller DSL caricati dinamicamente.

**Dependency Injection:** container custom con registrazione esplicita dei provider, risoluzione lazy, supporto a singleton/factory, e ordine di inizializzazione calcolato automaticamente via `graphlib.TopologicalSorter` sulle dipendenze dichiarate nei contract.

**Caricamento dinamico:** i moduli vengono caricati a runtime con `importlib.util.spec_from_file_location`, registrati in `sys.modules` come pacchetti sintetici, e possono essere ricaricati a caldo (hot-reload) tramite la classe `Handle`, che sostituisce l'oggetto interno preservandone lo stato.

**Configurazione Port e capabilities:** ogni Port definisce nel proprio schema JSON il contratto della configurazione globale e l'insieme delle capabilities attese. Una policy DSL dichiara la Port destinataria con `port_schema` e assegna la configurazione, per esempio `presentation:configuration := { ... };`. Ogni adapter concreto dichiara invece le proprie `capabilities`: il Loader le valida contro lo schema dell'adapter e il Defender verifica che soddisfino i requisiti della policy. La configurazione globale viene poi pubblicata su manager e adapter tramite `port_configuration`.

---

## Installazione

### Requisiti
- Python `>=3.11,<3.12`, come dichiarato in `pyproject.toml`.

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
| `--skip-verify` | Bypassa il controllo strict degli hash dei contract all'avvio — usare con cautela |

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

La configurazione è divisa in due livelli:

- `pyproject.toml` configura ogni istanza tecnica dell'adapter, inclusi `host`, `port` e `protocol` del server Starlette;
- la policy DSL della Port configura il comportamento globale condiviso da tutte le implementazioni della Port.

Il TOML può definire più istanze dello stesso servizio, ciascuna con nome, host e porta propri:

```toml
[[presentation.starlette]]
name = "public"
host = "127.0.0.1"
port = 8000
protocol = "http"

[[presentation.starlette]]
name = "internal"
host = "127.0.0.1"
port = 8001
protocol = "http"
```

Entrambe le istanze ricevono la stessa configurazione globale `presentation` dal DSL, ma mantengono separata la propria configurazione tecnica TOML.

Esempio di policy globale presentation:

```dsl
any:port_schema := "presentation";
any:adapter_schema := "presentation_adapter";

presentation:configuration := {
    "presentation_type": "rest_api";
    "cors_policy": { "enabled": false };
    "security_and_waf": {
        "tls_enabled": false;
        "csrf_protection": false
    };
    "authentication_guards": { "auth_required": false }
};
```

L'adapter dichiara le capacità che supporta, mentre il Defender raccoglie le capacità di tutti gli adapter attivi della Port. Se la policy richiede una capacità non disponibile in una delle implementazioni configurate, il bootstrap o l'autorizzazione vengono rifiutati.

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
client_id = '{{ env("GLPI_CLIENT_ID") }}'
client_secret = '{{ env("GLPI_CLIENT_SECRET") }}'
password = '{{ env("GLPI_PASSWORD") }}'
app_token = '{{ env("GLPI_APP_TOKEN") }}'
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

I confini pubblici tra Manager, Port e Adapter usano `framework.core.flow`.
`flow.Result` è un contenitore immutabile: `result.is_success` è una proprietà
boolean, mentre `result.output` contiene un oggetto `Success` o `Failure`.
Il valore riuscito è in `result.output.value`; l'errore è in
`result.output.error`.

```python
import framework.core.flow as flow

result = await manager.operation(session, **constants)

if result.is_success:
    value = flow.output(result)
else:
    error = flow.output(result)
```

`flow.output(result)` restituisce il payload in caso di successo o il valore
d'errore in caso di fallimento, senza sollevarlo. `flow.unwrap(result)` estrae
il payload oppure solleva l'errore. I metodi pubblici sono normalmente marcati
con `@flow.result()`; i Port possono applicare automaticamente il decorator
agli Adapter concreti tramite `__init_subclass__`.

Il risultato espone metadati quali `action`, `component`, `execution_time_ms`,
`input` e `transactions`. `transactions` è una tupla dei risultati Flow dei
confini chiamati internamente; `steps` offre la mappa degli output riusciti
indicizzati per azione. Il flusso attraversa DSL, framework e infrastructure.

**Attenzione ai dati:** `@flow.result()` conserva sempre gli argomenti e le
keyword argument della chiamata in `result.input`, anche fuori da `--dev`.
Non esporre né serializzare l'intero risultato o le sue transazioni senza
filtrare prima sessioni, credenziali e altri dati sensibili.

Nel DSL e nell'interprete, le chiamate restituiscono il risultato Flow
completo. In Python il payload si estrae con `flow.output()`; in un test DSL
si accede ai campi dell'oggetto risultato:

```python
result = await interpreter.call(action)
payload = flow.output(result)
transactions = result.transactions
```

Anche `SessionHandle.run()` restituisce un Flow; la mappa degli output dei nodi
DAG è disponibile tramite `flow.output(run_result)`.

### Test DSL

Durante un test, `@received` contiene il risultato Flow completo restituito da
`interpreter.call()`, non solo il payload. I campi principali sono:

```dsl
@received.is_success
@received.output.value
@received.output.error
@received.transactions
@received.input
```

`@received.output` è un oggetto `Success` o `Failure`; usa `value` solo quando
`is_success` è vero e `error` quando è falso. `@expected` contiene il valore
dichiarato in `outputs`. Per verificare payload ed esito:

```dsl
"outputs": {"name": "Alice"};
"assert": @received.is_success == true & @received.output.value.name == @expected.name;
```

Un esito fallito si verifica attraverso `Failure.error`:

```dsl
"assert": @received.is_success == false & @received.output.error != none;
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