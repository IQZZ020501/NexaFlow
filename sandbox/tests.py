"""Job protocol regression tests. VM, cgroup and egress checks run separately."""

import asyncio
import base64
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from . import job
from .self_check import check_execution


class JobTests(unittest.TestCase):
    def setUp(self):
        self.real_limits = job.limits
        # The deployed runner is Linux-only. macOS does not implement its AS
        # limit consistently; actual limits are checked in the execution image.
        self.limit_patch = (
            patch.object(job, "limits") if sys.platform == "darwin" else nullcontext()
        )
        self.limit_patch.__enter__()

    def tearDown(self):
        self.limit_patch.__exit__(None, None, None)

    def test_runtime_behaviors_and_fixed_renderers(self):
        check_execution()

    def test_nonzero_exit_and_large_stdin(self):
        failed = job.execute({"code": "raise ValueError('program failed')"})
        self.assertFalse(failed["ok"])
        self.assertIn("program failed", failed["stderr"])
        response = job.execute(
            {"code": "import sys; print(len(sys.stdin.read()))", "stdin": "x" * 200000}
        )
        self.assertEqual(response["stdout"].strip(), "200000")

    def test_package_script_and_binary_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "main.py").write_text(
                "import os, sys, json\nfrom pathlib import Path\n"
                "from helper import VALUE\nassert VALUE == 3\n"
                "p = Path(os.environ['NEXAFLOW_SKILL_DIR'])\n"
                "assert (p / 'asset.bin').read_bytes() == bytes([0, 255])\n"
                "data = json.load(sys.stdin)\n"
                "Path(os.environ['NEXAFLOW_OUTPUT_PATH']).write_text(data['text'])\n"
                "print('completed')\n"
            )
            (package / "asset.bin").write_bytes(bytes([0, 255]))
            (package / "helper.py").write_text("VALUE = 3\n")
            with patch.object(job, "PACKAGE_DIR", package):
                result = job.execute(
                    {
                        "script": "main.py",
                        "files": {"main.py": "", "helper.py": "", "asset.bin": ""},
                        "stdin": '{"text":"version-pinned"}',
                        "artifact": {"filename": "result.txt", "format": "txt"},
                    }
                )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["stdout"].strip(), "completed")
            self.assertEqual(
                base64.b64decode(result["artifact"]["content_base64"]),
                b"version-pinned",
            )

    def test_protocol_rejections(self):
        for request in (
            {"limits": {"timeout_ms": 0}},
            {"limits": {"timeout_ms": 120001}},
            {"mcp": {}, "limits": {"timeout_ms": 300001}},
            {"skill": "untrusted", "artifact": {"filename": "x", "format": "txt"}},
            {"skill": "documents", "artifact": {"filename": "x", "format": "pdf"}},
            {"skills": ["unknown"]},
            {"skills": "documents"},
            {"files": []},
            {"files": {str(n): "" for n in range(65)}},
            {"files": {"../escape.py": ""}},
            {"files": {"/absolute.py": ""}},
            {"files": {"a\\b.py": ""}},
            {"script": "other.py", "files": {"main.py": ""}},
            {"script": "shell.sh", "files": {"shell.sh": ""}},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                job.execute(request)
        for name in ("..", ".", "../unsafe.txt", "/unsafe.txt", "a\\b", "a\0b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                job.execute({"artifact": {"filename": name, "format": "txt"}})

    def test_limits_configuration(self):
        with patch.object(job.resource, "setrlimit") as apply_limit:
            self.real_limits(0.2)
            calls = {call.args[0]: call.args[1] for call in apply_limit.call_args_list}
            self.assertEqual(calls[job.resource.RLIMIT_CPU], (1, 2))
            self.assertEqual(calls[job.resource.RLIMIT_FSIZE], (job.MAX_FILE + 1,) * 2)
            self.assertEqual(calls[job.resource.RLIMIT_NPROC], (32, 32))
            self.assertEqual(calls[job.resource.RLIMIT_NOFILE], (64, 64))
            self.assertEqual(calls[job.resource.RLIMIT_CORE], (0, 0))
            apply_limit.reset_mock()
            self.real_limits(300, address_space=False)
            self.assertNotIn(
                job.resource.RLIMIT_AS,
                {call.args[0] for call in apply_limit.call_args_list},
            )

    def test_result_protocol_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = Path(temporary) / "request.json"
            response = Path("/tmp/nexaflow-response.json")
            # Never write the production response location from host tests.
            original_path = job.Path

            def path(value):
                return (
                    Path(temporary) / "response.json"
                    if str(value) == str(response)
                    else original_path(value)
                )

            with (
                patch.object(job, "Path", side_effect=path),
                patch.object(sys, "argv", ["job", str(request)]),
            ):
                for payload in (b"bad json", b"x" * (job.MAX_INPUT + 1)):
                    request.write_bytes(payload)
                    job.main()
                    result = json.loads((Path(temporary) / "response.json").read_text())
                    self.assertFalse(result["ok"])
                    self.assertLessEqual(len(result["error"]), 1000)

    def test_mcp_pagination_and_typed_call(self):
        async def cases():
            tool = SimpleNamespace(model_dump=lambda **kwargs: {"name": "echo"})
            fake = AsyncMock()
            fake.__aenter__.return_value = fake
            fake.list_tools.side_effect = [
                SimpleNamespace(tools=[tool], next_cursor="page-2"),
                SimpleNamespace(tools=[tool], next_cursor=None),
            ]
            request = {
                "operation": "discover",
                "config": {"command": "server"},
                "timeout": 300,
            }
            with (
                patch("mcp.Client", return_value=fake),
                patch("mcp.client.stdio.stdio_client"),
            ):
                result = await job.mcp_request(request)
                self.assertEqual(len(result["tools"]), 2)
                fake.list_tools.assert_any_await(cursor="page-2", cache_mode="reload")
                fake.list_tools.side_effect = None
                fake.list_tools.return_value = SimpleNamespace(
                    tools=[tool], next_cursor="repeat"
                )
                with self.assertRaisesRegex(ValueError, "pages"):
                    await job.mcp_request(request)
                fake.list_tools.return_value = SimpleNamespace(
                    tools=[tool] * 65, next_cursor=None
                )
                with self.assertRaisesRegex(ValueError, "too many tools"):
                    await job.mcp_request(request)
                payload = {
                    "content": [{"type": "text", "text": "ok"}],
                    "structuredContent": {"x": 1},
                    "_meta": {"trace": "t"},
                }
                fake.call_tool.return_value = SimpleNamespace(
                    model_dump=lambda **kwargs: payload
                )
                result = await job.mcp_request(
                    {
                        **request,
                        "operation": "call",
                        "name": "echo",
                        "arguments": {},
                        "meta": {"key": "k"},
                    }
                )
                self.assertEqual(result, payload)
                fake.call_tool.assert_awaited_once_with("echo", {}, meta={"key": "k"})

        asyncio.run(cases())


if __name__ == "__main__":
    unittest.main()
