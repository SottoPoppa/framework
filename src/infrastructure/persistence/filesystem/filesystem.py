import sys
import os
import time
import asyncio
import json
from concurrent.futures import CancelledError as FutureCancelledError
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import framework.port.persistence as persistence
import framework.core.flow as flow
from framework.service.diagnostic import get_logger
from framework.manager.messenger import Manager as Messenger


class FileWatcherHandler(FileSystemEventHandler):
    def __init__(self, adapter, session, loop):
        self.adapter = adapter
        self.session = session
        self.loop = loop  
        self._last_modified_times = {}
        self._debounce_interval = 1.0  # 1 secondo per evitare doppi eventi da editor

    def _trigger_event(self, event_type, event):
        if event.is_directory:
            return
            
        current_time = time.time()
        # Debounce su tutti i tipi di evento per evitare loop o eventi duplicati
        if current_time - self._last_modified_times.get(event.src_path, 0) < self._debounce_interval:
            return
        self._last_modified_times[event.src_path] = current_time

        coro = self.adapter.handle_watcher_event(self.session, event_type, event.src_path)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        except Exception as exc:
            coro.close()
            self.adapter.logger.error(
                "Impossibile pianificare l'evento del watcher",
                exception=exc,
                path=event.src_path,
            )
            return
        future.add_done_callback(self._event_completed)

    def _event_completed(self, future):
        try:
            result = future.result()
        except (asyncio.CancelledError, FutureCancelledError):
            return
        except Exception as exc:
            self.adapter.logger.error(
                "Gestione evento watcher fallita",
                exception=exc,
            )
            return
        if flow.is_result(result) and not flow.check(result):
            self.adapter.logger.error(
                "Pubblicazione evento watcher fallita",
                error=flow.output(result),
            )

    def on_modified(self, event):
        if event.is_directory:
            return
        #print(f"\n[Watcher] File modificato: {event.src_path}")
        self._trigger_event("modified", event)

    def on_created(self, event):
        if not event.is_directory:
            self._trigger_event("created", event)

    def on_deleted(self, event):
        if not event.is_directory:
            self._trigger_event("deleted", event)

    def on_moved(self, event):
        if event.is_directory:
            return
        self._trigger_event("moved", event)


