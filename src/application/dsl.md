# OmniPort DSL (Domain Specific Language) Reference

The OmniPort framework relies on a custom, reactive DSL to define business logic, state machines, and data transformations. This DSL is designed to be highly declarative and perfectly decoupled from the presentation layer.

## 📝 General Rules
- The DSL uses **Strict JSON-like structures**.
- Statements are separated by `;`.
- **NO trailing commas** are allowed in dictionaries `{}`, lists `[]`, or tuples `()`.
- Comments use `//` for single-line or `/* ... */` for block comments (nested blocks are not allowed).

## 🚀 Defining Reactive Tasks (Nodes)
A `.dsl` file represents a Directed Acyclic Graph (DAG) of nodes.
Nodes either define variables or execute tasks based on triggers.

### Defining State (Assign / Default)
```dsl
counter_logic : {
    // Defines a state variable 'count' with a default value of 0.
    // The arrow points to itself to persist the state.
    count(default: 0) -> counter_logic.count;
};
```

### Defining Actions (Triggers)
Use the format `trigger_name(kwargs) -> action;`
```dsl
increment_btn(deps: false) -> messenger.send(
    session: sid,
    domain: "counter:counter_logic.count",
    payload: (counter_logic.count + 1)
);
```

### Kwargs on Triggers (Task Metadata)
You can declare properties inside the trigger's `()`:
- `default: <value>`: Sets the initial state of the node.
- `deps: [<nodes>]` or `false`: Forces an explicit dependency list. Use `false` to prevent the engine from auto-inferring dependencies.
- `cache: false`: Disables caching for this node (forces execution every time).
- `on_end: "path.to.other.node"`: Triggers another node upon completion.

## ⚡ Pipes (Functional Chaining)
The pipe operator `|>` allows for clean functional transformations of data. The output of the previous step becomes the implicitly first argument of the next function.

```dsl
process_user() -> 
    database.get_user(id) 
    |> transform_user_data(strict: true) 
    |> messenger.send(session: sid, event: "user_loaded");
```

## 🏗️ Data Structures
The DSL supports strongly typed collections:

- **Dictionaries**: `{ "key": "value", "count": 10 }`
- **Lists**: `["apple", "banana", "cherry"]`
- **Tuples**: `(10, 20)`
- **Primitives**: `true`, `false`, `none`, strings (single or double quotes), and numbers.

## 🧮 Operations
Standard logical and mathematical operators are fully supported:
- **Math**: `+`, `-`, `*`, `/`, `%`, `^` (power)
- **Logic**: `and` (or `&`), `or` (or `|`), `not` (or `!`)
- **Comparison**: `==`, `!=`, `<`, `>`, `<=`, `>=`

```dsl
calculate() -> (base_price * 1.22) + shipping_cost;
is_valid() -> (age >= 18) and not is_banned;
```

## 📦 Static Assignments (Variables and Types)
Use `:=` for top-level static declarations. For a runtime value, use a type prefix;
for schemas use the special `type:` prefix.

```dsl
type:user_schema := {
    "name": { "type": "str", "required": true };
    "age":  { "type": "int", "default": 18 };
};

any:source := "test data";
```

La forma non tipizzata `name := value` non è supportata in modo affidabile dal
grammar attuale. Il valore nullo del DSL è `none` (non `null` e non `None`).
`resource()` non è un built-in generale: viene iniettato nell'ambiente dei
test DSL dal Tester.

## 🔌 Built-in Functions
Il registry core `framework.core.library.BUILTINS` espone `map_records`,
`tag_variants`, `keys`, `values`, `union`, `print`, `pass`, `int`, `str`,
`bool`, `random`, `format`, `result`, `file_dependencies`, `prefix_match` e
`tuple_filter_tuple`. `get()`, `put()` e `foreach()` non sono registrati come
built-in.

### Funzioni iniettate nei test

Nei file `.test.dsl`, il Tester aggiunge `resource(path)` per leggere un file
come testo e registra anche `import(module_path)`. Quest'ultimo percorso è
come testo e registra anche `import(module_path)`. L'import accetta il nome
assoluto di un modulo Python e delega da `Loader.import_module()` a
`Framework.import_module()`, che usa `importlib.import_module()`. Per i metodi
che richiedono stato usa fixture già iniettate oppure un test Python dedicato.

Durante i test, `@received` contiene il `flow.Result` restituito da
`interpreter.call()`: usa `@received.is_success`, `@received.output.value` in
caso di successo e `@received.output.error` in caso di errore. Gli argomenti
originali restano in `@received.input` e possono contenere dati sensibili.

## 🌐 Context Variables (`@`)
If you need to explicitly reference a specific runtime context variable instead of relying on standard resolution, you can prefix it with `@`.
```dsl
fetch() -> database.load(@current_user_id);
```

### Sessione e risultati tra controller

Ogni controller mantiene il proprio contesto locale. I risultati pubblicati da
un controller non vengono copiati automaticamente nel contesto di un altro
controller e non sono esposti tramite un namespace globale `shared`.

La sessione utente è il punto esplicito di coordinamento tra DAG. Nel DSL viene
esposta solo una snapshot JSON-safe della sessione; la sessione runtime del DAG
non entra mai nel contesto DSL:

```dsl
// Valore locale al controller corrente
dependencies

// Metadati della sessione
@session.id

// Risultato pubblicato dal controller terminal
@session.results.terminal.select
```

La forma canonica per un risultato remoto è quindi
`@session.results.<controller>.<node>`. Il valore rappresenta l'ultimo payload
riuscito pubblicato dal nodo. Un risultato non ancora prodotto deve essere
gestito dal controller chiamante come valore assente; i risultati vengono
rimossi quando il nodo viene invalidato o la sessione viene chiusa.

Quando una funzione di Manager o Port riceve un argomento `session`, il
framework reinietta internamente il riferimento runtime corretto. Il DSL può
quindi continuare a usare le API dichiarative esistenti senza ricevere o
serializzare `Session`, `SessionHandle`, Runner, adapter o primitive di
sincronizzazione.
