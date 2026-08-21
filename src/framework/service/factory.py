import re
from urllib.parse import quote
from jinja2 import Environment, meta, nodes
import asyncio 
import signal

import framework.service.scheme as scheme
import framework.service.flow as flow

class Repository:
    def __init__(self, **constants):
        self.location = {k.lower(): v for k, v in constants.get('location', {}).items()}
        self.actions = constants.get('actions', {})
        self.schema = constants.get('model')
        self.mapper = constants.get('mapper', {})

    def _map_provider_data(self, data, profile):
        """Converte i nomi del provider nei nomi canonici del modello."""
        if isinstance(data, list):
            return [self._map_provider_data(item, profile) for item in data]
        if not isinstance(data, dict) or not isinstance(self.mapper, dict):
            return data

        profile_key = str(profile).lower()
        mapping = {}
        for model_key, provider_keys in self.mapper.items():
            if not isinstance(provider_keys, dict):
                continue
            mapping.update({
                model_key: source
                for name, source in provider_keys.items()
                if str(name).lower() == profile_key
            })

        mapped = dict(data)
        for model_key, provider_path in mapping.items():
            value = scheme.get(data, provider_path)
            if value is not None:
                mapped = scheme.put(mapped, model_key, value)
        return mapped

    def get_requirements(self, template_str):
        """
        Estrae i requisiti dal template analizzando l'albero sintattico (AST) di Jinja2.
        Più robusto: supporta notazione a parentesi [] e ignora scope e cicli interni.
        """
        try:
            if not template_str or not isinstance(template_str, str) or '{' not in template_str:
                return []
            jinja_env = Environment()
            ast = jinja_env.parse(template_str)
            valid_roots = meta.find_undeclared_variables(ast)
            paths = set()
            
            def visit(node):
                if isinstance(node, nodes.Name):
                    return node.name if node.name in valid_roots else None
                elif isinstance(node, nodes.Getattr):
                    base = visit(node.node)
                    if base:
                        return f"{base}.{node.attr}"
                elif isinstance(node, nodes.Getitem):
                    base = visit(node.node)
                    if base and isinstance(node.arg, nodes.Const) and isinstance(node.arg.value, str):
                        return f"{base}.{node.arg.value}"
                elif isinstance(node, nodes.Call):
                    return visit(node.node)
                return None

            def traverse(node):
                path = visit(node)
                if path:
                    paths.add(path)
                for child in node.iter_child_nodes():
                    traverse(child)

            traverse(ast)
            
            cleaned_paths = set()
            for p in paths:
                if p.endswith('.items') or p.endswith('.keys') or p.endswith('.values'):
                    cleaned_paths.add(p.rsplit('.', 1)[0])
                else:
                    cleaned_paths.add(p)
                    
            final_paths = set(cleaned_paths)
            for p in cleaned_paths:
                for p2 in cleaned_paths:
                    if p != p2 and p2.startswith(p + '.'):
                        final_paths.discard(p)

            return sorted(final_paths)
        except Exception:
            # Fallback
            return re.findall(r'\{(\w+)\}', template_str)

    def select(self, templates, data):
        """
        Sceglie il miglior template in base alla densità di requisiti soddisfatti.
        Prioritizza i template che utilizzano percorsi più profondi (più specifici).
        """
        best_t, max_score = None, -1
        
        for t in (templates if isinstance(templates, list) else [templates]):
            reqs = self.get_requirements(t)
            score = 0
            
            if not reqs:
                score = 0.1 # Template statico
            else:
                # Verifichiamo quali requisiti sono presenti nei dati tramite il servizio Scheme
                met = [r for r in reqs if scheme.get(data, r) is not None]
                if len(met) == len(reqs):
                    # Calcoliamo lo score: numero requisiti ponderato per la profondità dei path
                    # Ogni segmento del path conta come precisione aggiuntiva
                    score = sum(r.count('.') + 1 for r in reqs)
                    # Bonus per l'utilizzo di logica complessa (cicli, ecc)
                    score += 0.5 if '{%' in t else 0
                else:
                    score = -1
            
            if score > max_score:
                max_score, best_t = score, t
                
        return best_t if max_score >= 0 else None

    async def results(self, transaction, profile):
        """Hook opzionale per post-processing."""
        if not self.schema:
            return transaction

        data = flow.output(transaction) if flow.is_result(transaction) else transaction
        data = self._map_provider_data(data, profile)
        model = (
            scheme.schemes.get(self.schema)
            if isinstance(self.schema, str)
            else self.schema
        )
        if not model:
            return transaction

        normalized = await scheme.normalize(data, model)
        if normalized["errors"]:
            return flow.error(normalized["errors"])
        return flow.success(normalized["data"])

    async def parameters(self, **inputs):
        """Prepara i parametri della rotta risolvendo il template tramite Scheme."""
        
        operation = inputs.get('operation')
        profile = inputs.get('provider')
        action = self.actions.get(operation, {})
        
        # 1. Definizione Payload e Logica
        payload_fn = action.get('payload')
        payload = payload_fn(**inputs.get('payload', {})) if callable(payload_fn) else inputs.get('payload', {})
        
        logic_fn = action.get('logic')
        process = logic_fn(**inputs) if callable(logic_fn) else inputs
        
        # 2. Selezione dinamica del Template
        combined = {**inputs, **payload, **process}
        templates = self.location.get(profile, [])
        
        template = self.select(templates, combined)

        
        if not template:
            raise ValueError(f"Nessun template compatibile trovato per {profile}. Dati: {list(combined.keys())}")

        # 3. Formattazione e Encoding
        path = await scheme.format(template, **combined)
        if '?' in path:
            base, query = path.split('?', 1)
            path = f"{base}?{quote(query, safe='=&%')}"
        else:
            path = quote(path)
            
        return process | {
            'location': path, 
            'provider': profile, 
            'payload': payload, 
            'filter': inputs.get('filter', {})
        }