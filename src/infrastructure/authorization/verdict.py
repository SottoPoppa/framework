imports = {
    #'persistence': 'framework/port/authorization.py',
}

import json
from typing import Dict, Any
import mistql # Motore di query sicuro
import asyncio
# La classe adapter gestisce il caricamento e la valutazione delle policy
class adapter():
    
    def __init__(self, **constants):
        self.config = constants.get('config')
        self._policies: Dict[str, Dict] = {}
        self._data_store: Dict[str, Any] = {}

    # ------------------------------
    # POLICY COMPILATION & LOADING
    # ------------------------------

    def _compile(self, policy_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Placeholder per la pre-elaborazione delle policy.
        """
        return policy_data

    def load_policy(self, name: str, policy_data: Dict[str, Any]):
        print(policy_data,name)
        """Carica una policy pre-compilata nella memoria."""
        '''if isinstance(policy_data, list):
            policy_data = {"rules": policy_data}
        compiled_policy = self._compile(policy_data)'''
        self._policies[name] = policy_data

    # ------------------------------
    # POLICY EVALUATION (MistQL)
    # ------------------------------

    def _evaluate_rule(self, rule: Dict, context: Dict[str, Any]) -> bool:
        """
        Valuta una singola regola usando l'espressione MistQL contenuta in 'condition'.
        """
        effect = rule.get("effect", "deny")
        condition_mistql_string = rule.get("condition") 
        
        # 1. Gestione assenza condizione
        if condition_mistql_string is None:
            return effect == "allow"

        safe_context = context

        # ➤ DEBUG STEP: log condition before evaluation
        print("\n🧪 Evaluating Rule")
        print("Effect:", effect)
        print("Condition:", condition_mistql_string)
        print("Context:", json.dumps(safe_context, indent=2))

        # 2. Evaluation con MistQL
        try:
            # MistQL valuta l'espressione (stringa) sul dizionario di contesto (safe_context)
            result = mistql.query(condition_mistql_string, safe_context)
            
            print(f"➡️ Result: {result} (Type: {type(result).__name__})")
        except Exception as e:
            # Cattura errori di sintassi MistQL o errori di runtime
            print("\n❌ MISTQL EVALUATION ERROR")
            print("---------------------------------")
            print("Rule:", condition_mistql_string)
            print("Error:", str(e))
            print("---------------------------------\n")
            return False

        # 3. Restituisce il risultato della decisione
        return bool(result) and effect == "allow"

    def check(self, policy_name: str, input_data: Dict[str, Any]) -> bool:
        """
        Esegue la valutazione policy su un input. Ritorna True/False (first match allow).
        """
        if policy_name not in self._policies:
            raise Exception(f"Policy '{policy_name}' non trovata")

        # Crea il contesto completo unendo l'input e i dati di supporto
        context = {
            "input": input_data,
            "data": self._data_store,
        }

        '''for rule in self._policies[policy_name].get("rules", []):
            if self._evaluate_rule(rule, context):
                return True'''
        
        return self._evaluate_rule(self._policies[policy_name], context)

    # ------------------------------
    # MOCK PERSISTENCE LAYER
    # ------------------------------

    async def load_policies(self):
        import framework.core.language as language
        for domain,name in self.config.get('project').get('policy',{}).items():
            text = await language.resource(path=f"application/policy/{domain}/{name}")
            ok = await language.convert(text,dict,'toml')
            policies = ok.get('policies')
            data = ok.get('store')
            self._data_store |= data
            for policy in policies:
                name = policy.get('id')
                self.load_policy(name, policy)