import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from public import main as cli


class DevPyrightGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_dev_stops_before_bootstrap_when_pyright_fails(self):
        framework_instance = Mock()
        executable = os.path.join(cli.cwd, "venv", "bin", "pyright")

        with (
            patch(
                "public.main.framework.Framework",
                return_value=framework_instance,
            ),
            patch(
                "public.main.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, executable),
            ) as run,
        ):
            result = await cli.main({"dev": True})

        self.assertFalse(result)
        run.assert_called_once_with([executable], cwd=cli.cwd, check=True)
        framework_instance.bootstrap.assert_not_called()