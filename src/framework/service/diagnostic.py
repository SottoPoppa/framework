import json
import traceback
import sys
import os
import platform
import socket
from datetime import datetime
from typing import Dict, Any, List, Optional
from contextlib import contextmanager
import time
import contextvars
import threading


# =====================================================================
# --- Utilities di Base ---
# =====================================================================

class DiagnosticEncoder(json.JSONEncoder):
    """JSONEncoder per serializzare oggetti complessi nei report diagnostici."""
    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def truncate_value(value: Any, max_str_len: int = 256, max_list_len: int = 20) -> Any:
    """Tronca stringhe e collezioni troppo grandi."""
    if isinstance(value, str):
        if len(value) > max_str_len:
            return f"{value[:max_str_len]}... [TRONCATA, L={len(value)}]"
        return value

    elif isinstance(value, (list, tuple, set)):
        if len(value) > max_list_len:
            truncated = list(value)[:max_list_len]
            return f"{truncated} ... [TRONCATA, N={len(value)}]"
        return list(value)

    elif isinstance(value, dict):
        return {k: truncate_value(v, max_str_len, max_list_len) for k, v in value.items()}

    return value


def _render_value(value: Any) -> str:
    """Rappresentazione compatta e leggibile di un valore di metadata
    (a differenza del repr() grezzo di Python)."""
    val = truncate_value(value, max_str_len=200)
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, cls=DiagnosticEncoder, ensure_ascii=False)
        except Exception:
            return str(val)
    if isinstance(val, str):
        return val
    return str(val)


# =====================================================================
# --- Analisi Exception ---
# =====================================================================

def get_system_info() -> Dict[str, Any]:
    """Raccoglie informazioni di sistema (opzionale, richiede psutil)."""
    try:
        import psutil
    except ImportError:
        return {"note": "psutil non installato, info di sistema non disponibili"}

    mem = psutil.virtual_memory()
    return {
        "hostname": socket.gethostname(),
        "process_id": os.getpid(),
        "cpu_cores": psutil.cpu_count(),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "ram_available_gb": round(mem.available / (1024**3), 2),
        "os_name": platform.platform(),
        "python_version": platform.python_version(),
    }


def analyze_traceback(tb) -> List[Dict[str, Any]]:
    """Estrae informazioni strutturate dal traceback."""
    frames = []
    current_tb = tb

    while current_tb is not None:
        frame = current_tb.tb_frame
        filename = frame.f_code.co_filename

        if "/usr/" in filename or "/lib/python" in filename:
            current_tb = current_tb.tb_next
            continue

        local_vars = {
            k: truncate_value(v)
            for k, v in frame.f_locals.items()
            if not k.startswith('_')
        }

        try:
            frame_summary = traceback.FrameSummary(
                filename,
                current_tb.tb_lineno,
                frame.f_code.co_name,
                lookup_line=True
            )
            code_line = frame_summary.line.strip() if frame_summary.line else "N/A"
        except Exception:
            code_line = "N/A"

        frames.append({
            "filename": filename,
            "line_number": current_tb.tb_lineno,
            "function": frame.f_code.co_name,
            "code_line": code_line,
            "local_variables": local_vars
        })

        current_tb = current_tb.tb_next

    return frames


def create_diagnostic_report(exc_info: tuple = None) -> Dict[str, Any]:
    """Genera un report diagnostico dettagliato per un'eccezione."""
    if exc_info:
        exc_type, exc_value, exc_traceback = exc_info
    else:
        exc_type, exc_value, exc_traceback = sys.exc_info()

    if exc_type is None:
        return {"status": "Nessuna eccezione attiva"}

    frames = analyze_traceback(exc_traceback)
    final_frame = frames[-1] if frames else {}

    report = {
        "timestamp": datetime.now().isoformat(),
        "exception": {
            "type": exc_type.__name__,
            "message": str(exc_value),
            "location": {
                "filename": final_frame.get("filename", "N/A"),
                "line_number": final_frame.get("line_number", 0),
                "function": final_frame.get("function", "N/A"),
                "code_line": final_frame.get("code_line", "N/A"),
            },
            "final_frame_variables": final_frame.get("local_variables", {}),
        },
        "traceback_frames": frames,
        "traceback_formatted": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    }

    return report


def save_diagnostic_report(report: Dict[str, Any], output_dir: str = ".diagnostics") -> str:
    """Salva il report diagnostico su file."""
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"diagnostic_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w') as f:
        json.dump(report, f, cls=DiagnosticEncoder, indent=2)

    return filepath


# =====================================================================
# --- Rendering dei log ---
# =====================================================================

COLOR_RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

LEVEL_COLORS = {
    "DEBUG":    "\033[37m",
    "INFO":     "\033[96m",
    "WARNING":  "\033[93m",
    "ERROR":    "\033[91m",
    "CRITICAL": "\033[95m",
}
LEVEL_ICONS = {
    "DEBUG":    "·",
    "INFO":     "ℹ",
    "WARNING":  "⚠",
    "ERROR":    "✖",
    "CRITICAL": "☠",
}

