import linecache
import re
import traceback
from typing import Any


_SENSITIVE_KEYS = {"password", "passphrase", "secret", "token", "api_key", "authorization"}


def safe_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Prepara un valore per il log senza esporre segreti o payload enormi."""
    if key.casefold() in _SENSITIVE_KEYS:
        return "<redacted>"
    if depth > 8:
        return "<nested>"
    if isinstance(value, dict):
        return {
            str(item_key): safe_value(item_value, key=str(item_key), depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [safe_value(item, depth=depth + 1) for item in value]
    if hasattr(value, "sid") and hasattr(value, "_session_data_store"):
        details = {"session_id": str(value.sid)}
        snapshot = value._session_data_store.get(value.sid)
        authentication = snapshot.get("authentication", {}) if snapshot else {}
        if isinstance(authentication, dict):
            actor = (
                authentication.get("user_id")
                or authentication.get("username")
                or authentication.get("email")
            )
            user = authentication.get("user", {})
            if actor is None and isinstance(user, dict):
                actor = user.get("id") or user.get("username") or user.get("email")
            if actor is not None:
                details["actor"] = str(actor)
        return details
    if hasattr(value, "id") and hasattr(value, "context"):
        return {"session_id": str(value.id)}
    if callable(value):
        return {
            "callable": getattr(value, "__qualname__", repr(value)),
        }
    if hasattr(value, "get_name") and hasattr(value, "done"):
        return {
            "task": value.get_name(),
            "done": value.done(),
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value if not isinstance(value, str) else value[:500]
        return text
    return repr(value)[:500]


def source_context(filename: str, lineno: int, radius: int = 2) -> str:
    """Restituisce le righe attorno al punto indicato nel sorgente."""
    first = max(1, lineno - radius)
    last = lineno + radius
    context = []
    for number in range(first, last + 1):
        source_line = linecache.getline(filename, number)
        if source_line:
            marker = ">" if number == lineno else " "
            context.append(f"{marker} {number}: {source_line.rstrip()}")
    return "\n".join(context)


def exception_location(exception: BaseException) -> dict[str, Any]:
    """Estrae causa e posizione di un'eccezione per il tracing applicativo."""
    declared_location = getattr(exception, "location", {})
    if not isinstance(declared_location, dict):
        declared_location = {}
    details = {
        "exception_type": type(exception).__name__,
        "exception_message": str(exception),
        **traceback_location(exception.__traceback__),
    }
    details.update(declared_location)
    return details


def traceback_location(tb: Any) -> dict[str, Any]:
    """Estrae file, riga, funzione e contesto dall'ultimo frame noto."""
    if tb is None:
        return {}
    frames = traceback.extract_tb(tb)
    if not frames:
        return {}
    frame = frames[-1]
    return {
        "source_file": frame.filename,
        "source_line": frame.lineno,
        "source_function": frame.name,
        "source_code": frame.line,
        "source_context": source_context(frame.filename, frame.lineno),
    }


def _failure_error(error: Any) -> tuple[str, str, dict[str, Any]]:
    if isinstance(error, tuple):
        if len(error) == 1:
            value = error[0]
            error_type, message, details = _failure_error(value)
            return error_type, message, details
        return "tuple", "; ".join(str(value) for value in error), {}
    if isinstance(error, dict):
        message = error.get("message") or error.get("error") or str(error)
        details = {
            key: error[key]
            for key in ("code", "path")
            if key in error
        }
        return str(error.get("code") or "dict"), str(message), details
    return type(error).__name__, str(error), {}


def failure_location(failure: Any) -> dict[str, Any]:
    """Estrae causa e posizione da una Failure, anche senza traceback."""
    error_type, error_message, error_details = _failure_error(failure.error)
    details = {
        "error_type": error_type,
        "error_message": error_message,
        **error_details,
    }
    if not failure.traceback:
        return details
    matches = re.findall(r'File "([^"]+)", line (\d+), in (.+)', failure.traceback)
    if not matches:
        return details
    filename, lineno, function = matches[-1]
    lines = failure.traceback.splitlines()
    source_code = next(
        (
            lines[index + 1].strip()
            for index, line in enumerate(lines[:-1])
            if f'File "{filename}", line {lineno}, in {function}' in line
            and index + 1 < len(lines)
            and lines[index + 1][:1].isspace()
        ),
        None,
    )
    return {
        **details,
        "exception_type": details["error_type"],
        "exception_message": details["error_message"],
        "source_file": filename,
        "source_line": int(lineno),
        "source_function": function,
        "source_code": source_code,
        "source_context": source_context(filename, int(lineno)),
    }