class Adapter(persistence.Port):
    capabilities = {
        "encryption_at_rest": False,
        "audit": False,
        "soft_delete": False,
    }

    def __init__(self, messenger: Messenger, **constants):
        self.messenger = messenger
        self.logger = get_logger("persistence.filesystem")
        self.config = constants
        self.name = constants.get('name')
        self.path = constants.get('path', os.getcwd()+"/")
        self.watch = constants.get('watch', False)
        self.observer = None

    @flow.result()
    async def start(self, session=None):
        if self.watch:
            main_loop = asyncio.get_running_loop()
            self._start_watcher(session, main_loop)

    @flow.result()
    async def stop(self, session=None):
        self.stop_watcher()

    def _start_watcher(self, session, main_loop):
        self.logger.info("Avvio del watcher", path=self.path)
        event_handler = FileWatcherHandler(adapter=self, session=session, loop=main_loop)
        self.observer = Observer()
        self.observer.schedule(event_handler, path=self.path, recursive=True)
        self.observer.start()

    @flow.result()
    async def handle_watcher_event(self, session, event_type, filepath):
        return await self.messenger.send(
            session,
            message=filepath,      
            domain=f"event.{event_type}"
        )
        

    def stop_watcher(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.logger.info("Watcher interrotto correttamente")

    def __del__(self):
        if self.observer and self.observer.is_alive():
            try:
                self.stop_watcher()
            except Exception as exc:
                logger = getattr(self, "logger", None)
                if logger:
                    logger.warning(
                        "Errore durante l'arresto del watcher in finalizzazione",
                        exception=exc,
                    )

    @flow.result()
    async def request(self, **constants):
        values = constants.get('storekeeper', constants)
        if not isinstance(values, dict):
            values = constants
        path = self._resolve_path(**(values | {"path": self.path}))
        path = self._resolve_confined_path(path)
        if self._is_structured_json(path, values):
            return await self._request_json(path, constants.get('method'), values)
        data = self._payload_data(**values)
        method = constants.get('method')

        match method:
            case 'POST':
                os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
                with open(path, "w", encoding="utf-8") as file:
                    file.write(data)
                return flow.success(self._record(path, data))
            case 'DELETE':
                if os.path.exists(path):
                    os.remove(path)
                    return flow.success({})

                return flow.error("File non trovato")
            case 'PUT':
                os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
                with open(path, "w", encoding="utf-8") as file:
                    file.write(data)
                return flow.success(self._record(path, data))
            case 'GET':
                try:
                    with open(path, "r", encoding="utf-8") as file:
                        data = file.read()
                except FileNotFoundError:
                    return flow.error({
                        "code": "not_found",
                        "message": "File non trovato",
                        "path": path,
                    })

                return flow.success(self._record(path, data))
            case 'VIEW':
                return await self.query(**values)
            case _:
                return flow.error()

    @staticmethod
    def _is_structured_json(path, constants):
        return Path(path).suffix.casefold() == '.json' and isinstance(
            constants.get('payload'), dict
        ) and 'content' not in constants.get('payload', {})

    async def _request_json(self, path, method, constants):
        document = self._read_json(path)
        records = self._json_records(document)
        filters = constants.get('filter', {})
        payload = constants.get('payload', {})

        if method == 'POST':
            records.append(payload)
            self._write_json(
                path,
                self._json_document(document, records, constants.get('collection')),
            )
            return flow.success(payload)

        matches = [record for record in records if self._matches(record, filters)]
        if method == 'GET':
            return flow.success(matches if filters else records)

        if method == 'PUT':
            if not matches:
                return flow.error('Record non trovato')
            for record in records:
                if self._matches(record, filters):
                    record.update(payload)
            self._write_json(
                path,
                self._json_document(document, records, constants.get('collection')),
            )
            updated = [record for record in records if self._matches(record, filters)]
            return flow.success(updated[0] if len(updated) == 1 else updated)

        if method == 'DELETE':
            remaining = [record for record in records if not self._matches(record, filters)]
            if len(remaining) == len(records):
                return flow.error('Record non trovato')
            self._write_json(
                path,
                self._json_document(document, remaining, constants.get('collection')),
            )
            return flow.success({})

        return flow.error()

    @staticmethod
    def _read_json(path):
        try:
            with open(path, encoding='utf-8') as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    @staticmethod
    def _json_records(document):
        if isinstance(document, list):
            return [record for record in document if isinstance(record, dict)]
        if isinstance(document, dict):
            for value in document.values():
                if isinstance(value, list):
                    return [record for record in value if isinstance(record, dict)]
        return []

    @staticmethod
    def _json_document(document, records, collection=None):
        if isinstance(document, (list, tuple)):
            return records
        items = getattr(document, 'items', None)
        if callable(items):
            for key, value in items():
                if isinstance(value, list):
                    document[key] = records
                    return document
            if isinstance(collection, str) and collection:
                document[collection] = records
                return document
            if not document:
                return records
        raise ValueError(
            "JSON document must contain a list or specify a collection key"
        )

    @staticmethod
    def _matches(record, filters):
        if not filters:
            return True
        for field, expected in filters.get('eq', {}).items():
            if record.get(field) != expected:
                return False
        return True

    @staticmethod
    def _write_json(path, document):
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        temporary_path = f"{path}.tmp"
        try:
            with open(temporary_path, 'w', encoding='utf-8') as file:
                json.dump(document, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

    @staticmethod
    def _resolve_path(**constants):
        location = constants.get('location')
        if isinstance(location, str) and location:
            return location
        filename = constants.get('filter', {}).get('eq', {}).get('filename', '')
        return os.path.join(constants.get('path', os.getcwd()), filename)

    def _resolve_confined_path(self, path):
        root = Path(self.path).resolve()
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "Percorso fuori dalla directory filesystem configurata"
            ) from exc
        return str(resolved)

    @staticmethod
    def _payload_data(**constants):
        payload = constants.get('payload', {})
        if isinstance(payload, dict) and 'content' in payload:
            return str(payload['content'])
        return str(constants.get('data', ''))

    @staticmethod
    def _record(path, content):
        file_path = Path(path)
        return {
            'path': str(file_path),
            'name': file_path.stem,
            'extension': file_path.suffix.lstrip('.'),
            'size': len(content.encode('utf-8')),
            'content': content,
        }

    # --- Operazioni CRUD standard di modello ---
    async def create(self, **constants): return await self.request(**{'method': 'POST'} | constants)
    async def delete(self, **constants): return await self.request(**{'method': 'DELETE'} | constants)
    async def update(self, **constants): return await self.request(**{'method': 'PUT'} | constants)
    async def read(self, **constants): return await self.request(**{'method': 'GET'} | constants)
    @flow.result()
    async def view(self, **constants): return await self.request(**{'method': 'VIEW'} | constants)
    # --- Operazioni Infrastrutturali (View & Query) ---


    @flow.result()
    async def query(self, **constants):
        """
        Invocato da Manager.overview() o da view.
        Raccoglie ricorsivamente tutto il contenuto del file system (query) 
        e delega il filtraggio al metodo filter.
        """
        if not self.path or not os.path.exists(self.path):
            return flow.error(f"La path '{self.path}' non esiste o non è valida.")
        
        all_items = []
        try:
            for root, dirs, files in os.walk(self.path):
                relative_root = os.path.relpath(root, self.path)
                if relative_root == ".":
                    relative_root = ""

                # Estrazione directory
                for d in dirs:
                    all_items.append({
                        "type": "directory",
                        "name": d,
                        "relative_path": os.path.join(relative_root, d),
                        "absolute_path": os.path.join(root, d)
                    })
                
                # Estrazione file
                for f in files:
                    all_items.append({
                        "type": "file",
                        "name": f,
                        "relative_path": os.path.join(relative_root, f),
                        "absolute_path": os.path.join(root, f)
                    })
            
            # 🌟 Delega il dataset appena estratto al metodo filter
            return await self.filter(dataset=all_items, **constants)
            
        except Exception as e:
            return flow.error(f"Errore durante l'ispezione della path: {str(e)}")

    async def filter(self, dataset, **constants):
        """
        Esegue esclusivamente la logica di filtraggio dinamico sul dataset.
        """
        filters = constants.get('filter', {})
        filtered_items = dataset

        operators = {
            'eq': lambda val, target: val == target,
            'ne': lambda val, target: val != target,
            'contains': lambda val, target: target.lower() in str(val).lower(),
            # Normalizziamo rimuovendo eventuali slash iniziali superflui per fare il confronto in sicurezza
            'startswith': lambda val, target: str(val).lstrip('/').lower().startswith(str(target).lstrip('/').lower()),
            'endswith': lambda val, target: str(val).lower().endswith(str(target).lower()),
        }

        for op, conditions in filters.items():
            if op not in operators or not isinstance(conditions, dict):
                continue
                
            op_func = operators[op]
            
            # Cicliamo sui campi interni (es. 'relative_path', 'type')
            for field, target_value in conditions.items():
                filtered_items = [
                    item for item in filtered_items 
                    if field in item and op_func(item[field], target_value)
                ]

        return flow.success(filtered_items)