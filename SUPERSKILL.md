# ARCHITECTURE-FIRST DEVELOPMENT RULES

Quando modifichi o aggiungi codice a questo progetto, considera l'architettura esistente come un vincolo, non come un suggerimento.

Il codice generato deve essere immediatamente comprensibile a chi ha progettato le astrazioni del progetto. Prima di introdurre una nuova astrazione, cerca sempre di esprimere il problema attraverso quelle esistenti. Se una nuova astrazione è realmente necessaria, fermati e spiegala prima di implementarla.

E aggiungerei:

Non ottimizzare per una soluzione che ritieni genericamente migliore se questa aumenta la distanza dal modello architetturale esistente. Una soluzione leggermente meno astratta ma coerente con il progetto è preferibile a una soluzione più sofisticata che introduce un nuovo modello mentale

## 1. Prima di scrivere codice, comprendi il vocabolario del progetto

Prima di implementare una modifica:

1. Analizza le astrazioni già presenti.
2. Individua Port, Adapter, Manager, Service, Scheme, Flow, Result, Container e gli altri concetti già utilizzati.
3. Cerca se il problema può essere rappresentato usando una di queste astrazioni.
4. Riutilizza le astrazioni esistenti prima di introdurne di nuove.

Non creare una nuova astrazione semplicemente perché risulta comoda per l'implementazione.

---

## 2. Le astrazioni esistenti hanno priorità

Se esiste già un'astrazione che rappresenta correttamente un concetto, devi utilizzarla.

Esempio:

```text
PersistencePort
    ↓
FilesystemAdapter
RedisAdapter
SupabaseAdapter
```

Se devi aggiungere Redis, devi preferire:

```python
class RedisAdapter(PersistencePort):
    ...
```

e non creare autonomamente:

```python
StorageCoordinator
StorageBackend
StorageRegistry
StorageManager
```

per rappresentare lo stesso concetto.

---

## 3. Non inventare un nuovo vocabolario

Non introdurre nuove astrazioni con nomi come:

```text
Coordinator
Mediator
Bridge
UniversalManager
GenericHandler
ContextManager
ResourceManager
Controller
Orchestrator
Registry
```

se il loro significato duplica un'astrazione già presente nel progetto.

Questi nomi non sono vietati quando rappresentano componenti già esistenti o
una responsabilità realmente distinta. Prima di aggiungerne uno nuovo,
verifica che non stia duplicando un Port, Adapter, Manager, Service, Scheme,
Flow, Result, Container, Repository, Policy o Action già presente.

Prima verifica sempre se il concetto appartiene già a:

```text
Port
Adapter
Manager
Service
Scheme
Flow
Result
Container
Repository
Policy
Action
```

o ad altre astrazioni già presenti nel codice.

---

## 4. Nuove astrazioni richiedono una motivazione

Puoi introdurre una nuova astrazione soltanto se:

* nessuna astrazione esistente rappresenta correttamente il concetto;
* riutilizzare un'astrazione esistente produrrebbe una responsabilità impropria;
* la nuova astrazione migliora realmente separazione delle responsabilità o dipendenze.

Prima di crearla, esplicita:

```text
NUOVA ASTRAZIONE

Nome:
Responsabilità:
Perché serve:
Quali astrazioni esistenti sono state considerate:
Perché non sono sufficienti:
Dipendenze:
```

Se non riesci a giustificarla chiaramente, non crearla.

---

## 5. Mantieni la direzione delle dipendenze

Non modificare arbitrariamente la direzione architetturale.

Preferisci:

```text
Domain
   ↑
Application
   ↑
Port
   ↑
Adapter
```

quando questa è la struttura già adottata dal progetto.

Gli Adapter implementano le astrazioni definite dal sistema; non devono diventare il punto da cui l'architettura viene ridefinita.

---

## 6. Prima modifica minima

Quando risolvi un problema:

1. identifica il punto responsabile;
2. modifica il minor numero possibile di astrazioni;
3. riutilizza componenti esistenti;
4. evita refactoring architetturali non richiesti;
5. non introdurre nuove strutture solo per semplificare localmente l'implementazione.

Non trasformare una richiesta locale in una nuova architettura.

---

## 7. Preserva il modello mentale del progetto

Il codice deve essere leggibile attraverso le astrazioni già presenti.

Devo poter vedere:

```text
Port → Adapter
Scheme → Flow
Manager → Port
Container → Dependency
Result → Flow
```

e capire immediatamente il ruolo del componente senza dover analizzare tutta la sua implementazione.

La leggibilità architetturale ha priorità rispetto alla brevità locale del codice.

---

## 8. Prima di implementare: piano architetturale

Prima di modificare codice, rispondi brevemente:

```text
PROBLEMA
Cosa devo cambiare?

ASTRAZIONI ESISTENTI
Quali astrazioni già presenti posso utilizzare?

COMPONENTI DA MODIFICARE
Quali file/classi devono cambiare?

NUOVE ASTRAZIONI
Ne serve qualcuna?
Se sì, perché quelle esistenti non bastano?

FLUSSO
Come attraverserà il sistema la nuova logica?

INVARIANTI
Quali regole architetturali devono rimanere vere?
```

