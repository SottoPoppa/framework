"""Caricamento dei programmi DSL: testo → AST → definizione del DAG.

Il risultato è un artefatto puro e immutabile, indicizzato per nome e per hash
del sorgente: ricaricare lo stesso testo non ricompila nulla.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from lark.exceptions import UnexpectedInput

from .compiler import Compiler
from .model import DagDefinition
from .parser import Parser


class DSLSourceError(ValueError):
    """Errore DSL con posizione e fase, utile ai client di tooling."""

    def __init__(self, source: str, phase: str, message: str, error: Any = None):
        self.source = source
        self.phase = phase
        self.line = getattr(error, "line", None)
        self.column = getattr(error, "column", None)
        location = ""
        if self.line is not None:
            location = f":{self.line}"
            if self.column is not None:
                location += f":{self.column}"
        super().__init__(f"Errore {phase} in '{source}'{location}: {message}")


@dataclass(frozen=True, slots=True)
class Program:
    """Programma DSL compilato: dato puro, confrontabile e trasferibile."""

    name: str
    digest: str
    definition: DagDefinition


class ProgramLoader:
    """Parser + compiler con cache sul contenuto del sorgente."""

    def __init__(self, parser: Parser | None = None, compiler: Compiler | None = None):
        self.parser = parser or Parser()
        self.compiler = compiler or Compiler()
        self._cache: dict[tuple[str, str], Program] = {}

    @staticmethod
    def digest(source: str) -> str:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def parse(self, source: str, name: str = "<string>"):
        """Parsa senza compilare, per tooling e diagnostica."""
        try:
            return self.parser.parse(source)
        except UnexpectedInput as error:
            raise DSLSourceError(
                name, "parsing DSL", str(error).splitlines()[0], error
            ) from error

    def load(self, name: str, source: str) -> Program:
        digest = self.digest(source)
        cached = self._cache.get((name, digest))
        if cached is not None:
            return cached

        tree = self.parse(source, name)
        try:
            definition = self.compiler.compile(tree, name=name)
        except DSLSourceError:
            raise
        except Exception as error:
            raise DSLSourceError(name, "compilazione DSL", str(error)) from error

        program = Program(name, digest, definition)
        self._cache[(name, digest)] = program
        return program
