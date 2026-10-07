import unittest
from pathlib import Path
from typing import Any, Literal, assert_type, cast
from unittest.mock import AsyncMock

from framework.core import flow
from framework.core.session import SessionData
from framework.manager.storekeeper import Manager as StorekeeperManager
from framework.scheme.models import (
    DomainScheme,
    SessionScheme,
    SessionDataScheme,
    StorekeeperScheme,
    UserScheme as JsonUserScheme,
)
from framework.service.scheme_codegen import PROJECT_ROOT, render_stub
from framework.service.scheme import Scheme, normalize


class PasswordScheme(Scheme):
    digest: str


class UserScheme(Scheme):
    password: PasswordScheme


class SchemeRuntimeTypeTests(unittest.TestCase):
    def test_typed_constructor_preserves_nested_scheme_type(self):
        user = UserScheme(password=PasswordScheme(digest="pbkdf2-hash"))

        assert_type(user.password, PasswordScheme)
        self.assertIsInstance(user.password, PasswordScheme)
        self.assertEqual(user.password.digest, "pbkdf2-hash")

    def test_from_mapping_builds_nested_scheme(self):
        user = UserScheme.from_mapping(
            {"password": {"digest": "pbkdf2-hash"}}
        )

        self.assertIsInstance(user.password, PasswordScheme)
        self.assertEqual(user.password.digest, "pbkdf2-hash")

    def test_normalize_with_scheme_type_returns_nested_scheme(self):
        result = normalize(
            {"password": {"digest": "pbkdf2-hash"}}, UserScheme
        )

        self.assertTrue(result.is_success)
        user = flow.output(result)
        self.assertIsInstance(user, UserScheme)
        self.assertIsInstance(user.password, PasswordScheme)

    def test_normalize_preserves_legacy_session_data_constructor(self):
        result = normalize(
            {
                "id": "session-1",
                "context": {},
                "authentication": {},
                "results": {},
            },
            SessionData,
        )

        self.assertTrue(result.is_success)
        self.assertIsInstance(flow.output(result), SessionData)

    def test_session_data_uses_generated_json_scheme(self):
        session = SessionData.from_dict(
            {
                "id": "session-1",
                "context": {},
                "authentication": {},
                "results": {},
            }
        )

        assert_type(session.id, str)
        assert_type(session.context, dict[str, Any])
        self.assertIsInstance(session, SessionDataScheme)

    def test_from_mapping_rejects_invalid_nested_field_type(self):
        with self.assertRaises(ValueError):
            UserScheme.from_mapping({"password": {"digest": 123}})

    def test_from_mapping_rejects_missing_required_field(self):
        with self.assertRaises(ValueError):
            PasswordScheme.from_mapping({})


class GeneratedJsonSchemeTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_required_flag_stays_optional(self):
        domain = DomainScheme.from_mapping(
            {"id": "d1", "domain": "example.test", "status": "active"}
        )

        assert_type(domain.owner, str | None)
        self.assertNotIn("ssl_enabled", domain)
        self.assertNotIn("owner", domain)
        self.assertIsNone(domain.owner)

    def test_json_allowed_values_are_literals_and_validated(self):
        user = JsonUserScheme(
            identifier="u1",
            username="mario",
            role="admin",
            avatar="avatar.png",
        )

        assert_type(user.role, Literal["admin", "user", "guest"])
        self.assertEqual(user.role, "admin")
        with self.assertRaises(ValueError):
            JsonUserScheme(
                identifier="u1",
                username="mario",
                role=cast(Any, "owner"),
                avatar="avatar.png",
            )

    def test_json_schema_reference_builds_nested_scheme(self):
        session = SessionScheme.from_mapping(
            {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "providers": {},
                "user": {
                    "identifier": "u1",
                    "username": "mario",
                    "role": "admin",
                    "avatar": "avatar.png",
                },
            }
        )

        assert_type(session.user, JsonUserScheme)
        assert_type(session.user.role, Literal["admin", "user", "guest"])
        self.assertIsInstance(session.user, JsonUserScheme)

    def test_storekeeper_json_generates_defaults_and_literal_type(self):
        storekeeper = StorekeeperScheme(
            provider="git",
            repository="tasks",
        )

        assert_type(
            storekeeper.operation,
            Literal["create", "read", "update", "delete", "view"],
        )
        self.assertEqual(storekeeper.operation, "read")

    async def test_storekeeper_manager_uses_scheme_for_flat_constants(self):
        manager = cast(StorekeeperManager, object.__new__(StorekeeperManager))
        repository = object()
        constants = {
            "provider": "test",
            "repository": "tasks",
            "operation": "create",
            "payload": {"id": "task-1"},
            "id": "task-1",
            "exclude_dirs": [".git"],
        }
        load_repository = AsyncMock(return_value=flow.success(repository))
        prepare_operations = AsyncMock(return_value=flow.success([]))
        setattr(manager, "_load_repository", load_repository)
        setattr(manager, "_prepare_operations", prepare_operations)

        result = await manager.preparation(object(), constants)

        self.assertTrue(result.is_success)
        load_repository.assert_awaited_once_with("tasks")
        prepare_operations.assert_awaited_once()
        arguments = prepare_operations.await_args.args
        self.assertIsInstance(arguments[1], StorekeeperScheme)
        self.assertEqual(arguments[1].operation, "create")
        self.assertEqual(arguments[2], constants)

    def test_generated_stub_matches_json_sources(self):
        stub_path = PROJECT_ROOT / "src/framework/scheme/models.pyi"

        self.assertEqual(stub_path.read_text(encoding="utf-8"), render_stub())


if __name__ == "__main__":
    unittest.main()