from abc import ABC, abstractmethod

import framework.core.flow as flow

class Port(ABC):

    # Mappa: nome_metodo -> decoratore da applicare automaticamente
    _method_decorators = {
        "sign_in":      flow.result(inputs=("email", "password")),
        "sign_up":      flow.result(inputs=("email", "password")),
        "sign_out":     flow.result(inputs=("session",),          outputs=("session",)),
        "sign_aid":     flow.result(safe_kwargs=True),
        "get_user": flow.result(inputs=("session",)),
    }

    _seeds = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method_name, decorator in Port._method_decorators.items():
            if method_name in cls.__dict__:  # solo se definito direttamente
                original = cls.__dict__[method_name]
                setattr(cls, method_name, decorator(original))

    @abstractmethod
    def sign_in(self,email,password):
        pass

    @abstractmethod
    def sign_up(self,email,password):
        pass

    @abstractmethod
    def sign_out(self,access_token):
        pass

    @abstractmethod
    def get_user(self,access_token):
        pass

    @abstractmethod
    def sign_aid(self,email):
        pass