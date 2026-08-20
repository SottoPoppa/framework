import sys
import os
import time
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import framework.port.persistence as persistence
import framework.service.flow as flow
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
        asyncio.run_coroutine_threadsafe(coro, self.loop)

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
    def __init__(self, messenger: Messenger, **constants):
        self.messenger = messenger
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
        print(f"👀 Avvio del watcher su '{self.path}'...")
        event_handler = FileWatcherHandler(adapter=self, session=session, loop=main_loop)
        self.observer = Observer()
        self.observer.schedule(event_handler, path=self.path, recursive=True)
        self.observer.start()

    @flow.result()
    async def handle_watcher_event(self, session, event_type, filepath):
        await self.messenger.send(
            session,
            message=filepath,      
            domain=f"event.{event_type}"
        )
        

    def stop_watcher(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join()
                print("👋 Watcher interrotto correttamente.")
            except Exception:
                pass

    def __del__(self):
        if self.observer and self.observer.is_alive():
            self.stop_watcher()

    @flow.result()
    async def request(self, **constants):
        filename = constants.get('filter', {}).get('eq', {}).get('filename','')
        #raise Exception(filename)
        method = constants.get('method')
        
        path = self.path + filename

        match method:
            case 'POST':
                with open(path, "w", encoding="utf-8") as file:
                    file.write(data)
            case 'DELETE':
                if os.path.exists(filepath):
                    os.remove(filepath)
                    return flow.success(filepath)

                return flow.error("File non trovato")
            case 'PUT':
                with open(path, "a", encoding="utf-8") as file:
                    file.write(data)
            case 'GET':
                with open(path, "r", encoding="utf-8") as file:
                    data = file.read()

                return flow.success(data)
            case 'VIEW':
                return await self.query(**constants)
            case _:
                return flow.error()

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