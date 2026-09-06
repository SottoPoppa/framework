from collections.abc import Mapping, MutableMapping, Sequence
MISSING = object()
class DataPathError(KeyError): pass

def resolve(root, path, *, default=MISSING):
    cur = root
    try:
        for part in filter(None, path.split('.')):
            if isinstance(cur, Mapping): cur = cur[part]
            elif isinstance(cur, Sequence) and not isinstance(cur, (str, bytes, bytearray)): cur = cur[int(part)]
            else: cur = getattr(cur, part)
        return cur
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
        if default is not MISSING: return default
        raise DataPathError(path) from exc

def exists(root, path): return resolve(root, path, default=MISSING) is not MISSING

def publish(root: MutableMapping, path, value):
    parts = [x for x in path.split('.') if x]
    if not parts: raise DataPathError(path)
    cur = root
    for part in parts[:-1]:
        if not isinstance(cur.get(part), MutableMapping): cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value

def delete(root, path):
    parts = [x for x in path.split('.') if x]; cur = root
    for part in parts[:-1]: cur = cur[part]
    return cur.pop(parts[-1])
