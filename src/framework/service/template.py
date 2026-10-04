from __future__ import annotations

import os
from time import perf_counter
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, cast

from jinja2 import (
    Environment,
    FileSystemLoader,
    TemplateError,
    TemplateNotFound,
    TemplateSyntaxError,
    Undefined,
    nodes,
    select_autoescape,
)
from jinja2.exceptions import TemplateRuntimeError, UndefinedError
from jinja2.ext import Extension
from jinja2.parser import Parser
from jinja2.runtime import Context
import framework.core.flow as flow
import framework.service.dom as dom
from framework.service.diagnostic import get_logger


TEMPLATE_RENDER_CONTEXT_KEY = "_template_context"


class DeferredUndefined(Undefined):
    """Preserva le espressioni Jinja non risolte nel primo passaggio."""

    def __init__(
        self,
        hint: str | None = None,
        obj: Any = None,
        name: str | None = None,
        exc: type[TemplateRuntimeError] = UndefinedError,
        expression: str | None = None,
    ) -> None:
        super().__init__(hint=hint, obj=obj, name=name, exc=exc)
        self._expression: str = expression or name or ""

    def __getattr__(self, name: str) -> DeferredUndefined:
        if name.startswith("__"):
            raise AttributeError(name)
        return type(self)(expression=f"{self._expression}.{name}")

    def __getitem__(self, key: Any) -> DeferredUndefined:
        if isinstance(key, str):
            expression = f"{self._expression}[{key!r}]"
        else:
            expression = f"{self._expression}[{key}]"
        return type(self)(expression=expression)

    def __str__(self) -> str:
        return "{{ " + self._expression + " }}"

    def __html__(self) -> str:
        return str(self)

    def __bool__(self) -> bool:
        return False

    def __iter__(self) -> Iterator[Any]:
        return iter(())


