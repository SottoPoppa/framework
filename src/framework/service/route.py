import itertools
import re
from urllib.parse import urlparse, parse_qs, urljoin

ROUTE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}


def normalize_path(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Il path della route deve essere una stringa non vuota")
    path = path.strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return re.sub(r"\{\$([a-zA-Z0-9_]+)\}", r"{\1}", path)


def split_url(url):
    """Restituisce i componenti dell'URL in una forma facilmente ricercabile."""
    full_url = str(url)
    parsed_url = urlparse(full_url)
    path = [part for part in parsed_url.path.split("/") if part]
    query = parse_qs(parsed_url.query, keep_blank_values=True)
    fragment = parse_qs(parsed_url.fragment, keep_blank_values=True)

    return {
        "full": full_url,
        "scheme": parsed_url.scheme,
        "netloc": parsed_url.netloc,
        "path": path,
        "query": query,
        "fragment": fragment,
    }


def compile_pattern(path):
    pattern = re.sub(r"\{([a-zA-Z0-9_]+)\}", r"(?P<\1>[^/]+)", path)
    return re.compile(f"^{pattern}$")


def register(routes, route):
    view = f"application/view/page/{route['view']}" if route.get("view") else None
    path = normalize_path(route.get("path") or (view.replace(".xml", "") if view else ""))
    method = route.get("method", "GET").upper()
    if method not in ROUTE_METHODS:
        raise ValueError(f"Metodo HTTP non supportato: {method}")
    entry = {
        **{key: route.get(key) for key in ("method", "type", "layout", "controller", "path")},
        "view": view,
        "pattern": compile_pattern(path),
    }
    routes.setdefault(path, {})[method] = entry
    return path, method, entry


def register_many(routes, route_items):
    for route in route_items:
        view = f"application/view/page/{route['view']}" if route.get("view") else None
        path = normalize_path(route.get("path") or (view.replace(".xml", "") if view else ""))
        matches = list(re.finditer(r"\{([a-zA-Z0-9_|]+)\}", path))
        option_sets = [match.group(1).split("|") for match in matches if "|" in match.group(1)]
        placeholders = [match.group(0) for match in matches if "|" in match.group(1)]
        combinations = itertools.product(*option_sets) if option_sets else [()]
        for combination in combinations:
            expanded = path
            for placeholder, value in zip(placeholders, combination):
                expanded = expanded.replace(placeholder, value, 1)
            register(routes, {**route, "path": expanded})
    return routes


def match(routes, path, method="GET"):
    path = normalize_path(path)
    method = method.upper()
    for methods in routes.values():
        entry = methods.get(method)
        if entry is None:
            continue
        route_match = entry["pattern"].match(path)
        if route_match:
            return entry, route_match.groupdict()
    return None, {}

import copy

def route(
    url: dict,
    new_part: str,
) -> str:
    """
    Aggiorna path/query di una URL.

    Restituisce la sola parte route:

        /users/10?active=true#details
    """

    url_data = copy.deepcopy(url)

    path = url_data.get(
        "path",
        [],
    )

    query_params = copy.deepcopy(
        url_data.get(
            "query",
            {},
        )
    )

    fragment = url_data.get(
        "fragment",
        "",
    )

    parsed = urlparse(new_part)

    if parsed.path:
        path = [
            part
            for part in parsed.path.split("/")
            if part
        ]

    if parsed.query:

        for param in parsed.query.split("&"):

            if "=" not in param:
                continue

            key, value = param.split(
                "=",
                1,
            )

            query_params.setdefault(
                key,
                [],
            ).append(value)

    query_parts = []

    for key, values in query_params.items():

        if values:
            query_parts.append(
                f"{key}={values[-1]}"
            )

    result = ""

    if path:
        result += "/" + "/".join(path)

    if query_parts:
        result += "?" + "&".join(query_parts)

    if fragment:
        result += f"#{fragment}"

    return result

def resolve_route(risorse, request_url, request_method, base_url=None,**kargs):
        
        try:
            # 1. Normalizzazione URL
            # Se request_url è relativo (es. "/home"), urljoin lo unisce a base_url
            full_url = urljoin(base_url, request_url) if base_url else request_url
            parsed = urlparse(full_url)
            
            # Pulizia del path: togliamo slash vuoti per la lista, ma manteniamo il path stringa per il match
            path_list = [p for p in parsed.path.split('/') if p]
            
            # Trasformiamo query e fragment in dizionari puliti
            query_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
            frag_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.fragment).items()}

            url_payload = {
                'url': full_url,
                'protocol': parsed.scheme,
                'host': parsed.hostname,
                'port': parsed.port,
                'path': path_list,
                'query': query_params,
                'fragment': frag_params
            }

            # 2. Ciclo di Matching (Aggiornato per supportare la struttura nidificata {path: {metodo: config}})
            for methods_dict in risorse.values():
                # Tutte le configurazioni per lo stesso path condividono lo stesso pattern
                # ne prendiamo una qualsiasi per eseguire il match del path
                first_config = next(iter(methods_dict.values()))
                match = first_config['pattern'].match(parsed.path)
                
                if match:
                    # Trovato il path, cerchiamo se il metodo richiesto è supportato
                    route_data = methods_dict.get(request_method.upper())
                    
                    if not route_data:
                        # Metodo non trovato per questo path specifico
                        continue
                        
                    # Recuperiamo i metadati
                    metadata = route_data.get('metadata', route_data)
                    
                    # Estrazione parametri dinamici dalla Regex (es. {'id': '123'})
                    dynamic_params = match.groupdict()
                    
                    return {
                        'metadata': metadata,
                        'params': dynamic_params,
                        'url_details': url_payload
                    }

            print(f"[-] No route matched for: {request_method} {parsed.path}")
            return None

        except Exception as e:
            print(f"[!] Resolve Error: {e}")
            return None