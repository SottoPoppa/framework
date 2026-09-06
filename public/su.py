import asyncio
from dataclasses import dataclass

# --- IMPORT DEI TUOI MODULI AGGIORNATI ---
# Assicurati che i file siano nello stesso modulo o nei rispettivi pacchetti
from framework.core.language.parser import Parser          # Il tuo parser con propagate_positions=True
from framework.core.language.compiler import Compiler      # Il tuo compiler aggiornato per Dataclass AST
from framework.core.dag.graph import Dag              # Il tuo DAG con gestione context
from framework.core.dag.runner import DagRunner       # Il tuo runner asincrono aggiornato


# --- 1. MOCK / REGISTRY DELLE FUNZIONI (OPZIONALE) ---
class DummyRegistry:
    """Registry per risentire delle funzioni usate nel DSL (es. +, concat, log)."""
    def resolve(self, name: str):
        # Esempio di funzioni registrate
        registry = {
            "print_info": lambda msg: f"[LOG] Executed: {msg}",
        }
        if name in registry:
            return registry[name]
        raise ValueError(f"Function {name} not found")


# --- 2. PIPELINE PRINCIPALE ---
async def main():
    # A. Definizione del codice DSL
    # Combina definizioni di contesto e un'operazione matematica/logica
    dsl_code = """
    {
        selected: "src/infrastructure/presentation/console.py";
        aaa: "sdsod";
        a: 10;
        b: 10 + a;
    }
    """

    print("=== 1. PARSING DSL -> AST ===")
    parser = Parser()
    ast = parser.parse(dsl_code)
    print("AST Generato con successo!\n")

    print("=== 2. COMPILAZIONE AST -> DAG DEFINITION ===")
    compiler = Compiler()
    dag_def = compiler.compile(ast, name="my_pipeline")
    print(f"Nome DAG: {dag_def.name}")
    print(f"Context compilato: {dag_def.context}\n")

    print("=== 3. CREAZIONE DEL GRAFO (DAG) ===")
    dag = Dag(dag_def)
    print(f"Nodi di esecuzione (Task) trovati: {len(dag.nodes)}")
    print(f"Variabili di contesto caricate: {list(dag.definition.context.keys())}\n")

    print("=== 4. ESECUZIONE TRAMITE DAG RUNNER ===")
    registry = DummyRegistry()
    runner = DagRunner(registry=registry)

    # Registra il DAG nel runner
    runner.register(dag)

    # Esegue il DAG (crea la sessione e valuta le espressioni)
    session = await runner.run("my_pipeline")

    print("\n=== 5. RISULTATI NEL CONTESTO FINALE ===")
    final_context = session.context.data
    
    print(f"selected : {final_context.get('selected')}")
    print(f"aaa      : {final_context.get('aaa')}")
    print(f"a        : {final_context.get('a')}")
    print(f"b (10+a) : {final_context.get('b')}")

    # Pulizia della sessione
    runner.close_session(session.id)


# --- 3. AVVIO DEL LOOP ASINCRONO ---
if __name__ == "__main__":
    asyncio.run(main())