class AsyncBlockExtension(Extension):
    tags = {"storekeeper", "messenger"}

    def parse(self, parser: Parser) -> nodes.Node:
        token = next(parser.stream)
        block_name = token.value
        args, kwargs, dynamic_args, dynamic_kwargs = parser.parse_call_args()
        if args or dynamic_args is not None or dynamic_kwargs is not None:
            raise TemplateSyntaxError(
                f"{block_name} accetta solo argomenti nominati",
                token.lineno,
            )
        parser.stream.expect("name:as")
        variable = parser.stream.expect("name").value
        body = parser.parse_statements(
            (f"name:end{block_name}",),
            drop_needle=True,
        )
        call = self.call_method(
            "_render",
            [nodes.ContextReference(), nodes.Const(block_name)],
            kwargs=kwargs,
            lineno=token.lineno,
        )
        return nodes.CallBlock(
            call,
            [nodes.Name(variable, "param")],
            [],
            body,
        ).set_lineno(token.lineno)

    async def _render(
        self,
        context: Context,
        block_name: str,
        caller: Any,
        **request: Any,
    ) -> Any:
        loaders = cast(
            dict[str, Any], context.get("_async_block_loaders", {})
        )
        loader: Any = loaders.get(block_name)
        if not callable(loader):
            raise RuntimeError(
                f"Blocco Jinja '{block_name}' non disponibile nel template"
            )
        started = perf_counter()
        value = await cast(Callable[..., Awaitable[Any]], loader)(request)
        get_logger("template").debug(
            "Blocco asincrono completato",
            block=block_name,
            operation=request.get("operation", "receive" if block_name == "messenger" else "gather"),
            repository=request.get("repository"),
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return await cast(Callable[..., Awaitable[Any]], caller)(value)


def _result_output(value: Any) -> Any:
    """Restituisce il payload sia da un Result sia dalla sua forma serializzata."""
    if flow.is_result(value):
        return flow.output(value)
    if isinstance(value, dict):
        result_data = cast(dict[str, Any], value)
        output = result_data.get("output")
        output_data = (
            cast(dict[str, Any], output) if isinstance(output, dict) else None
        )
        if output_data is not None and "is_success" in output_data:
            return (
                output_data.get("value")
                if output_data["is_success"]
                else output_data.get("error")
            )
        return result_data
    return value


def _result_success(value: Any) -> bool:
    """Indica se un valore rappresenta un risultato riuscito."""
    if flow.is_result(value):
        return value.is_success
    if isinstance(value, dict):
        result_data = cast(dict[str, Any], value)
        output = result_data.get("output")
        output_data = (
            cast(dict[str, Any], output) if isinstance(output, dict) else None
        )
        if output_data is not None and "is_success" in output_data:
            return bool(output_data["is_success"])
    return True


def _template_filters() -> dict[str, Any]:
    def get_filter(data: Any, key: Any) -> Any:
        if isinstance(data, dict):
            return cast(dict[Any, Any], data).get(key)
        return None

    return {
        "value": _result_output,
        "check": _result_success,
        "get": get_filter,
    }


def get_jinja(
    infrastructure: Any | None = None,
    **options: Any,
) -> Environment:
    """Restituisce un ambiente Jinja, usando la cache se disponibile."""
    key = tuple(sorted((name, id(value)) for name, value in options.items()))
    if infrastructure is None:
        environment = Environment(**options)
    else:
        environment = infrastructure.jinja_environments.get(key)
        if environment is None:
            environment = Environment(**options)
            infrastructure.jinja_environments[key] = environment
    environment.filters.update(_template_filters())
    return environment


def _select_environment(infrastructure: Any, target: str) -> Environment:
    default = get_jinja(infrastructure)
    try:
        references = [
            node.template.value
            for node in default.parse(target).find_all(
                (nodes.Include, nodes.Extends, nodes.Import, nodes.FromImport)
            )
            if isinstance(node.template, nodes.Const)
            and isinstance(node.template.value, str)
        ]
    except Exception:
        return default
    if not references:
        return default
    for environment in infrastructure.jinja_environments.values():
        loader = getattr(environment, "loader", None)
        if loader is None:
            continue
        try:
            for reference in references:
                loader.get_source(environment, reference)
        except TemplateNotFound:
            continue
        return environment
    return default


def render_jinja(
    infrastructure: Any,
    target: str,
    context: dict[str, Any] | None = None,
    environment: Environment | None = None,
) -> str:
    if "{{" not in target and "{%" not in target and "{#" not in target:
        return target
    environment = environment or _select_environment(infrastructure, target)
    def env(name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    payload: dict[str, Any] = {
        "env": env,
        **(context or {}),
    }
    return environment.from_string(target).render(**payload)


async def format(
    target: Any,
    infrastructure: Any | None = None,
    **constants: Any,
) -> Any:
    """Formatta una stringa usando l'ambiente Jinja dell'infrastruttura."""
    try:
        if not target:
            return target
        if not isinstance(target, str):
            target = str(target)
        if "{" not in target:
            return target
        environment = get_jinja(
            infrastructure,
            autoescape=select_autoescape(["html", "xml"]),
        )
        return render_jinja(
            infrastructure,
            target,
            context=constants,
            environment=environment,
        )
    except Exception as e:
        raise ValueError(f"Errore formattazione: {e}")


async def render(
    infrastructure: Any,
    managers: Any,
    runtime_session: Any,
    render_node: Callable[..., Awaitable[Any]],
    text: Any = None,
    file: str | None = None,
    controller_context: dict[str, Any] | None = None,
    source_name: str | None = None,
    async_block_loaders: dict[str, Callable[..., Awaitable[Any]]] | None = None,
    **constants: Any,
) -> Any:
    logger = get_logger("template")
    render_started = perf_counter()
    if text is None and file is None:
        raise ValueError("No text or file provided")
    if text is None:
        text = infrastructure.resource(file)
    elif isinstance(text, dom.element_type()):
        text = dom.serialize(cast(Any, text))
    elif not isinstance(text, str):
        text = str(text)
    text = cast(str, text)
    source_name = source_name or file or "template string"

    environment = get_jinja(
        infrastructure,
        loader=FileSystemLoader("src/application/view/layout/"),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=DeferredUndefined,
        extensions=(AsyncBlockExtension,),
        enable_async=True,
    )
    compile_started = perf_counter()
    try:
        template = environment.from_string(text)
    except TemplateError as error:
        line = getattr(error, "lineno", None)
        location = f" riga {line}" if line else ""
        raise flow.LocatedError(
            f"Errore sintassi Jinja in '{source_name}'{location}: {error}",
            source_file=source_name,
            source_line=line,
            source_function="Jinja template",
        ) from error
    logger.debug(
        "Template compilato",
        source=source_name,
        duration_ms=round((perf_counter() - compile_started) * 1000, 2),
    )
    manager_context: dict[str, Any] = {"manager": managers}
    render_context: dict[str, Any] = constants | (controller_context or {}) | manager_context
    template_context: dict[str, Any] = render_context
    if async_block_loaders is not None:
        template_context = {
            **render_context,
            "_async_block_loaders": async_block_loaders,
        }
    jinja_started = perf_counter()
    content = await template.render_async(template_context)
    logger.info(
        "Jinja render completato",
        source=source_name,
        duration_ms=round((perf_counter() - jinja_started) * 1000, 2),
        characters=len(content),
    )
    xml_started = perf_counter()
    try:
        xml = dom.parse(content)
    except dom.parse_error() as error:
        line, column = cast(
            tuple[int | None, int | None],
            getattr(error, "position", (None, None)),
        )
        rendered_line: str | None = None
        if line and 1 <= line <= len(content.splitlines()):
            rendered_line = content.splitlines()[line - 1].strip()
        raise flow.LocatedError(
            f"Errore XML in '{source_name}': {error}",
            source_file=source_name,
            source_line=line,
            source_column=column,
            source_function="rendered XML",
            source_code=rendered_line,
            source_context=(
                f"> {line}: {rendered_line}" if line and rendered_line else None
            ),
        ) from error
    logger.debug(
        "XML template analizzato",
        source=source_name,
        duration_ms=round((perf_counter() - xml_started) * 1000, 2),
    )
    widgets_started = perf_counter()
    rendered = await render_node(
        content,
        xml,
        {TEMPLATE_RENDER_CONTEXT_KEY: render_context},
        runtime_session=runtime_session,
    )
    logger.info(
        "Widget template costruiti",
        source=source_name,
        duration_ms=round((perf_counter() - widgets_started) * 1000, 2),
        total_duration_ms=round((perf_counter() - render_started) * 1000, 2),
    )
    return rendered
