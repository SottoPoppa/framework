"""DAG engine based on returns.Result."""

import asyncio
import functools
import inspect
import time
import traceback
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

import networkx as nx
from returns.result import Failure, Result, Success

import framework.service.scheme as scheme


class FlowError(Exception):
    pass


@dataclass
class DependencyError(FlowError):
    node: str
    dependencies: list[str]
    failed: list[str]


@dataclass
class DependencyPolicyError(FlowError):
    node: str
    policy: object
    succeeded: int
    required: int


@dataclass
class WaitingForDependencies(FlowError):
    node: str
    dependencies: list[str]


@dataclass
class ConditionError(FlowError):
    node: str


@dataclass
class NodeExecutionError(FlowError):
    node: str
    cause: BaseException

    def __str__(self):
        return f"{self.node}: {self.cause}"


@dataclass
class ValidationError(FlowError):
    action: str
    details: object


class NodeState(Enum):
    WAITING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()


@dataclass
class NodeExecution:
    file: str
    node: str
    result: Result
    started_at: float
    duration: float
    state: NodeState
    version: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class Transaction:
    action: str
    started_at: float
    duration: float
    success: bool
    error: FlowError | None = None
    component: str | None = None


_transaction_stack = ContextVar("flow_transactions", default=None)


def success(value):
    return Success(value)


def error(exception: BaseException | str):
    return Failure(exception if isinstance(exception, BaseException) else FlowError(str(exception)))


def format_error(exception: BaseException) -> str:
    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))


def _require_result(value) -> Result:
    if not isinstance(value, Result):
        raise TypeError(f"Expected Result, got {type(value).__name__}")
    return value


async def _call(function, *args, **kwargs):
    value = function(*args, **kwargs) if callable(function) else function
    return await value if inspect.isawaitable(value) else value


def _track(action: str, started: float, result: Result, component: str):
    stack = _transaction_stack.get()
    if stack is not None:
        stack.append(Transaction(action, started, time.perf_counter() - started,
                                 isinstance(result, Success),
                                 result.failure() if isinstance(result, Failure) else None,
                                 component))


def result(inputs=None, outputs=None, safe_kwargs=False):
    def decorate(function):
        @functools.wraps(function)
        async def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                call_kwargs = await _normalize_inputs(inputs, kwargs)
                value = await _call(function, *args, **call_kwargs)
                current = value if isinstance(value, Result) else Success(value)
                current = await _normalize_outputs(function.__name__, outputs, current)
            except ValueError as exception:
                current = error(ValidationError(function.__qualname__, str(exception)))
            except Exception as exception:
                current = error(NodeExecutionError(function.__name__, exception))
            _track(function.__name__, started, current, function.__module__)
            return current
        return wrapper
    return decorate


async def _normalize_inputs(inputs, kwargs):
    if isinstance(inputs, (tuple, list)):
        return {key: value for key, value in kwargs.items() if key in inputs}
    models = getattr(scheme, "schemes", {})
    if inputs in models:
        normalized = await scheme.normalize(kwargs, models[inputs])
        if normalized.get("errors"):
            raise ValueError(f"Validation errors: {normalized['errors']}")
        return normalized["data"]
    return kwargs


async def _normalize_outputs(action_name, outputs, result):
    if not outputs or isinstance(result, Failure):
        return result
    value = result.unwrap()
    if isinstance(outputs, (tuple, list)):
        return Success({key: value[key] for key in outputs})
    models = getattr(scheme, "schemes", {})
    if outputs not in models:
        return result
    normalized = await scheme.normalize(value, models[outputs])
    return error(ValidationError(action_name, normalized["errors"])) if normalized["errors"] else Success(normalized["data"])


async def _pipe(current: Result, function) -> Result:
    if isinstance(current, Failure):
        return current
    try:
        return _require_result(await _call(function, current.unwrap()))
    except Exception as exception:
        return error(exception)


async def pipeline(value, *functions):
    current = _require_result(value)
    for function in functions:
        current = await _pipe(current, function)
    return current


async def act(step):
    if not isinstance(step, tuple):
        return error(FlowError("invalid step"))
    function, args, kwargs = step
    try:
        return _require_result(await _call(function, *args, **kwargs))
    except Exception as exception:
        return error(exception)


def step(function, *args, **kwargs):
    return function, args, kwargs


async def branch(condition, context, branches):
    selected = condition if isinstance(condition, bool) else condition(**context)
    return _require_result(await _call(branches[selected], context))


def foreach(iterable, function, args=()):
    async def apply(view):
        items = view.get("items", iterable)
        values = []
        for item in items:
            values.append(await _call(function, view, item, *args))
        return Success(values)
    return apply


async def reset(old, new):
    return Success(new)


