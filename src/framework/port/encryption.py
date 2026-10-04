from abc import ABC, abstractmethod
from typing import Any

# encrypted

class encryption(ABC):

    @abstractmethod
    def loader(**constants: Any) -> Any:
        pass

    @abstractmethod
    def encryption(self, **constants: Any) -> Any:
        pass

    @abstractmethod
    def decryption(self, **constants: Any) -> Any:
        pass