import os
import inspect
import uuid
from typing import Optional

import framework.service.diagnostic as diagnostic
import framework.core.language as language
import framework.port.manager as manager
import framework.core.flow as flow
import framework.manager.loader as loader_module


# Alias abbreviati → percorso src relativo
_FILTER_ALIASES: dict[str, str] = {
    "managers":        "src/framework/manager",
    "ports":           "src/framework/port",
    "services":        "src/framework/service",
    "infrastructure":  "src/infrastructure",
}

# Logger legato a questo manager: ogni riga stampata da qui porta sempre
# il tag colorato [tester], senza doverlo ripetere ad ogni chiamata.
_logger = diagnostic.get_logger("tester")


def resolve_filter(raw: str | None) -> Optional[str]:
    """Ritorna il prefisso di percorso su cui filtrare, o None (tutto).

    Esempi di input → output:
        managers                      → src/framework/manager
        managers/defender             → src/framework/manager/defender
        ports                         → src/framework/port
        infrastructure                → src/infrastructure
        infrastructure/authentication → src/infrastructure/authentication
        src/qualunque/percorso        → src/qualunque/percorso  (raw)
    """
    if not raw:
        return None
    if raw in _FILTER_ALIASES:
        return _FILTER_ALIASES[raw]
    for alias, base in _FILTER_ALIASES.items():
        if raw.startswith(alias + '/'):
            return f"{base}/{raw[len(alias) + 1:]}"
    return raw


def is_integration_test_path(path: str) -> bool:
    """Riconosce gli scenari di integrazione in base al nome del file."""
    normalized = path.replace('\\', '/')
    return normalized.endswith('.integration.test.dsl')


def is_contract_test_path(path: str) -> bool:
    """Riconosce i test DSL che certificano l'API del componente."""
    normalized = path.replace('\\', '/')
    return normalized.endswith('.test.dsl') and not is_integration_test_path(normalized)


def resolve_target_name(target) -> str:
    """Ritorna il nome stabile usato per associare un callable al contract."""
    name = getattr(target, "__qualname__", None)
    return name if isinstance(name, str) else str(name or target)


def resolve_export_alias(
    target,
    callable_exports: dict[int, str],
    object_exports: dict[int, tuple[str, object]],
) -> str | None:
    """Associa un callable all'export che lo contiene o lo espone."""
    alias = callable_exports.get(id(target))
    if alias:
        return alias

    exported = object_exports.get(id(target))
    if exported:
        return exported[0]

    owner = getattr(target, "__self__", None)
    if owner is not None:
        exported = object_exports.get(id(owner))
        if exported:
            return exported[0]

    target_name = resolve_target_name(target)
    for object_alias, exported_object in object_exports.values():
        class_name = (
            exported_object.__name__
            if inspect.isclass(exported_object)
            else type(exported_object).__name__
        )
        if target_name.startswith(f"{class_name}."):
            return object_alias

    return None


