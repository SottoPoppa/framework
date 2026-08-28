import re
import json
try:
    import tomllib as tomli
except ImportError:
    import tomli
import hashlib
import copy
from urllib.parse import urlparse, urlencode
from jinja2 import Environment, meta
from cerberus import Validator
from collections.abc import Mapping

jinja_env = Environment()

mappa = {
    (str,dict,''): lambda v: v if isinstance(v, dict) else {},
    (dict,dict,''): lambda v: v,
    (str,str,''): lambda v: v,
    (str,dict,'json'): lambda v: json.loads(v) if isinstance(v, str) else v if isinstance(v, dict) else {},
    (dict,dict,'json'): lambda v: v,
    (dict,str,'json'): lambda v: json.dumps(v,indent=4) if isinstance(v, dict) else v if isinstance(v, str) else '',
    (str,str,'json'): lambda v: v,
    (str,str,'hash'): lambda v: hashlib.sha256(v.encode('utf-8')).hexdigest() if isinstance(v, str) else '',
    (str,dict,'toml'): lambda content: tomli.loads(content) if isinstance(content, str) else content if isinstance(content, dict) else {},
    (dict,dict,'toml'): lambda v: v,
    (dict,str,'toml'): lambda data: tomli.dumps(data) if isinstance(data, dict) else data if isinstance(data, str) else '',
    (str,str,'toml'): lambda v: v,
    (str,int,''): lambda v: int(v) if isinstance(v, str) else v if isinstance(v, int) else 0,
    (int,str,''): lambda v: str(v) if isinstance(v, int) else v if isinstance(v, str) else '',
    (str,bool,''): lambda v: True if v.lower() == 'true' else False,
    (bool,str,''): lambda v: str(v) if isinstance(v, bool) else v if isinstance(v, str) else '',
    (str,list,''): lambda v: [v],
    (type(None),list,''): lambda v: [],
}

async def convert(target, output,input=''):
    try:
        if type(target) == output:
            return target
        return mappa[(type(target),output,input)](target)
    except KeyError:
        raise ValueError(f"Conversione non supportata: {type(target)} -> {type(output)}:{output} da {input}")
    except Exception as e:
        raise ValueError(f"Errore conversione: {e}")

async def format(target, **constants):
    """Formatta una stringa usando Jinja2 e l'environment condiviso (jinja)."""
    try:
        if not target or not isinstance(target, str) or '{' not in target:
            return target
        template = jinja_env.from_string(target)
        return template.render(constants)
    except Exception as e:
        raise ValueError(f"Errore formattazione: {e}")

def _get_missing_requirements(pattern: str, value: str) -> str:
    # 1. Normalizzazione (Fondamentale per i backslash dello schema)
    norm_p = pattern.replace("\\\\", "\\")
    
    # 2. Registry di regole atomiche
    # Nota: L'ordine conta! Più è specifica la regola, più deve stare in alto.
    rules = [
        # Caratteri speciali e classi
        (r"\[a-z\]", "lowercase letter", r"[a-z]"),
        (r"\[A-Z\]", "uppercase letter", r"[A-Z]"),
        (r"\\d|\[0-9\]", "number", r"\d"),
        (r"\[@\$!%\*\?&\]", "special char", r"[@$!%*?&]"),
        (r"\\s", "space", r"\s"),
        
        # Quantificatori (Lunghezza)
        (r"\{(\d+),(\d+)\}", "between {0} and {1} chars", None),
        (r"\{(\d+),\}", "at least {0} chars", None),
        (r"\{(\d+)\}", "exactly {0} chars", None),
        
        # Casi di "solo" o "composto da"
        (r"\^\[a-zA-Z\]\+\$", "only letters", r"^[a-zA-Z]+$"),
        (r"\^\\d\+\$", "only digits", r"^\d+$"),
    ]
    
    missing = []
    
    for meta_p, label, test_p in rules:
        match = re.search(meta_p, norm_p)
        if match:
            args = match.groups()
            msg = label.format(*args) if args else label
            
            # Logica di validazione
            if test_p:
                if not re.search(test_p, value):
                    missing.append(msg)
            elif args:
                # Gestione lunghezze dinamiche
                val_len = len(value)
                if len(args) == 1: # {n} o {n,}
                    min_val = int(args[0])
                    if val_len < min_val:
                        missing.append(msg)
                elif len(args) == 2: # {n,m}
                    min_v, max_v = int(args[0]), int(args[1])
                    if not (min_v <= val_len <= max_v):
                        missing.append(msg)

    # 3. Pulizia duplicati (se una regex ha più riferimenti allo stesso set)
    unique_missing = list(dict.fromkeys(missing))
    
    if not unique_missing:
        # Se la regex ha fallito ma non abbiamo trovato regole specifiche mappate
        return "invalid format"
        
    return f"missing {', '.join(unique_missing)}"