# Palette per i tag dei componenti: colori diversi da quelli dei livelli,
# assegnati in modo deterministico per nome così lo stesso componente ha
# sempre lo stesso colore in tutta la run.
_COMPONENT_PALETTE = [
    "\033[94m",  # blu
    "\033[92m",  # verde
    "\033[33m",  # giallo scuro
    "\033[36m",  # ciano scuro
    "\033[35m",  # viola
    "\033[97m",  # bianco
]

_COMPONENT_WIDTH = 12

_log_indent: contextvars.ContextVar[int] = contextvars.ContextVar("log_indent", default=0)
_log_file_path: Optional[str] = None
_log_file_component: Optional[str] = None
_log_file_console = True
_log_file_lock = threading.Lock()


def configure_log_file(
    path: Optional[str] = None,
    *,
    component: Optional[str] = None,
    console: bool = True,
) -> None:
    """Configura il file diagnostico e, opzionalmente, la sua destinazione console."""
    global _log_file_path, _log_file_component, _log_file_console
    _log_file_path = path
    _log_file_component = component
    _log_file_console = console


def _component_color(name: str) -> str:
    idx = sum(ord(c) for c in name) % len(_COMPONENT_PALETTE)
    return _COMPONENT_PALETTE[idx]


def _indent_str(indent: int) -> str:
    return "│ " * indent


