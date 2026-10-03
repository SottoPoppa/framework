from abc import abstractmethod
from typing import Protocol

import framework.core.flow as flow


class Port(Protocol):
    @abstractmethod
    @flow.result()
    def load_data_store(self) -> object:
        raise NotImplementedError()

    @abstractmethod
    @flow.result()
    def load_policies(self) -> object:
        raise NotImplementedError()


port = Port
    