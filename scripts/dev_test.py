from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from scripts.dev import (
    development_port,
    is_managed_opensandbox_url,
    read_env,
    set_env_value,
)


class EnvironmentFileTests(unittest.TestCase):
    def test_set_env_value_replaces_duplicates_without_changing_other_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# local\nTOKEN=old\nOTHER='kept'\nTOKEN=stale\n", encoding="utf-8")

            set_env_value(path, "TOKEN", "new")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "# local\nTOKEN=new\nOTHER='kept'\nTOKEN=new\n",
            )
            self.assertEqual(read_env(path), {"TOKEN": "new", "OTHER": "kept"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_set_env_value_appends_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("EXISTING=value\n", encoding="utf-8")

            set_env_value(path, "ADDED", "value")

            self.assertEqual(read_env(path)["ADDED"], "value")


class OpenSandboxUrlTests(unittest.TestCase):
    def test_accepts_only_the_local_managed_endpoint(self) -> None:
        self.assertTrue(is_managed_opensandbox_url("http://127.0.0.1:8088"))
        self.assertTrue(is_managed_opensandbox_url("http://localhost:8088/"))
        self.assertFalse(is_managed_opensandbox_url("https://127.0.0.1:8088"))
        self.assertFalse(is_managed_opensandbox_url("http://127.0.0.1:8089"))
        self.assertFalse(is_managed_opensandbox_url("http://execution.example:8088"))


class DevelopmentPortTests(unittest.TestCase):
    def test_uses_default_port(self) -> None:
        self.assertEqual(development_port("NEXAFLOW_TEST_UNUSED_PORT", 8000), 8000)


if __name__ == "__main__":
    unittest.main()
