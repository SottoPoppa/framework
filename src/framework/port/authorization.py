from abc import ABC, abstractmethod

import framework.core.flow as flow


class port(ABC):
    def __init__(self):
        #self.server = Server(ldap_server, get_info=ALL)
        #self.user_dn = user_dn
        #self.password = password
        pass

    @abstractmethod
    @flow.result()
    def load_data_store(self):
        raise NotImplementedError()

    @abstractmethod
    @flow.result()
    def load_policies(self):
        raise NotImplementedError()
    