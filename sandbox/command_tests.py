"""Host-safe command tests; Linux UID escape checks also run in the image."""

import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from . import command


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.workspace = root / "workspace"
        for name, value in (("WORKSPACE", self.workspace), ("EXPORTS", root / "exports"), ("SESSION", root / "session")):
            self.stack.enter_context(patch.object(command, name, value))
        self.stack.enter_context(patch.object(command, "_child_limits"))
        self.stack.enter_context(patch.object(command, "kill_user_processes"))
        self.stack.enter_context(patch.object(command.os, "geteuid", return_value=0))
        self.stack.enter_context(patch.object(command.os, "chown"))
        # The real export owner is checked in the Linux guest. Local tests
        # keep all files owned by the invoking developer.
        self.real_lstat = Path.lstat
        def lstat(path):
            info = self.real_lstat(path)
            if path == command.EXPORTS:
                values = list(info)
                values[4] = 0
                return command.os.stat_result(values)
            return info
        self.stack.enter_context(patch.object(Path, "lstat", lstat))

    def tearDown(self):
        self.stack.close()

    def run_command(self, text, timeout=2):
        return command.execute({"command": text, "timeout_seconds": timeout}, python_binary=sys.executable)

    def test_nonzero_and_timeout_are_results(self):
        result = self.run_command("printf 'failed'; exit 7")
        self.assertTrue(result["ok"])
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["stdout"], "failed")
        result = self.run_command("sleep 3", timeout=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["exit_code"], 124)
        self.assertTrue(result["timed_out"])

    def test_bounded_logs_keep_beginning_and_end(self):
        result = self.run_command("printf BEGIN; head -c 100000 /dev/zero | tr '\\0' x; printf END")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len((result["stdout"] + result["stderr"]).encode()), command.MAX_LOG)
        self.assertTrue(result["stdout"].startswith("BEGIN"))
        self.assertTrue(result["stdout"].endswith("END"))
        log = command.BoundedLog(128)
        log.append(b"\xff" * 1000)
        self.assertLessEqual(len(log.text().encode()), 128)

    def test_persistent_workspace_and_changed_artifacts(self):
        first = self.run_command("echo saved > state; echo first > outputs/result.txt")
        self.assertEqual(len(first["artifacts"]), 1)
        self.assertEqual(Path(first["artifacts"][0]["path"]).read_text(), "first\n")
        second = self.run_command("cat state")
        self.assertEqual(second["stdout"], "saved\n")
        self.assertEqual(second["artifacts"], [])
        third = self.run_command("echo changed > outputs/result.txt; ln -s /etc/passwd outputs/link; ln outputs/result.txt outputs/hardlink")
        self.assertEqual(third["artifacts"], [])

    def test_export_limits_and_input_validation(self):
        result = self.run_command("for n in {1..10}; do echo file > outputs/$n.txt; done")
        self.assertEqual(len(result["artifacts"]), 8)
        self.assertEqual(len(result["warnings"]), 2)
        for payload in ({"command": ""}, {"command": "true", "timeout_seconds": True}, {"command": "true", "timeout_seconds": 301}):
            with self.assertRaises(ValueError):
                command.execute(payload, python_binary=sys.executable)
