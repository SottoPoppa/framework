class DagRunner:

    def __init__(self, workers: int = 3):
        self.workers = workers

        self.graphs   = {}   # fname -> DiGraph
        self.nodes    = {}   # fname -> {node_name -> node_def}
        self.triggers = {}   # fname -> {node_name -> [listeners]}

        self._file_defaults = {}

        self.sessions  = {}
        self.queue     = asyncio.Queue()
        self.tasks     = []
        self.running   = False

        self.cancelled_sessions: set = set()

    # ─────────────────────────────────────────
    # FILE
    # ─────────────────────────────────────────

    async def add_file(self, name: str, nodes: List[Dict]):
        G  = nx.DiGraph()
        nm = {n["name"]: n for n in nodes}
        self.triggers[name] = {}

        for n in nodes:
            G.add_node(n["name"])
            for d in n.get("deps", []):
                if d in nm:
                    G.add_edge(d, n["name"])
            trg = n.get("trigger")
            if trg:
                self.triggers[name].setdefault(trg, []).append(n["name"])

        if not nx.is_directed_acyclic_graph(G):
            raise ValueError(f"Il file '{name}' contiene cicli")

        self.graphs[name] = G
        self.nodes[name]  = nm
        self._file_defaults[name] = {
            n["name"]: n["default"]
            for n in nodes
            if n.get("default") is not None
        }

        for session in self.sessions.values():
            for k, v in self._file_defaults[name].items():
                _set_default(session["ctx"], k, v)

    async def delete_file(self, name: str):
        for store in (self.graphs, self.nodes, self.triggers):
            store.pop(name, None)

    def attach_node(self, fname: str, node_def: dict):
        """Aggiunge dinamicamente un nodo reattivo a un DAG."""
        if fname not in self.graphs:
            return
            
        name = node_def["name"]
        if name in self.nodes[fname]:
            return
            
        self.nodes[fname][name] = node_def
        self.graphs[fname].add_node(name)
        
        for dep in node_def.get("deps", []):
            if dep in self.nodes[fname]:
                self.graphs[fname].add_edge(dep, name)

    # ─────────────────────────────────────────
    # SESSION — identità utente persistente
    #
    # Non è legata a un file specifico.
    # ctx accumula stato tra le richieste.
    # run_file() decide quale file eseguire.
    # ─────────────────────────────────────────

    def create_session(self, sid: str, ctx: Optional[Dict] = None):
        """
        Inizializza o aggiorna una sessione persistente.
        Se esiste già, unisce il nuovo contesto a quello esistente.
        """
        session = self.sessions.setdefault(sid, {
            "ctx":           {},
            "results":       {},       # "fname::node_name" -> Result
            "done":          {},       # "fname::node_name" -> Event
            "schedulers":    {},       # "fname::node_name" -> Task heartbeat
            "running_files": set(),    # fname attualmente in esecuzione
        })

        # 1. inietta i default di tutti i file registrati — priorità minima
        for defaults in self._file_defaults.values():
            for k, v in defaults.items():
                _set_default(session["ctx"], k, v)

        if ctx:
            session["ctx"].update(ctx)

    def context(self, sid: str) -> Dict:
        """Restituisce il contesto della sessione sid."""
        return self.sessions.get(sid, {}).get("ctx", {})

    async def run_file(self, sid: str, fname: str, ctx_update: Optional[Dict] = None):
        """
        Esegue un file specifico sulla sessione esistente.

        ctx_update: aggiorna il ctx prima dell'esecuzione
                    (tipicamente il body della request HTTP)

        Aspetta solo i nodi one-shot.
        I nodi schedulati continuano in background fino a close_session.
        Più run_file sulla stessa sessione possono girare in parallelo.

        Ritorna: dict {node_name -> Result} dei nodi del file eseguito.
        """
        if sid not in self.sessions:
            raise ValueError(f"FLOW -> Sessione '{sid}' non trovata.")
        if fname not in self.graphs:
            raise ValueError(f"File '{fname}' non registrato.")

        session = self.sessions[sid]

        # Aggiorna ctx con i dati della richiesta corrente usando deep merge
        # le chiavi esistenti (impostate da update_state/messenger.post) hanno priorità
        if ctx_update:
            _deep_merge_defaults(session["ctx"], ctx_update)

        session["running_files"].add(fname)

        # Inizializza/resetta gli eventi done per i nodi di questo file
        for n in self.nodes[fname]:
            session["done"][_key(fname, n)] = asyncio.Event()

        if not self.running:
            await self.start()

        # Enqueue i root node
        '''for n in self.graphs[fname].nodes:
            if self.graphs[fname].in_degree(n) == 0 and self.nodes[fname][n].get("entry", True):
                self.queue.put_nowait((sid, fname, n))'''
        
        # Enqueue root nodes (bootstrap del DAG)
        for n in self.graphs[fname].nodes:
            nd = self.nodes[fname][n]
            if self.graphs[fname].in_degree(n) == 0:
                if not self._auto_starts(fname, n):
                    continue
                if nd.get("entry", True):
                    self.queue.put_nowait((sid, fname, n))


        # Aspetta solo i nodi one-shot (senza schedule)
        one_shot = [
            session["done"][_key(fname, n)].wait()
            for n in self.nodes[fname]
            if not self.nodes[fname][n].get("schedule") and self._auto_starts(fname, n)
        ]
        
        if one_shot:
            await asyncio.gather(*one_shot)
        else:
            # DAG puramente reattivo: aspetta almeno un giro completo
            await asyncio.gather(*[
                session["done"][_key(fname, n)].wait()
                for n in self.nodes[fname]
            ])

        session["running_files"].discard(fname)

        # Ritorna i risultati di questo file con chiave semplice (node_name)
        return {
            n: session["results"][_key(fname, n)]
            for n in self.nodes[fname]
            if _key(fname, n) in session["results"]
        }

    async def close_session(self, sid: str):
        if sid not in self.sessions:
            return

        session = self.sessions[sid]
        self.cancelled_sessions.add(sid)

        for task in session["schedulers"].values():
            task.cancel()

        for event in session["done"].values():
            if not event.is_set():
                event.set()

        del self.sessions[sid]

        async def _cleanup():
            await asyncio.sleep(60)
            self.cancelled_sessions.discard(sid)
        asyncio.create_task(_cleanup())

    async def clear_all_sessions(self):
        for sid in list(self.sessions.keys()):
            await self.close_session(sid)

    # ─────────────────────────────────────────
    # WORKERS
    # ─────────────────────────────────────────

    async def start(self):
        self.running = True
        self.tasks = [asyncio.create_task(self._worker()) for _ in range(self.workers)]

    async def stop(self):
        self.running = False
        for t in self.tasks:
            t.cancel()

    async def _worker(self):
        while self.running:
            try:
                sid, fname, name = await asyncio.wait_for(self.queue.get(), 0.2)
            except asyncio.TimeoutError:
                continue

            if sid in self.cancelled_sessions:
                self.queue.task_done()
                continue

            await self._run_node(sid, fname, name)
            self.queue.task_done()

    # ─────────────────────────────────────────
    # CORE
    # ─────────────────────────────────────────

    async def _run_node(self, sid: str, fname: str, name: str):
        session = self.sessions[sid]
        nd  = self.nodes[fname][name]
        k   = _key(fname, name)

        d = {
            "sid":     sid,
            "fname":   fname,
            "node":    nd,
            "ctx":     session["ctx"],
            "results": session["results"],
            "result":  None,
            "t0":      time.perf_counter(),
        }

        steps = [self._check_deps]
        if nd.get("duration"):   steps.append(self._handle_duration)
        if nd.get("when"):       steps.append(self._check_when)
        if nd.get("on_start"):   steps.append(functools.partial(self._run_hook, hook_name="on_start"))
        steps.append(self._execute_step)
        if nd.get("on_success"): steps.append(functools.partial(self._run_hook, hook_name="on_success"))
        if nd.get("on_error"):   steps.append(functools.partial(self._run_hook, hook_name="on_error"))
        if nd.get("on_end"):     steps.append(functools.partial(self._run_hook, hook_name="on_end"))
        steps.append(self._save_step)
        steps.append(self._dispatch)

        await pipeline(d, *steps)

        if k in session["done"]:
            session["done"][k].set()

    # ─────────────────────────────────────────
    # OPS
    # ─────────────────────────────────────────

    @action()
    async def _check_deps(self, d):
        sid       = d["sid"]
        fname     = d["fname"]
        deps      = d["node"].get("deps", [])
        node_name = d["node"]["name"]
        k         = _key(fname, node_name)
        policy    = d["node"].get("policy", "all")
        res       = d["results"]
        session   = self.sessions[sid]
        use_cache = d["node"].get("cache", False)

        if not deps:
            return success(d)

        dep_keys = [_key(fname, dep) for dep in deps]

        not_ready = [
            dk for dk in dep_keys
            if dk in session["done"] and not session["done"][dk].is_set()
        ]

        if not_ready and not use_cache:
            async def _retry_later():
                await asyncio.sleep(0.5)
                self.queue.put_nowait((sid, fname, node_name))
            asyncio.create_task(_retry_later())
            return error(f"Waiting for deps: {not_ready}")

        if not use_cache:
            my_last = res.get(k, {}).get("updated_at", 0)
            fresh = any(res[dk]["updated_at"] > my_last for dk in dep_keys if dk in res)
            if k in res and not fresh:
                async def _wait_fresh():
                    await asyncio.sleep(0.5)
                    self.queue.put_nowait((sid, fname, node_name))
                asyncio.create_task(_wait_fresh())
                return error("No fresh data from parents yet.")

        completed = [dk for dk in dep_keys if dk in res]
        succeeded = [dk for dk in completed if res[dk]["success"]]

        if policy == "all":
            if len(succeeded) == len(deps): return success(d)
            failed = [dk for dk in completed if not res[dk]["success"]]
            return error(f"policy=all failed: {failed}")

        if policy == "any":
            if len(succeeded) >= 1: return success(d)
            return error("policy=any failed")

        if isinstance(policy, int):
            if len(succeeded) >= policy: return success(d)
            return error(f"policy={policy} >= ({len(succeeded)} succeeded)")

        return error(f"unknown policy: {policy!r}")

    @action()
    async def _check_when(self, d):
        fn = d["node"].get("when")
        if not fn: return success(d)
        if bool(fn(d["ctx"] | d["results"])): return success(d)
        return error("when condition not met")

    @action()
    async def _execute_step(self, d):
        nd, ctx, res = d["node"], d["ctx"], d["results"]
        fname   = d["fname"]
        retries = nd.get("retries", 0)
        delay   = nd.get("retry_delay", 0)

        # Inietta gli output dei dep nel ctx condiviso (by reference)
        # In questo modo le mutazioni del nodo su ctx persistono nella sessione
        if nd.get("meta"):
            for dep in nd.get("deps", []):
                if _key(fname, dep) in res:
                    ctx[dep] = res[_key(fname, dep)]
        else:
            for dep in nd.get("deps", []):
                if _key(fname, dep) in res:
                    ctx[dep] = res[_key(fname, dep)]["outputs"]
        inputs = ctx

        last_result = None
        for i in range(retries + 1):
            try:
                r = await _call(nd["fn"], inputs)
                last_result = r if is_result(r) else success(r, d["t0"])
                if last_result["success"]: break
            except Exception as e:
                last_result = error(e, d["t0"])
            if i < retries:
                await asyncio.sleep(delay)

        d["result"] = last_result
        trace(
            last_result,
            pipeline=fname,
            node=nd["name"],
        )
        return success(d)

    @action()
    async def _run_hook(self, d, hook_name: str):
        nd       = d["node"]
        fname    = d["fname"]
        hook_val = nd.get(hook_name)
        sid      = d["sid"]

        if not hook_val: return success(d)

        try:
            if isinstance(hook_val, (str, list)):
                targets = [hook_val] if isinstance(hook_val, str) else hook_val
                for target in targets:
                    tk = _key(fname, target)
                    if tk in self.sessions[sid]["done"]:
                        self.sessions[sid]["done"][tk].clear()
                    self.queue.put_nowait((sid, fname, target))
            elif callable(hook_val):
                await _call(hook_val, d, d.get("result"))
            return success(d)
        except Exception as e:
            print(f"❌ Hook {hook_name} di {nd['name']}: {e}")
            return success(d)

    @action()
    async def _handle_duration(self, d):
        nd      = d["node"]
        fname   = d["fname"]
        max_dur = nd.get("duration")
        if not max_dur: return success(d)
        k = _key(fname, nd["name"])
        current = d["results"].get(k, {}).get("duration", 0.0)
        if current >= max_dur:
            return error(f"Quota temporale esaurita ({current:.2f}s >= {max_dur}s)")
        return success(d)

    @action()
    async def _save_step(self, d):
        nd, result = d["node"], d["result"]
        fname   = d["fname"]
        session = self.sessions[d["sid"]]
        k       = _key(fname, nd["name"])

        _set(d["ctx"], nd.get("path"), result["outputs"])
        session["results"][k] = result
        session.setdefault("last_seen", {})[k] = result["version"]
        result["duration"] += result["time"]

        return success(d)

    def _auto_starts(self, fname: str, n: str) -> bool:
        """Vero se il nodo può partire da solo in questa run (entry/trigger/schedule),
        oppure se dipende da altri nodi (verrà propagato via dispatch)."""
        nd = self.nodes[fname][n]
        if self.graphs[fname].in_degree(n) > 0:
            return True  # non è root: arriverà via dispatch se il parent parte
        return bool(nd.get("entry", True)) or bool(nd.get("trigger")) or bool(nd.get("schedule"))

    @action()
    async def _dispatch(self, d):
        sid       = d["sid"]
        fname     = d["fname"]
        node_name = d["node"]["name"]
        k         = _key(fname, node_name)
        session   = self.sessions[sid]
        interval  = d["node"].get("schedule")

        for nxt in self.graphs[fname].successors(node_name):
            nxt_k = _key(fname, nxt)
            if not self.nodes[fname][nxt].get("cache") and nxt_k in session["done"]:
                session["done"][nxt_k].clear()
            self.queue.put_nowait((sid, fname, nxt))

        for trg in self.triggers[fname].get(node_name, []):
            self.queue.put_nowait((sid, fname, trg))

        if interval and k not in session["schedulers"]:
            async def _heartbeat(fname=fname, node_name=node_name, k=k):
                try:
                    while sid in self.sessions and sid not in self.cancelled_sessions:
                        await asyncio.sleep(interval)
                        if k in session["done"]:
                            session["done"][k].clear()
                        self.queue.put_nowait((sid, fname, node_name))
                        await session["done"][k].wait()
                except asyncio.CancelledError:
                    pass
            session["schedulers"][k] = asyncio.create_task(_heartbeat())

        return success(d)

    # ─────────────────────────────────────────
    # REACTIVE API
    # ─────────────────────────────────────────

    def get_file_context(self, sid: str, fname: str) -> Dict:
        session = self.sessions.get(sid)
        if not session or fname not in self.nodes:
            return {}

        file_ctx = {}
        # Itera sui nodi definiti in quel file
        for node_name, node_def in self.nodes[fname].items():
            path = node_def.get("path")
            if path:
                # Recupera il valore dal ctx della sessione usando il path
                # (Nota: dovresti implementare una funzione di 'get' speculare a '_set')
                valore = _get_from_path(session["ctx"], path)
                if valore is not None:
                    file_ctx[path] = valore
        return file_ctx

    def update_state(self, sid: str, fname: str, path: str, value: Any):
        """Aggiorna una variabile nel contesto della sessione senza triggerare nessun nodo."""
        if sid not in self.sessions:
            return
        session = self.sessions[sid]
        _set(session["ctx"], path, value)

    def emit(self, sid: str, fname: str, name: str, value: Any = None):
        """Trigger manuale di un nodo specifico."""
        if sid not in self.sessions:
            return
        session = self.sessions[sid]
        if value is not None:
            _set(session["ctx"], name, value)
        # Accoda solo se il nodo esiste davvero nel file
        if fname in self.nodes and name in self.nodes[fname]:
            if _key(fname, name) in session.get("done", {}):
                session["done"][_key(fname, name)].clear()
            self.queue.put_nowait((sid, fname, name))
        else:
            print(f"[emit] Nodo '{name}' non trovato in '{fname}' — ignorato")

    async def wait_node(self, sid: str, fname: str, name: str):
        """Attende il completamento di un nodo specifico."""
        await self.sessions[sid]["done"][_key(fname, name)].wait()