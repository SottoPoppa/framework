import os
from pathlib import Path
import json

class Contract:
    VERSION = 2
    """Gestione dei contratti (*.contract.json / *.json) associati a un
    qualunque file sorgente — non solo adapter: manager, service, port, ecc.

    Un contratto ha due responsabilità:
    1. dichiarare le dipendenze pip del componente (`requires`), quando
       presenti (tipicamente solo negli adapter, usato da Loader.install());
    2. dichiarare gli export che compongono l'API verificata e certificare,
       componente per componente, che il codice in esecuzione è quello che ha
       superato i test — struttura:

                "contract_version": 2,
                "exports": {
                    "messenger": ["Manager.send", "Manager.receive"]
                },

        "hashes": {
          "Port": {
            "initialize": {"test": "<hash al momento del test>", "production": "<hash attuale>"},
            "close":      {"test": "...", "production": "..."}
          },
          "una_funzione_top": {"test": "...", "production": "..."}
        }

       I metodi di classe sono annidati sotto il nome della classe
       ('Port' → 'initialize'); le funzioni a livello di modulo, non
       avendo una classe sotto cui stare, restano piatte alla radice
       (vedi Reflection.module_components).
    Se un componente esportato cambia dopo essere stato testato, il suo
    hash `production` non combacia più con `test` → al boot risulta stale.

    Un file senza contratto accanto non viene mai verificato: il contratto
    è opt-in, si applica a QUALSIASI file — non solo agli adapter.
    """

    @staticmethod
    def for_source(source_path: str) -> str:
        """Deriva il percorso del contratto da un file sorgente .py.
        Preferisce '<file>.contract.json', ripiega su '<file>.json'."""
        base, _ = os.path.splitext(source_path)
        contract, legacy = f"{base}.contract.json", f"{base}.json"
        if os.path.exists(contract):
            return contract
        return legacy if os.path.exists(legacy) else contract

    @staticmethod
    def read(path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            content = Path(path).read_text(encoding="utf-8").strip()
            return json.loads(content) if content else {}
        except Exception as e:
            print(f"[!] Errore lettura contratto '{path}': {e}")
            return {}

    @staticmethod
    def write(path: str, data: dict) -> None:
        def json_safe(value):
            if isinstance(value, dict):
                return {str(key): json_safe(item) for key, item in value.items()}
            if isinstance(value, (list, tuple, set)):
                return [json_safe(item) for item in value]
            return value

        target = Path(path)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(json_safe(data), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(target)

    @staticmethod
    def _export_names(exports) -> list[str] | None:
        if exports is None:
            return None
        if isinstance(exports, dict):
            names = []
            for methods in exports.values():
                if isinstance(methods, list):
                    names.extend(methods)
                elif isinstance(methods, str):
                    names.append(methods)
            return sorted(set(names))
        if isinstance(exports, list):
            return sorted(set(exports))
        raise ValueError("'exports' deve essere una lista o un dizionario")

    @staticmethod
    def _entry(hashes: dict, name: str) -> dict:
        """Ritorna il dict {test, production} per un componente, annidando
        sotto il nome della classe quando `name` è 'ClasseName.metodo'."""
        if "." in name:
            cls_name, method_name = name.split(".", 1)
            return hashes.setdefault(cls_name, {}).setdefault(method_name, {})
        return hashes.setdefault(name, {})

    @staticmethod
    def record_tested(
        source_path: str,
        component_hashes: dict[str, str],
        exports: list[str] | None = None,
    ) -> None:
        """Chiamato dal tester quando i test relativi a specifici componenti
        (metodi o funzioni) passano. `component_hashes`: {nome: hash_sorgente}.
        `exports`, quando presente, è il manifest dell'API verificata. Non
        richiede che esista già un contratto: se manca lo crea."""
        if not component_hashes:
            return
        path = Contract.for_source(source_path)
        previous = Contract.read(path)
        if exports is not None:
            # Un nuovo test è una nuova certificazione: elimina hash rimasti
            # da export rimossi, preservando solo le dipendenze del contract.
            contract = {
                key: value
                for key, value in previous.items()
                if key == "requires"
            }
            contract.update({
                "contract_version": Contract.VERSION,
                "exports": exports,
                "hashes": {},
            })
        else:
            contract = previous
        hashes = contract.setdefault("hashes", {})
        for name, component_hash in component_hashes.items():
            entry = Contract._entry(hashes, name)
            entry["test"] = component_hash
            entry["production"] = component_hash
        Contract.write(path, contract)

    @staticmethod
    def verify_module(source_path: str, module, strict: bool) -> bool:
        import framework.service.introspection as introspection
        """Chiamato al caricamento di qualunque componente: se esiste un
        contratto accanto al file, verifica ogni suo componente pubblico
        (metodi di classi + funzioni di modulo) contro l'hash registrato al
        momento del test. Aggiorna `production` come traccia di audit.

        Nessun contratto presente → nessuna verifica, ritorna True subito.
        """
        contract_path = Contract.for_source(source_path)
        if not os.path.exists(contract_path):
            return True

        contract = Contract.read(contract_path)
        declared_exports = contract.get("exports")
        names = Contract._export_names(declared_exports)
        if declared_exports is not None and names is None:
            raise RuntimeError(
                f"Contract non valido: 'exports' deve essere una lista o un dizionario in '{contract_path}'"
            )

        components = introspection.Reflection.module_components(
            module,
            set(names) if names is not None else None,
        )
        if not components and names is None:
            return True

        hashes = contract.setdefault("hashes", {})

        missing = []
        modified = []
        names_to_verify = names if names is not None else components.keys()
        for name in names_to_verify:
            source = components.get(name)
            if source is None:
                missing.append(name)
                continue
            current = introspection.Reflection.hash_text(source)
            entry = Contract._entry(hashes, name)
            tested = entry.get("test")
            entry["production"] = current
            if tested is None or tested != current:
                modified.append(name)

        Contract.write(contract_path, contract)

        stale = missing + modified
        if missing:
            print(f"[!] '{source_path}': export mancanti nel codice: {', '.join(missing)}")
        if modified:
            print(f"[!] '{source_path}': export non testati o modificati: {', '.join(modified)}")
        if not stale:
            print(f"[✓] '{source_path}': tutti gli export testati e verificati.")

        if strict and stale:
            raise RuntimeError(
                f"Avvio bloccato: '{source_path}' ha componenti non testati/modificati: "
                f"{', '.join(stale)} (usa --dev, --test o --skip-verify per bypassare)."
            )
        return not stale