def _format_validation_errors(errors: dict, schema: dict, data: dict) -> list:
    result = []
    for field, field_errors in errors.items():
        for error in field_errors:
            # Se l'errore riguarda una regex, usiamo la nostra logica locale
            if "value does not match regex" in error:
                pattern = schema.get(field, {}).get("regex", "")
                value = data.get(field, "")
                
                # Sostituiamo la chiamata API con la logica locale
                message = _get_missing_requirements(pattern, str(value))
                
                result.append({"field": field, "message": message})
            else:
                # Altri tipi di errori (es: required, type, ecc.)
                result.append({"field": field, "message": error})
    return result

async def normalize(value, schema, mode='full'):
    if isinstance(value, list):
        results = [await normalize(item, schema, mode) for item in value]
        # Se ci sono errori in qualche elemento, aggregali
        all_data = [r["data"] for r in results if r["data"] is not None]
        all_errors = [r["errors"] for r in results if r["errors"] is not None]
        return {"data": all_data, "errors": all_errors if all_errors else None}

    value = value or {}
    if not isinstance(schema, Mapping):
        raise TypeError("Lo schema deve essere un dizionario valido per Cerberus.", schema)
    if not isinstance(value, Mapping):
        # Se non è una mappa e non era una lista, allora è un errore di tipo
        return {"data": None, "errors": [{"field": "_root", "message": "Expected dict or list"}]}

    processed_value = value

    for field_name, field_rules in schema.copy().items():
        val = processed_value.get(field_name)
        if 'default' in field_rules:
            func_name = field_rules['default']
            if 'time.now.utc()' == func_name:
                from datetime import datetime
                processed_value[field_name] = str(datetime.now())
            if 'uuid.uuid4()' == func_name:
                import uuid
                processed_value[field_name] = str(uuid.uuid4())
        if isinstance(field_rules, dict) and 'function' in field_rules:
            func_name = field_rules['function']
            if func_name == 'generate_identifier':
                if field_name not in processed_value:
                    pass
            elif func_name == 'time_now_utc':
                processed_value[field_name] = "ciao"
                if field_name not in processed_value:
                    processed_value[field_name] = "ciao"
                    pass
        if isinstance(field_rules, dict) and "convert" in field_rules:
            convert_name = field_rules["convert"]
            if field_name in processed_value:
                processed_value[field_name] = await convert(val, convert_name)
            schema[field_name].pop("convert")

        if isinstance(field_rules, dict) and "comment" in field_rules:
            schema[field_name].pop("comment")

    v = Validator(schema, allow_unknown=False,purge_unknown=True)
    if not v.validate(processed_value):
        return {"data": None, "errors": _format_validation_errors(v.errors, schema, processed_value)}

    return {"data": v.document, "errors": None}

def transform(data_dict, mapper, values, input, output):
    """ Trasforma un set di costanti in un output mappato. """
    def find_matching_keys(mapper, target_dict):
        if not isinstance(mapper, dict) or not isinstance(target_dict, dict):
            return None
        target_keys = set(target_dict.keys())
        for key in mapper.keys():
            if key in target_keys:
                return key
        return None
    translated = {}

    if not isinstance(data_dict, dict):
        raise TypeError("Il primo argomento deve essere un dizionario.")

    if not isinstance(mapper, dict):
        raise TypeError("'mapper' deve essere un dizionario.")

    if not isinstance(values, dict):
        raise TypeError("'values' deve essere un dizionario.")
    
    if not isinstance(input, dict):
        raise TypeError("'input' deve essere un dizionario.")
    
    if not isinstance(output, dict):
        raise TypeError("'output' deve essere un dizionario.")

    key = find_matching_keys(mapper,output) or find_matching_keys(mapper,input)
    for k, v in mapper.items():
        n1 = get(data_dict, k)
        n2 = get(data_dict, v.get(key, None))
        
        if n1:
            output_key = v.get(key, None)
            value = n1
            translated |= put2(translated, output_key, value, output)
        if n2:
            output_key = k
            value = n2
            translated |= put2(translated, output_key, value, output)

    fieldsData = data_dict.keys()
    fieldsOutput = output.keys()

    for field in fieldsData:
        if field in fieldsOutput:
            value = get(data_dict, field)
            translated |= put2(translated, field, value, output)

    return translated

def _get_next_schema(schema, key):
    if isinstance(schema, dict):
        if 'schema' in schema:
            if schema.get('type') == 'list': return schema['schema']
            if isinstance(schema['schema'], dict): return schema['schema'].get(key)
        return schema.get(key)
    return None

