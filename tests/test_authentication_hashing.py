import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import framework.core.flow as flow
from framework.manager.defender import Manager as Defender
from infrastructure.authentication.stub import Adapter


class StubPasswordHashingTests(unittest.IsolatedAsyncioTestCase):
    async def test_password_is_salted_hashed_and_verified(self):
        adapter = Adapter()

        registered = await adapter.sign_up("alice@example.test", "correct horse")
        stored_user = adapter._users["alice@example.test"]
        encoded = stored_user["password_hash"]
        algorithm, iterations, salt, _ = encoded.split("$", 3)

        self.assertTrue(flow.check(registered))
        self.assertTrue(adapter.capabilities["password_hashing"])
        self.assertFalse(adapter.capabilities["mfa"])
        self.assertFalse(adapter.capabilities["token_rotation"])
        self.assertFalse(
            Defender.__new__(Defender)._profile_satisfies(
                {
                    "password_hashing": True,
                    "mfa": True,
                    "token_rotation": True,
                },
                adapter.capabilities,
            )
        )
        self.assertNotIn("password", stored_user)
        self.assertEqual(algorithm, "pbkdf2_sha256")
        self.assertEqual(int(iterations), adapter._password_iterations)
        self.assertEqual(len(salt), 32)
        self.assertTrue(
            flow.check(await adapter.sign_in("alice@example.test", "correct horse"))
        )
        self.assertFalse(
            flow.check(await adapter.sign_in("alice@example.test", "wrong password"))
        )


if __name__ == "__main__":
    unittest.main()