class Manager(manager.Port):
    def __init__(self, loader: loader_module.Loader, **constants):
        """Inizializza il Manager per l'esecuzione dei test DSL.

        :param loader: Il Loader del framework (dipendenza iniettata)
        :param constants: Configurazioni aggiuntive (incluso filtro da CLI)
        """
        self.loader = loader
        self.filter_raw = constants.get('filter', None)
        self.prefix = resolve_filter(self.filter_raw)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _matches_filter(self, path: str) -> bool:
        """True se il file deve essere eseguito dato il filtro attivo."""
        if self.prefix is None:
            return True
        return path.replace('\\', '/').startswith(self.prefix.replace('\\', '/'))

    def _discover_test_files(self, integration: bool = False) -> list[str]:
        """Elenca in anticipo tutti i file .test.dsl da eseguire, così da
        poter mostrare un contatore [i/N] e un riepilogo coerente."""
        found = []
        for root, _, files in os.walk('./src'):
            for file in files:
                path = os.path.join(root, file).replace('./', '')
                if integration and not is_integration_test_path(path):
                    continue
                if not integration and not is_contract_test_path(path):
                    continue
                if self._matches_filter(path):
                    found.append(path)
        return sorted(found)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    @flow.result()
    async def startup(self, session=None):
        pass

    @flow.result()
    async def shutdown(self, session=None):
        pass

    @flow.result(safe_kwargs=True)
    async def run(self, session, **constants):
        """Esegue i test di contract DSL filtrati secondo il prefisso configurato."""
        return await self._run_suites(session, integration=False, **constants)

    @flow.result(safe_kwargs=True)
    async def run_integration(self, session, **constants):
        """Esegue gli scenari DSL sul runtime gia costruito dal Loader."""
        return await self._run_suites(session, integration=True, **constants)

    async def _run_suites(self, session, integration: bool, **constants):
        filter_raw = constants.get('filter', self.filter_raw)
        self.filter_raw = filter_raw
        self.prefix = resolve_filter(filter_raw)
        label = self.prefix or 'tutti'

        test_files = self._discover_test_files(integration=integration)
        suite_label = 'integrazione' if integration else 'contract'
        _logger.info(
            f"Avvio esecuzione suite {suite_label}… filtro: {label}",
            file_trovati=len(test_files),
        )

        interp = language.Interpreter()
        await interp.start()

        summary = {
            "file_totali": len(test_files),
            "file_ok": 0,
            "file_con_test_falliti": [],   # il file gira, ma almeno un test fallisce
            "file_non_eseguiti": [],       # il file non parte proprio (parse/runtime error)
            "test_totali": 0,
            "test_passati": 0,
            "test_falliti": 0,
        }

        for i, path in enumerate(test_files, start=1):
            # Ogni file ha il suo "scope": se tutti i test passano viene
            # stampata UNA riga compatta; se qualcosa fallisce, viene
            # mostrato tutto il dettaglio bufferizzato (incluso traceback).
            with _logger.scope(f"[{i}/{len(test_files)}] {path}") as s:
                try:
                    res = await self.loader.resource(path)
                    source = flow.output(res) if flow.is_result(res) else res
                    await interp.load_file(path, source)
                    outcome = await self._execute_dsl(
                        interp,
                        path,
                        s,
                        integration=integration,
                        runtime_session=session,
                    )
                    if not integration:
                        self.loader.record_contract(path, outcome)

                    data = outcome.get("data", {})
                    if "total" in data:
                        # Il file è partito ed è stata eseguita almeno la
                        # raccolta dei test (anche se poi qualcuno fallisce).
                        s.set_summary(
                            passed=data.get("passed", 0),
                            failed=data.get("failed", 0),
                            total=data.get("total", 0),
                        )
                        summary["test_totali"] += data.get("total", 0)
                        summary["test_passati"] += data.get("passed", 0)
                        summary["test_falliti"] += data.get("failed", 0)

                        if outcome.get("success"):
                            summary["file_ok"] += 1
                        else:
                            s.mark_failed()
                            summary["file_con_test_falliti"].append(path)
                    else:
                        # Il file non è nemmeno partito (es. errore di parsing
                        # o runtime prima di poter leggere la test_suite):
                        # non ha senso mostrare "0 passati/falliti".
                        s.mark_failed()
                        summary["file_non_eseguiti"].append(path)

                except Exception as e:
                    s.error(f"Impossibile eseguire il file DSL {path}", exception=e)
                    summary["file_non_eseguiti"].append(path)
                    self.loader.record_contract(path, {"success": False, "data": {"error": str(e)}})

        esito = "PASSED" if not summary["file_con_test_falliti"] and not summary["file_non_eseguiti"] else "FAILED"
        log_fn = _logger.error if esito == "FAILED" else _logger.info
        log_fn(
            f"Riepilogo suite {suite_label}: {esito}",
            file_totali=summary["file_totali"],
            file_ok=summary["file_ok"],
            file_con_test_falliti=summary["file_con_test_falliti"],
            file_non_eseguiti=summary["file_non_eseguiti"],
            test_totali=summary["test_totali"],
            test_passati=summary["test_passati"],
            test_falliti=summary["test_falliti"],
        )
        return esito == "PASSED"

    # ── esecuzione di un singolo file .test.dsl ────────────────────────────────

    async def _execute_dsl(
        self,
        interp: language.Interpreter,
        path: str,
        s: "diagnostic.LogScope",
        integration: bool = False,
        runtime_session=None,
    ) -> dict:
        """Esegue una suite di test DSL e registra i risultati.

        :param interp: L'interprete DSL
        :param path: Percorso del file .test.dsl
        :param s: Scope di log del file corrente (vedi Manager.run)
        :return: Dizionario con esito e dettagli dei test
        """
        session_id = str(uuid.uuid4())
        session_dict = {
            'id': session_id,
            'errors': [],
            'providers': {},
            'user': {'id': 'tester', 'role': 'system'}
        }

        interp.session_create(
            sid=session_id,
            env=language.DSL_FUNCTIONS | {
                'resource': self.loader.resource,
                'import': self.loader.import_module,
                'test': {
                    'loader': self.loader,
                    'application': getattr(self.loader, 'app', None),
                    'managers': self.loader.get_managers(),
                    'session': runtime_session,
                    'integration': integration,
                },
            }
        )

        session = language.SessionHandle(interp, session=session_dict)

        try:
            run_result = await session.run(path)
            ctx = flow.output(run_result) if flow.is_result(run_result) else run_result
            #exit(ctx)
        except Exception as e:
            s.error(
                f"Il file DSL {path} non è stato eseguito correttamente (errore di parsing o runtime)",
                exception=e,
            )
            return {"success": False, "data": {"error": str(e)}}

        test_suite = language.flatten_records(ctx.get('test_suite', []))

        exports = ctx.get('exports', {}) or {}
        exported_targets = {
            id(target): alias
            for alias, target in exports.items()
            if callable(target) and not inspect.isclass(target)
        } if isinstance(exports, dict) else {}
        exported_objects = {
            id(target): (alias, target)
            for alias, target in exports.items()
            if (not callable(target) or inspect.isclass(target)) and target is not None
        } if isinstance(exports, dict) else {}
        export_methods = {
            alias: set()
            for alias, target in exports.items()
        } if isinstance(exports, dict) else {}
        invalid_exports = [
            alias for alias, target in exports.items()
            if target is None
        ] if isinstance(exports, dict) else ["exports"]

        results = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": [],
            "details": [],
            "exports": {},
            "export_errors": [],
        }
        if invalid_exports:
            results["export_errors"].append(
                f"Export non valido: {', '.join(sorted(invalid_exports))}"
            )
        used_exports = set()

        for alias, target in exports.items() if isinstance(exports, dict) else ():
            if callable(target):
                export_methods[alias].add(resolve_target_name(target))

        for i, test in enumerate(test_suite):
            if not isinstance(test, dict):
                continue

            results["total"] += 1
            target = test.get('action')
            args = test.get('inputs', ())
            expected = test.get('outputs')
            assert_fn = test.get('assert')
            test_note = test.get('note', f'Test #{i}')

            # ── validazione preventiva ──────────────────────────────────
            if not callable(target):
                self._record_setup_error(
                    results, s, i, test_note, target,
                    f"'action' non è una funzione valida (valore risolto: {target!r}). "
                    f"Controlla il nome nel file DSL e che l'import correlato sia andato a buon fine."
                )
                continue

            export_alias = resolve_export_alias(target, exported_targets, exported_objects)
            if exports and export_alias is None:
                self._record_setup_error(
                    results, s, i, test_note, target,
                    f"'action' non dichiarata in exports (valore risolto: {target!r})."
                )
                continue

            if not callable(assert_fn):
                self._record_setup_error(
                    results, s, i, test_note, target,
                    f"'assert' non è una funzione valida (valore risolto: {assert_fn!r})."
                )
                continue

            # ── fase 1: invocazione dell'azione ─────────────────────────
            try:
                if isinstance(args, dict) and ('args' in args or 'kwargs' in args):
                    positional = args.get('args', ())
                    keyword = args.get('kwargs', {})
                    if not isinstance(positional, (list, tuple)):
                        positional = (positional,)
                    if not isinstance(keyword, dict):
                        raise TypeError("'inputs.kwargs' deve essere un dizionario")
                    received = await interp.call(target, tuple(positional), keyword)
                elif isinstance(args, dict):
                    received = await interp.call(target, (), args)
                elif isinstance(args, (list, tuple)):
                    received = await interp.call(target, args)
                else:
                    received = await interp.call(target, (args,))
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"target": str(target), "error": str(e), "test_note": test_note, "phase": "action"})
                results["details"].append({"target": str(target), "status": "ERROR", "phase": "action", "message": str(e), "note": test_note, "inputs": args})
                s.error(f"Test N.{i} ({test_note}): errore nell'azione '{target}'", exception=e, inputs=args)
                continue

            # ── fase 2: valutazione dell'assert ─────────────────────────
            try:
                ok = flow.output(await interp.call(assert_fn, (), {"received": received, "expected": expected}))
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"target": str(target), "error": str(e), "test_note": test_note, "phase": "assert"})
                results["details"].append({"target": str(target), "status": "ERROR", "phase": "assert", "message": str(e), "note": test_note, "received": received, "expected": expected})
                s.error(f"Test N.{i} ({test_note}): errore nella valutazione dell'assert", exception=e, expected=expected, received=received)
                continue

            target_name = resolve_target_name(target)
            results["passed" if ok else "failed"] += 1
            detail = {
                "target": target_name,
                "export": export_alias,
                "status": "OK" if ok else "FAIL",
                "note": test_note,
            }

            if ok:
                if export_alias:
                    used_exports.add(export_alias)
                    export_methods.setdefault(export_alias, set()).add(target_name)
                # Bufferizzato: si vede solo se il file, nel complesso, fallisce.
                s.info(f"OK - Test N.{i}: {test_note}")
            else:
                detail |= {"expected": expected, "received": received, "inputs": args}
                s.warning(f"FAIL - Test N.{i}: {test_note}", inputs=args, expected=expected, received=received)
                s.mark_failed()

            results["details"].append(detail)

        results["exports"] = {
            alias: sorted(methods)
            for alias, methods in export_methods.items()
        }
        missing_exports = set(exports) - used_exports if isinstance(exports, dict) else set()
        if missing_exports:
            message = f"Export non testati: {', '.join(sorted(missing_exports))}"
            results["export_errors"].append(message)
            s.error(message)

        results["success"] = results["failed"] == 0 and not results["export_errors"]
        return {"success": results["success"], "data": results}

    @staticmethod
    def _record_setup_error(results: dict, s: "diagnostic.LogScope", i: int, test_note: str, target, message: str) -> None:
        """Registra un test non partito per un problema di configurazione
        (action/assert non risolti), distinguendolo da un vero fallimento
        dell'azione o dell'assert."""
        results["failed"] += 1
        results["errors"].append({"target": str(target), "error": message, "test_note": test_note, "phase": "setup"})
        results["details"].append({"target": str(target), "status": "ERROR", "phase": "setup", "message": message, "note": test_note})
        s.error(f"Test N.{i} ({test_note}): setup non valido", dettaglio=message)