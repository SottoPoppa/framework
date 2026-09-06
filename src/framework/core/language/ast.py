from dataclasses import dataclass
@dataclass(frozen=True)
class Program: statements: tuple
@dataclass(frozen=True)
class Assignment: name: str; value: object
@dataclass(frozen=True)
class Task:
    name: str; action: object; entry: bool=True; deps: bool=True; on_end: str|None=None
