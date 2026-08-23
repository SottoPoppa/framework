from typing import Any

import framework.port.authentication as authentication
import framework.service.flow as flow


class Adapter(authentication.Port):
    """Provider deterministico per i test di integrazione del Defender."""

    def __init__(self, **constants: Any) -> None:
        self.name = constants.get("name", "stub")
        self.config = constants
        self._users: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _user_id(email: str) -> str:
        return email.replace("@", "-").replace(".", "-")

    def _result(self, name: str, email: str) -> dict[str, Any]:
        return {
            "id": name,
            "providers": {
                self.name: {
                    "tokens": {
                        "access_token": f"access-{name}",
                        "refresh_token": f"refresh-{name}",
                    },
                    "user": {"id": name, "email": email},
                }
            },
            "user": {"id": name, "email": email},
        }

    async def sign_up(self, email: str, password: str, **kwargs: Any):
        if email in self._users:
            return flow.error("User already exists")
        user_id = self._user_id(email)
        self._users[email] = {"id": user_id, "email": email, "password": password}
        return flow.success(self._result(user_id, email))

    async def sign_in(self, email: str, password: str):
        user = self._users.get(email)
        if user is None:
            return flow.error("User not found")
        if user["password"] != password:
            return flow.error("Invalid credentials")
        return flow.success(self._result(user["id"], email))

    async def sign_out(self, session: dict[str, Any]):
        return flow.success({"session": session})

    async def get_user(self, session: dict[str, Any]):
        return flow.success(session.get("user", {}))

    async def sign_aid(self, email: str, **kwargs: Any):
        user = self._users.get(email)
        if user is None:
            return flow.error("User not found")
        return flow.success(self._result(user["id"], email))