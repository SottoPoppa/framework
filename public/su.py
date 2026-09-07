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
            "print_info": lambda msg: (print(f"[INFO]: {msg}"), msg)[1],
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
        int:lt := 22;
        b: 10 + a;
        zio: a |> print_info; 
        g:print_info("ciao!!!!!!!!!!!!!!!");
        uu() -> print_info(ss);
        ss() -> print_info(b+10);
    }
    """

    dsl_code = """
        any:port_schema := "presentation";
any:adapter_schema := "presentation_adapter";

presentation:configuration := {
    "presentation_type": "rest_api";
    "cors_policy": {
        "enabled": false;
    };
    "security_and_waf": {
        "tls_enabled": false;
        "csrf_protection": false
    };
    "authentication_guards": {
        "auth_required": false
    }
};
type:route := {
    "path": { "type": "string" };
    "method": { "type": "string"; "default": "GET" };
    "type": { "type": "string" "allowed": ["view","authenticate","terminate","activate","reinstate"] };
    "view": { "type": "string"; "default": "" };
    "controller": { "type": "string"; "default": "" };
};

type:policy := {
    "effect": { "type": "string"; "regex": "^(allow|deny)$"; "default": "deny" };
    "target": { 
        "schema": { "action": { "type": "string" }; "resource": { "type": "string" }; "location": { "type": "string" }; "context": { "type": "dict" } }; 
        "default": { "action": ""; "resource": ""; "location": ""; "context": {} };
    };
    "description": { "type": "string"; "default": "" };
    "condition": { "default": true };
};

type:user := {
  "identifier": { "type": "string" };
  "username": { "type": "string" };
  "role": { "type": "string"; "regex": "^(admin|user|guest)$" };
  "avatar": { "type": "string" };
};

type:role := {
    "id": { "type": "string" };
    "name": { "type": "string" };
    "description": { "type": "string" };
    "resources": { "type": "list"; "schema": { "type": "string" } };
};

roles:{
    role:admin := {
        id:"role-1";
        name:"admin";
        description:"admin";
        resources:["all"];
    };
    role:user := {
        id:"role-2";
        name:"user";
        description:"user";
        resources:["all"];
    };
    role:guest := {
        id:"role-3";
        name:"guest";
        description:"guest";
        resources:["application/view/page/auth/login.xml"];
    };
}

routes: {
    route:GET_INDEX := { path:"/"; method:"GET"; "type":"view"; view:"terminal.xml"; controller:"terminal" };
    route:GET_ECOMMERCE := { path:"/shop"; method:"GET"; "type":"view"; view:"ecommerce.xml"; controller:"catalog" };
    route:GET_PROFILE := { path:"/profile"; method:"GET"; "type":"view"; view:"profile.xml" };
    // Auth
    route:GET_LOGIN := { path:"/login"; method:"GET"; "type":"view"; view:"login.xml" };
    route:GET_LOGOUT := { path:"/logout"; method:"GET"; "type":"view"; view:"auth/logout.xml" };
    route:POST_LOGIN := { path:"/login"; method:"POST"; "type":"authenticate"; view:"auth/login.xml" };
    route:POST_LOGOUT := { path:"/logout"; method:"POST"; "type":"terminate"; view:"auth/logout.xml" };
    route:GET_SIGNUP := { path:"/signup"; method:"GET"; "type":"view"; view:"auth/signup.xml" };
    route:POST_SIGNUP := { path:"/signup"; method:"POST"; "type":"activate"; };
    route:GET_RECOVERY := { path:"/recovery"; method:"GET"; "type":"reinstate"; view:"auth/signup.xml" };
    route:POST_RECOVERY := { path:"/recovery"; method:"POST"; "type":"reinstate"; };
    // Admin
    route:GET_ADMIN := { path:"/admin"; method:"GET"; "type":"view"; view:"admin.xml" };
    // Error
    route:GET_ERROR_404 := { path:"/404"; method:"GET"; "type":"view"; view:"error/404.xml" };
    // Twitch
    route:GET_BROWSER := { path:"/browse"; method:"GET"; "type":"view"; view:"twitch_browse.xml" };
    route:GET_HOME := { path:"/home"; method:"GET"; "type":"view"; view:"twitch_home.xml" };
    route:GET_USER_PROFILE := { path:"/user/{id}"; method:"GET"; "type":"view"; view:"twitch_channel.xml" };
    route:GET_TRIS := { path:"/tris"; method:"GET"; "type":"view"; view:"tris.xml"; controller:"tris" };
}

policies: {
    policy:GET_ALLOW_PATH := {
        effect:"allow";
        target: { action: "GET"; };
        description:"Allow GET method for resources in guest role"; 
        condition: (@resource in roles.guest.resources) & (@action == "GET");
    };
    policy:GET_ALLOW_ALL := {
        effect:"allow";
        target: { action: "GET"; };
        description:"Allow all GET requests";
        condition: @action == "GET";
    };
    policy:POST_ALLOW_ALL := {
        effect:"allow";
        target: { action: "POST"; };
        description:"Allow all POST requests";
        condition: @action == "POST";
    };
}
    

requirement:REQUIRES := {

}


rules : {
    "/": [policies.GET_ALLOW_ALL];
    "/shop": [policies.GET_ALLOW_ALL];
    "/profile": [policies.GET_ALLOW_PATH];
    "/login": [policies.GET_ALLOW_ALL,policies.POST_ALLOW_ALL];
    "/logout": [policies.GET_ALLOW_PATH];
    "/signup": [policies.GET_ALLOW_ALL,policies.POST_ALLOW_ALL];
    "/recovery": [policies.GET_ALLOW_ALL,policies.POST_ALLOW_ALL];
    "/admin": [policies.GET_ALLOW_PATH];
    "/browse": [policies.GET_ALLOW_ALL];
    "/home": [policies.GET_ALLOW_ALL];
    "/user/{id}": [policies.GET_ALLOW_ALL];
    "/tris": [policies.GET_ALLOW_ALL];
    "/static/js/dsl.js": [policies.GET_ALLOW_ALL];
    //"/404": [policies.GET_ALLOW_ALL];
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

    for k, v in final_context.items():
        print(f"{k:<10} : {v}")

    # Pulizia della sessione
    runner.close_session(session.id)


# --- 3. AVVIO DEL LOOP ASINCRONO ---
if __name__ == "__main__":
    asyncio.run(main())