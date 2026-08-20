import itertools
import re
from urllib.parse import parse_qs, urlparse


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
