import inspect
import json
import framework.port.actuation as actuation
import framework.core.flow as flow


class Adapter(actuation.Port):
    """Adapter di attuazione che mappa ed esegue chiamate di funzione (Function Calling)

    generate da modelli LLM/AI. Traduce payload JSON strutturati in comandi concreti
    o invocazioni di funzioni Python registrate.
    """

    capabilities = {
        "feedback_loop": True,
        "async_execution": True,
        "emergency_stop": True,
        "protocols": ["JSON-RPC", "FunctionCalling", "REST"],
    }

    def __init__(self, name: str = "function_calling_actuator"):
        self.name = name
        self._registry: dict[str, callable] = {}
        self._last_state: dict = {}
        self._enabled_features: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Ciclo di Vita (Start / Stop)
    # ------------------------------------------------------------------

    async def start(self, *services, **constants):
        """Inizializza il registry delle funzioni ed eventuali collegamenti."""
        return True

    async def stop(self, *services, **constants):
        """Svuota il registro delle funzioni registrate."""
        self._registry.clear()
        return True

    # ------------------------------------------------------------------
    # Registrazione dei Tool/Funzioni
    # ------------------------------------------------------------------

    def register_function(self, name: str, func: callable):
        """Registra un metodo o funzione Python invocabile dal Function Calling."""
        self._registry[name] = func

    def get_openai_tools_schema(self) -> list[dict]:
        """Restituisce lo schema dei tool/funzioni registrati nel formato standard OpenAI/Ollama."""
        tools = []
        for name, func in self._registry.items():
            doc = inspect.getdoc(func) or "Nessuna descrizione disponibile."
            sig = inspect.signature(func)
            
            properties = {}
            required = []

            for param_name, param in sig.parameters.items():
                if param_name in ("self", "session", "services", "constants"):
                    continue
                
                # Mappatura tipo Python -> JSON Schema
                type_map = {int: "integer", float: "number", str: "string", bool: "boolean", dict: "object", list: "array"}
                param_type = type_map.get(param.annotation, "string")

                properties[param_name] = {
                    "type": param_type,
                    "description": f"Parametro {param_name}"
                }
                if param.default == inspect.Parameter.empty:
                    required.append(param_name)

            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": doc,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            })
        return tools

    # ------------------------------------------------------------------
    # Implementazione del Contratto Actuator.Port
    # ------------------------------------------------------------------

    async def execute(self, *services, **constants):
        """Esegue una funzione richiesta dal Function Calling dell'LLM.
        
        Parametri attesi in **constants:
        - function_name: nome della funzione da invocare.
        - arguments: dizionario dei parametri o stringa JSON da decodificare.
        - tool_call_id: id della chiamata generata dall'LLM (opzionale).
        """
        function_name = constants.get("function_name")
        arguments = constants.get("arguments", {})
        tool_call_id = constants.get("tool_call_id")

        if not function_name:
            return {"status": "error", "message": "Parametro 'function_name' mancante."}

        # Decodifica se gli argomenti sono arrivati come stringa JSON
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as e:
                return {"status": "error", "message": f"JSON non valido: {str(e)}"}

        func = self._registry.get(function_name)
        if not func:
            return {
                "status": "error",
                "message": f"Funzione '{function_name}' non trovata nel registro dell'attuatore."
            }

        try:
            # Esecuzione asincrona o sincrona della funzione target
            if inspect.iscoroutinefunction(func):
                result = await func(*services, **arguments)
            else:
                result = func(*services, **arguments)

            execution_payload = {
                "status": "success",
                "tool_call_id": tool_call_id,
                "function_name": function_name,
                "result": result
            }
            self._last_state[function_name] = execution_payload
            return execution_payload

        except Exception as e:
            return {
                "status": "error",
                "tool_call_id": tool_call_id,
                "function_name": function_name,
                "message": f"Errore durante l'esecuzione: {str(e)}"
            }

    async def set_state(self, *services, **constants):
        """Imposta lo stato di una feature o proprietà passando per un tool dedicato."""
        key = constants.get("key")
        value = constants.get("value")
        if key:
            self._last_state[key] = value
            return {"status": "updated", "key": key, "value": value}
        return {"status": "ignored"}

    async def get_state(self, *services, **constants):
        """Restituisce lo stato dell'ultima esecuzione o stato registrato."""
        return self._last_state

    async def toggle_feature(self, *services, **constants):
        """Abilita o disabilita una specifica funzione del registro."""
        feature_name = constants.get("feature_name")
        enabled = constants.get("enabled", True)
        if feature_name:
            self._enabled_features[feature_name] = enabled
            return {"feature": feature_name, "enabled": enabled}
        return {"status": "error", "message": "feature_name mancante"}