def _format_entry(
    level: str,
    message: str,
    component: Optional[str],
    indent: int,
    metadata: dict,
    exception: Optional[BaseException],
) -> str:
    """Costruisce (senza stampare) una entry di log, eventualmente multi-riga."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    lvl = level.upper()
    lcolor = LEVEL_COLORS.get(lvl, "")
    icon = LEVEL_ICONS.get(lvl, "•")

    comp_tag = ""
    if component:
        ccolor = _component_color(component)
        comp_tag = f" {ccolor}{component[:_COMPONENT_WIDTH]:<{_COMPONENT_WIDTH}}{COLOR_RESET}"
    else:
        comp_tag = f" {'':<{_COMPONENT_WIDTH}}"

    tree = _indent_str(indent)
    header = (
        f"{DIM}{timestamp}{COLOR_RESET} "
        f"{lcolor}{lvl:<8}{COLOR_RESET}"
        f"{comp_tag} "
        f"{tree}{lcolor}{icon}{COLOR_RESET} {message}"
    )

    lines = [header]

    if metadata:
        items = list(metadata.items())
        for idx, (key, value) in enumerate(items):
            branch = "└─" if idx == len(items) - 1 else "├─"
            meta_tree = _indent_str(indent + 1)
            lines.append(
                f"{' ' * 12} {' ' * 8} {' ' * _COMPONENT_WIDTH} {meta_tree}{branch} "
                f"{DIM}{key}{COLOR_RESET}: {_render_value(value)}"
            )

    if exception is not None:
        report = create_diagnostic_report((type(exception), exception, exception.__traceback__))
        meta_tree = _indent_str(indent + 1)
        pad = f"{' ' * 12} {' ' * 8} {' ' * _COMPONENT_WIDTH} "
        lines.append(f"{lcolor}{pad}{meta_tree}└─ Traceback:{COLOR_RESET}")
        for tb_line in report["traceback_formatted"].splitlines():
            lines.append(f"{lcolor}{pad}{_indent_str(indent + 2)}{tb_line}{COLOR_RESET}")
        if lvl in ("ERROR", "CRITICAL"):
            filepath = save_diagnostic_report(report)
            lines.append(f"{lcolor}{pad}{meta_tree}└─ 📝 Report salvato: {filepath}{COLOR_RESET}")

    return "\n".join(lines)


def log(level: str, message: str, component: Optional[str] = None,
        exception: Optional[BaseException] = None, **metadata):
    """Log immediato: stampa subito a schermo (comportamento storico)."""
    indent = _log_indent.get()
    entry = _format_entry(level, message, component, indent, metadata, exception)
    file_enabled = (
        _log_file_path is not None
        and (_log_file_component is None or _log_file_component == component)
    )
    if not (file_enabled and not _log_file_console):
        print(entry)

    if file_enabled:
        with _log_file_lock:
            os.makedirs(os.path.dirname(_log_file_path) or ".", exist_ok=True)
            with open(_log_file_path, "a", encoding="utf-8") as logfile:
                logfile.write(entry + "\n")


@contextmanager
def timed_block(title: str, level: str = "INFO", component: Optional[str] = None):
    """Blocco SEMPRE dettagliato: apertura e chiusura stampate a prescindere
    dall'esito. Mantenuto per compatibilità con codice esistente; per i test
    conviene usare `scope()`, che è silenzioso in caso di successo."""
    indent = _log_indent.get()
    token = _log_indent.set(indent + 1)
    log(level, f"{title} - Starting...", component=component)
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        _log_indent.reset(token)
        log(level, f"{title} - Completed in {duration:.3f}s", component=component)


# =====================================================================
# --- Scope: dettagliato solo in caso di errore ---
# =====================================================================

class LogScope:
    """
    Raggruppa i log di un blocco di lavoro (es. l'esecuzione di un file di
    test, o di un intero manager). Le entry create con .debug/.info/
    .warning/.error() dentro il blocco vengono bufferizzate:

      - se il blocco si chiude con successo → viene stampata UNA riga
        compatta di riepilogo (✅);
      - se fallisce (eccezione propagata, o mark_failed() chiamato
        esplicitamente) → viene stampata la riga di riepilogo (❌) seguita
        da TUTTO il dettaglio bufferizzato, incluso l'eventuale traceback.
    """

    def __init__(self, title: str, component: Optional[str] = None):
        self.title = title
        self.component = component
        self._buffer: List[str] = []
        self._failed = False
        self._start = 0.0
        self._token = None
        self._extra_summary: Dict[str, Any] = {}

    # -- logging bufferizzato --------------------------------------------
    def _add(self, level: str, message: str, exception: Optional[BaseException] = None, **metadata):
        indent = _log_indent.get()
        entry = _format_entry(level, message, self.component, indent, metadata, exception)
        self._buffer.append(entry)

    def debug(self, message, **metadata):
        self._add("DEBUG", message, **metadata)

    def info(self, message, **metadata):
        self._add("INFO", message, **metadata)

    def warning(self, message, **metadata):
        self._add("WARNING", message, **metadata)

    def error(self, message, exception: Optional[BaseException] = None, **metadata):
        self._add("ERROR", message, exception=exception, **metadata)
        self._failed = True

    def mark_failed(self):
        """Segna il blocco come fallito senza necessariamente loggare un errore
        (es. un assert non andato a buon fine, non un'eccezione Python)."""
        self._failed = True

    def set_summary(self, **kv):
        """Info extra mostrate nella riga compatta finale, es. set_summary(passed=3, failed=0)."""
        self._extra_summary.update(kv)

    # -- context manager ---------------------------------------------------
    def __enter__(self):
        self._start = time.perf_counter()
        indent = _log_indent.get()
        self._token = _log_indent.set(indent + 1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.perf_counter() - self._start
        _log_indent.reset(self._token)

        failed = self._failed or exc_type is not None
        icon = "✅" if not failed else "❌"

        if self._extra_summary:
            bits = ", ".join(f"{k}={v}" for k, v in self._extra_summary.items())
            summary_txt = f" ({bits}, {duration:.3f}s)"
        else:
            summary_txt = f" ({duration:.3f}s)"

        header_level = "ERROR" if failed else "INFO"
        indent = _log_indent.get()
        print(_format_entry(header_level, f"{icon} {self.title}{summary_txt}", self.component, indent, {}, None))

        if failed:
            for entry in self._buffer:
                print(entry)
            if exc_type is not None:
                report = create_diagnostic_report((exc_type, exc_val, exc_tb))
                pad_indent = indent + 1
                lcolor = LEVEL_COLORS["ERROR"]
                print(f"{lcolor}{_indent_str(pad_indent)}└─ Traceback (non gestito nel blocco):{COLOR_RESET}")
                for tb_line in report["traceback_formatted"].splitlines():
                    print(f"{lcolor}{_indent_str(pad_indent + 1)}{tb_line}{COLOR_RESET}")
                filepath = save_diagnostic_report(report)
                print(f"{lcolor}{_indent_str(pad_indent)}└─ 📝 Report salvato: {filepath}{COLOR_RESET}")

        return False  # non sopprime mai l'eccezione originale


def scope(title: str, component: Optional[str] = None) -> LogScope:
    """Apre un blocco di log 'silenzioso se va tutto bene'."""
    return LogScope(title, component=component)


# =====================================================================
# --- Logger con componente fisso ---
# =====================================================================

class ComponentLogger:
    """Logger 'legato' a un nome di componente, per non doverlo ripetere
    ad ogni chiamata e per garantire lo stesso tag/colore ovunque."""

    def __init__(self, component: str):
        self.component = component

    def debug(self, message, **metadata):
        log("DEBUG", message, component=self.component, **metadata)

    def info(self, message, **metadata):
        log("INFO", message, component=self.component, **metadata)

    def warning(self, message, **metadata):
        log("WARNING", message, component=self.component, **metadata)

    def error(self, message, exception=None, **metadata):
        log("ERROR", message, component=self.component, exception=exception, **metadata)

    def critical(self, message, exception=None, **metadata):
        log("CRITICAL", message, component=self.component, exception=exception, **metadata)

    def scope(self, title: str) -> LogScope:
        return scope(title, component=self.component)


def get_logger(component: str) -> ComponentLogger:
    return ComponentLogger(component)