def route(url: dict, new_part: str) -> str:
    """
    Updates the URL's path and/or adds query parameters based on the input string.
    """
    url = copy.deepcopy(url)
    protocol = url.get("protocol", "http")
    host = url.get("host", "localhost")
    port = url.get("port")
    path = url.get("path", [])
    query_params = url.get('query', {})
    fragment = url.get("fragment", "")

    parsed_new_part = urlparse(new_part)

    if parsed_new_part.path:
        path = [p for p in parsed_new_part.path.split('/') if p]

    if parsed_new_part.query:
        [query_params.setdefault(k, []).append(v) for k, v in (param.split('=', 1) for param in parsed_new_part.query.split('&') if '=' in param)]
        for key, value in query_params.items():
            pass
    
    query_parts = []
    query_string = ""
    for key, values in query_params.items():
        if values:  # prendi solo l'ultimo elemento
            query_parts.append(f"{key}={values[-1]}")
    query_string = "&".join(query_parts)

    base_url = ""
    if path:
        base_url += "/" + "/".join(path)

    if query_string:
        base_url += f"?{query_string}"
    
    if fragment:
        base_url += f"#{fragment}"

    return base_url

def get(data, path, default=None):
    if not path:
        return data
    
    # Partition del path per separare la prima chiave dal resto
    key, _, rest = path.partition(".")
    
    # Regex per catturare pattern del tipo: nome[attr=valore] o *[attr=valore]
    # Gestisce opzionalmente apici singoli o doppi attorno al valore
    filter_match = re.match(r"([^\[]+)\[([^=]+)=[\"']?([^\"']+)[\"']?\]", key)
    
    if filter_match:
        key_base, attr, expected = filter_match.groups()
        
        # Identifica la sorgente del filtro
        if key_base == "*":
            target = data if isinstance(data, (list, tuple)) else []
        else:
            target = data.get(key_base, []) if isinstance(data, (dict, Mapping)) else []
            
        # Filtra gli elementi: cast a stringa per confronto robusto
        filtered = [x for x in target if isinstance(x, dict) and str(x.get(attr)) == expected]
        
        # Ricorsione: applica il 'rest' su ogni elemento filtrato
        results = [get(item, rest, default) for item in filtered]
        
        # Ritorna il risultato (o None/default se la lista è vuota)
        return results if results else default

    # Gestione Wildcard pura
    if key == "*":
        if isinstance(data, (list, tuple)):
            return [get(x, rest, default) for x in data]
        return default
        
    # Navigazione standard (Dict, Mapping, List, Attribute)
    try:
        if isinstance(data, (dict, Mapping)):
            value = data.get(key, default)
        elif isinstance(data, (list, tuple)) and key.lstrip("-").isdigit():
            idx = int(key)
            value = data[idx] if 0 <= idx < len(data) else default
        else:
            value = getattr(data, key, default)
            
        return get(value, rest, default) if rest else value
    except (IndexError, TypeError, ValueError, KeyError):
        return default

def put(data, path, value):
    if not path:
        return value
    
    res = copy.deepcopy(data)
    key, _, rest = path.partition(".")
    
    # --- GESTIONE BULK / FILTRO CON REGEX ---
    # La regex cattura: key_base, attr, expected
    # Supporta: key[attr=valore], key[attr='valore'], key[attr="valore"]
    filter_match = re.match(r"([^\[]+)\[([^=]+)=[\"']?([^\"']+)[\"']?\]", key)
    
    if key == "*" or filter_match:
        if not isinstance(res, list):
            # Se la struttura non è una lista, non possiamo filtrare: restituiamo il dato originale
            return data
        
        if key == "*":
            return [put(item, rest, value) for item in res]
        
        # Estrazione dati dalla regex
        key_base, attr, expected = filter_match.groups()
        
        # Applicazione filtro: aggiorna solo gli elementi che corrispondono
        return [
            put(item, rest, value) if str(item.get(attr)) == expected else item 
            for item in res
        ]

    # --- IDENTIFICAZIONE CHIAVE ---
    is_idx = key.lstrip("-").isdigit()
    idx = int(key) if is_idx else key

    # --- PROTEZIONE ACCESSO A LISTA CON STRINGA ---
    if isinstance(res, list) and not is_idx:
        return data

    # --- LOOK-AHEAD: CREAZIONE DINAMICA ---
    # Creazione nodo se la chiave non esiste
    if isinstance(res, dict) and key not in res:
        next_key, _, _ = rest.partition(".")
        is_next_idx = next_key.lstrip("-").isdigit()
        res[key] = [] if is_next_idx else {}
    
    elif isinstance(res, list):
        if not is_idx or idx >= 999: return data
        if idx >= len(res):
            res.extend([None] * (idx - len(res) + 1))
            # Decidiamo se creare un dizionario o una lista per il nuovo slot
            next_key, _, _ = rest.partition(".")
            res[idx] = [] if next_key.lstrip("-").isdigit() else {}

    # --- ESECUZIONE PUT RICORSIVA ---
    if isinstance(res, list):
        if idx >= len(res): return data
        res[idx] = put(res[idx], rest, value)
    elif isinstance(res, dict):
        res[key] = put(res.get(key), rest, value)
    else:
        # Se res è un tipo primitivo che non può contenere chiavi
        return data
        
    return res