from abc import ABC, abstractmethod
from typing import Any

# encrypted

class encryption(ABC):

    @abstractmethod
    def loader(**constants: Any) -> object:
        pass

    @abstractmethod
    def encryption(self, **constants: Any) -> object:
        pass

    @abstractmethod
    def decryption(self, **constants: Any) -> object:
        pass