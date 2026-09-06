from . import data
from .data import MISSING

class ExecutionContext:
    def __init__(self, initial=None): self._data = dict(initial or {})
    @property
    def data(self): return self._data
    def get(self, path, default=MISSING): return data.resolve(self._data, path, default=default)
    def set(self, path, value): data.publish(self._data, path, value)
    def exists(self, path): return data.exists(self._data, path)
    def delete(self, path): return data.delete(self._data, path)
    def snapshot(self): return dict(self._data)