Dopo questa analisi puoi implementare.

---

## 9. Dopo l'implementazione: verifica architetturale

Al termine controlla:

```text
[ ] Ho riutilizzato le astrazioni esistenti?
[ ] Ho introdotto nuove astrazioni?
[ ] Se sì, sono realmente necessarie?
[ ] Ho aggiunto dipendenze inutili?
[ ] Ho modificato la direzione delle dipendenze?
[ ] Ho duplicato una responsabilità già esistente?
[ ] Il nuovo codice è esprimibile attraverso il vocabolario del progetto?
[ ] I test esistenti continuano a passare?
```

Se una risposta è negativa, correggi il codice prima di considerare concluso il lavoro.

---

## 10. Regola fondamentale

NON ottimizzare soltanto per:

> "far funzionare il codice".

Ottimizza nell'ordine:

```text
ARCHITETTURA
     ↓
RESPONSABILITÀ
     ↓
DIPENDENZE
     ↓
IMPLEMENTAZIONE
     ↓
OTTIMIZZAZIONE
```

Il codice deve inserirsi nel modello architetturale esistente, non costringere il progetto ad adattarsi al codice appena scritto.

---

## 11. Modello data-driven del DSL

Il progetto distingue tre livelli che non devono essere confusi:

```text
DSL
     testo dichiarativo scritto dall'utente

Rappresentazione runtime del DSL
     programma compilato che descrive operazioni, nodi e dipendenze

Context
     dati JSON prodotti e aggiornati durante l'esecuzione
```

Il flusso principale è:

```text
DSL
     -> parser e compiler
     -> rappresentazione runtime del DSL
     -> evaluator e runner
     -> context JSON aggiornato
```

La rappresentazione runtime del DSL deve contenere dati descrittivi, non
oggetti operativi. Può descrivere riferimenti, chiamate, nodi, dipendenze,
eventi, condizioni e risultati, ma non deve contenere direttamente:

```text
Manager, Adapter, coroutine, asyncio.Task, lock, queue o callable Python
```

Il `Context` contiene esclusivamente dati puri e ricostruibili:

```text
stringhe, numeri, booleani, null, liste e mappe JSON
```

I Manager e gli Adapter leggono dal `Context`, eseguono il comportamento
runtime e scrivono nel `Context` soltanto risultati puri. Il runtime può essere
ricreato partendo dalla rappresentazione del DSL, dal Registry delle
implementazioni e dal Context.

Invariante fondamentale:

```text
Il programma descrive cosa fare.
Il runtime sa come farlo.
Il Context conserva i dati e i risultati.
```

Per i risultati usa il contratto runtime effettivo: `Result.is_success` è una
proprietà, `Result.output` contiene `Success.value` o `Failure.error`,
`flow.output()` estrae payload o errore e `flow.unwrap()` solleva l'errore.
Non presumere chiavi `success`/`outputs`/`errors`. `Result.input` conserva gli
argomenti della chiamata e va filtrato prima di esporre il risultato.

---

## 12. Scrivi codice comprensibile attraverso il flusso dei dati

Prima di modificare codice, descrivi brevemente:

```text
INPUT
Quali dati entrano?

TRASFORMAZIONE
Quale componente li interpreta o modifica?

OUTPUT
Quali dati puri escono o vengono scritti nel Context?

RUNTIME
Quali oggetti operativi vengono usati senza finire nei dati?
```

Preferisci nomi espliciti, funzioni piccole e passaggi visibili. Non nascondere
trasformazioni importanti dietro astrazioni generiche solo per ridurre il
numero di righe.

Quando una modifica è complessa:

1. mostra prima il comportamento attuale con un esempio concreto;
2. descrivi il comportamento desiderato;
3. modifica una responsabilità alla volta;
4. esegui un test mirato dopo ogni modifica;
5. verifica che il Context resti JSON e che il runtime resti fuori dai dati.

---

## 13. Quando hai dubbi, fermati

Se non è chiaro quale astrazione utilizzare, NON inventarne immediatamente una.

Dichiara il dubbio e proponi le alternative:

```text
Ho individuato queste astrazioni esistenti:

A → ...
B → ...
C → ...

A sembra la più vicina perché ...

Prima di introdurre una nuova astrazione, verifico se A può essere estesa o utilizzata.
```

---

## 14. Importante: puoi scrivere molto codice, ma devi mantenere il vocabolario

Non è necessario limitare la quantità di codice prodotto.

Puoi modificare anche molti file e implementare funzionalità complesse.

Il vincolo fondamentale è:

> NUOVA IMPLEMENTAZIONE, STESSO LINGUAGGIO ARCHITETTURALE.

L'obiettivo è che un componente nuovo sembri appartenere naturalmente al progetto invece di introdurre un secondo modo di progettare il sistema.