async def switch(data, cases):
    for condition, function in cases.items():
        if condition is not True and callable(condition) and condition(**data):
            return _require_result(await _call(function, data))
    default = cases.get(True)
    return _require_result(await _call(default, data)) if callable(default) else Success(default)


def node(name: str, fn: Callable, **options):
    return {"name": name, "fn": fn, "default": options.get("default"),
            "deps": options.get("deps", []), "policy": options.get("policy", "all"),
            "meta": options.get("meta", False), "trigger": options.get("trigger"),
            "schedule": options.get("schedule"), "duration": options.get("duration"),
            "timeout": options.get("timeout", 30), "retries": options.get("retries", 0),
            "retry_delay": options.get("retry_delay", 0), "when": options.get("when"),
            "path": options.get("path", name), "cache": options.get("cache", False),
            "on_start": options.get("on_start"), "on_success": options.get("on_success"),
            "on_error": options.get("on_error"), "on_end": options.get("on_end"),
            "entry": options.get("entry", True)}


def _set(context, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        context = context.setdefault(part, {})
    context[parts[-1]] = value


def _set_default(context, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        context = context.setdefault(part, {})
    context.setdefault(parts[-1], value)


def _get(context, path, default=None):
    for part in path.split(".") if path else ():
        if not isinstance(context, dict) or part not in context:
            return default
        context = context[part]
    return context


def _merge_defaults(target, source):
    for key, value in source.items():
        if key not in target:
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge_defaults(target[key], value)


def _key(file, name):
    return f"{file}::{name}"


class DagRunner:
    def __init__(self, workers=3):
        self.workers = workers
        self.graphs, self.nodes, self.triggers = {}, {}, {}
        self._file_defaults, self.sessions = {}, {}
        self.queue, self.tasks, self.running = asyncio.Queue(), [], False
        self.cancelled_sessions = set()

    async def add_file(self, name, definitions):
        graph = nx.DiGraph()
        nodes = {item["name"]: item for item in definitions}
        for item in definitions:
            graph.add_node(item["name"])
            graph.add_edges_from((dependency, item["name"]) for dependency in item.get("deps", []) if dependency in nodes)
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError(f"Il file '{name}' contiene cicli")
        self.graphs[name], self.nodes[name] = graph, nodes
        self.triggers[name] = {}
        for item in definitions:
            if item.get("trigger"):
                self.triggers[name].setdefault(item["trigger"], []).append(item["name"])
        self._file_defaults[name] = {item["name"]: item["default"] for item in definitions if item.get("default") is not None}
        for session in self.sessions.values():
            for key, value in self._file_defaults[name].items():
                _set_default(session["ctx"], key, value)

    async def delete_file(self, name):
        for store in (self.graphs, self.nodes, self.triggers, self._file_defaults):
            store.pop(name, None)

    def attach_node(self, file, definition):
        if file not in self.graphs or definition["name"] in self.nodes[file]:
            return
        self.nodes[file][definition["name"]] = definition
        self.graphs[file].add_node(definition["name"])
        for dependency in definition.get("deps", []):
            if dependency in self.nodes[file]:
                self.graphs[file].add_edge(dependency, definition["name"])

    def create_session(self, sid, context=None):
        session = self.sessions.setdefault(sid, {"ctx": {}, "results": {}, "executions": {}, "states": {}, "done": {}, "schedulers": set(), "running_files": set()})
        for defaults in self._file_defaults.values():
            for key, value in defaults.items():
                _set_default(session["ctx"], key, value)
        if context:
            session["ctx"].update(context)

    def context(self, sid):
        return self.sessions.get(sid, {}).get("ctx", {})

    async def run_file(self, sid, file, ctx_update=None):
        if sid not in self.sessions:
            raise ValueError(f"FLOW -> Sessione '{sid}' non trovata.")
        if file not in self.graphs:
            raise ValueError(f"File '{file}' non registrato.")
        session = self.sessions[sid]
        if ctx_update:
            _merge_defaults(session["ctx"], ctx_update)
        session["running_files"].add(file)
        for name in self.nodes[file]:
            key = _key(file, name)
            session["done"][key] = asyncio.Event()
            session["states"][key] = NodeState.WAITING
        if not self.running:
            await self.start()
        for name in self.graphs[file]:
            if self.graphs[file].in_degree(name) == 0 and self.nodes[file][name].get("entry", True):
                self.queue.put_nowait((sid, file, name))
        await asyncio.gather(*(session["done"][_key(file, name)].wait() for name in self.nodes[file] if not self.nodes[file][name].get("schedule")))
        session["running_files"].discard(file)
        return {name: session["results"][_key(file, name)] for name in self.nodes[file] if _key(file, name) in session["results"]}

    async def start(self):
        self.running = True
        self.tasks = [asyncio.create_task(self._worker()) for _ in range(self.workers)]

    async def stop(self):
        self.running = False
        for task in self.tasks:
            task.cancel()

    async def _worker(self):
        while self.running:
            try:
                item = await asyncio.wait_for(self.queue.get(), .2)
            except asyncio.TimeoutError:
                continue
            try:
                if item[0] not in self.cancelled_sessions:
                    await self._run_node(*item)
            finally:
                self.queue.task_done()

    async def _run_node(self, sid, file, name):
        session, definition = self.sessions[sid], self.nodes[file][name]
        key = _key(file, name)
        session["states"][key] = NodeState.RUNNING
        context = {"sid": sid, "fname": file, "node": definition, "ctx": session["ctx"], "results": session["results"], "session": session, "result": None, "t0": time.perf_counter()}
        result = await pipeline(Success(context), self._check_deps, self._check_when, self._execute, self._save, self._dispatch)
        if isinstance(result, Failure):
            session["results"][key] = result
            session["states"][key] = NodeState.FAILED
        else:
            session["states"][key] = NodeState.SUCCESS
        session["done"][key].set()

    async def _check_deps(self, context):
        definition, session, file = context["node"], context["session"], context["fname"]
        dependencies = [_key(file, dependency) for dependency in definition.get("deps", [])]
        pending = [key for key in dependencies if key in session["done"] and not session["done"][key].is_set()]
        if pending and not definition.get("cache"):
            return error(WaitingForDependencies(definition["name"], pending))
        succeeded = [key for key in dependencies if isinstance(session["results"].get(key), Success)]
        policy = definition.get("policy", "all")
        required = len(dependencies) if policy == "all" else 1 if policy == "any" else policy
        if dependencies and not isinstance(required, int):
            return error(DependencyPolicyError(definition["name"], policy, len(succeeded), len(dependencies)))
        if dependencies and len(succeeded) < required:
            failed = [key for key in dependencies if isinstance(session["results"].get(key), Failure)]
            return error(DependencyError(definition["name"], dependencies, failed))
        return Success(context)

    async def _check_when(self, context):
        condition = context["node"].get("when")
        return Success(context) if not condition or condition(context["ctx"] | context["results"]) else error(ConditionError(context["node"]["name"]))

    async def _execute(self, context):
        definition, session, file = context["node"], context["session"], context["fname"]
        for dependency in definition.get("deps", []):
            result = session["results"].get(_key(file, dependency))
            if isinstance(result, Success):
                context["ctx"][dependency] = result.unwrap()
        last = None
        retries = definition.get("retries", 0)
        for attempt in range(retries + 1):
            try:
                last = _require_result(await _call(definition["fn"], context["ctx"]))
            except Exception as exception:
                last = error(NodeExecutionError(definition["name"], exception))
            if isinstance(last, Success) or attempt == retries:
                break
            await asyncio.sleep(definition.get("retry_delay", 0))
        context["result"] = last
        return Success(context)

    async def _save(self, context):
        definition, session, file = context["node"], context["session"], context["fname"]
        key, result = _key(file, definition["name"]), context["result"]
        session["results"][key] = result
        if isinstance(result, Success):
            _set(context["ctx"], definition.get("path"), result.unwrap())
        session["executions"][key] = NodeExecution(file, definition["name"], result, context["t0"], time.perf_counter() - context["t0"], NodeState.SUCCESS if isinstance(result, Success) else NodeState.FAILED)
        return Success(context)

    async def _dispatch(self, context):
        sid, file, name = context["sid"], context["fname"], context["node"]["name"]
        for child in self.graphs[file].successors(name):
            self.queue.put_nowait((sid, file, child))
        for target in self.triggers[file].get(name, []):
            self.queue.put_nowait((sid, file, target))
        return Success(context)

    async def close_session(self, sid):
        session = self.sessions.pop(sid, None)
        if session:
            for task in session["schedulers"]:
                task.cancel()

    async def clear_all_sessions(self):
        for sid in list(self.sessions):
            await self.close_session(sid)

    def get_file_context(self, sid, file):
        session = self.sessions.get(sid)
        if not session or file not in self.nodes:
            return {}
        return {definition["path"]: _get(session["ctx"], definition["path"]) for definition in self.nodes[file].values() if _get(session["ctx"], definition["path"]) is not None}

    def update_state(self, sid, file, path, value):
        if sid in self.sessions:
            _set(self.sessions[sid]["ctx"], path, value)

    def emit(self, sid, file, name, value=None):
        if sid not in self.sessions or file not in self.nodes or name not in self.nodes[file]:
            return
        session = self.sessions[sid]
        if value is not None:
            _set(session["ctx"], name, value)
        session["done"].setdefault(_key(file, name), asyncio.Event()).clear()
        self.queue.put_nowait((sid, file, name))

    async def wait_node(self, sid, file, name):
        await self.sessions[sid]["done"][_key(file, name)].wait()
