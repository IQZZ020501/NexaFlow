"""Validate the single-file deployment and its real process lifecycle."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rendered = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.config = json.loads(rendered.stdout)
        cls.source = cls.config["configs"]["app-supervisor"]["content"]

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="nexaflow-compose-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        script = self.directory / "app.py"
        script.write_text(self.source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("app_supervisor", script)
        assert spec is not None and spec.loader is not None
        self.supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.supervisor)

    def test_five_resident_services_with_isolated_execution_and_migration(self) -> None:
        services = self.config["services"]
        self.assertEqual(
            {name for name, service in services.items() if service["restart"] != "no"},
            {"app", "db", "redis", "qdrant", "opensandbox"},
        )
        app = services["app"]
        self.assertEqual(
            app["depends_on"]["migrate"]["condition"], "service_completed_successfully"
        )
        self.assertEqual(app["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", app["security_opt"])
        self.assertFalse(
            any("docker.sock" in volume["target"] for volume in app["volumes"])
        )
        self.assertEqual(
            set(app["networks"]["default"]["aliases"]), {"api", "frontend"}
        )
        commands = {label: command for label, command, _ in self.supervisor.SERVICES}
        self.assertEqual(set(commands), {"api", "worker", "agent-worker", "frontend"})
        self.assertIn("--role=background", commands["worker"])
        self.assertIn("--role=agents", commands["agent-worker"])

    def test_workers_have_distinct_celery_node_names_on_the_shared_host(self) -> None:
        commands = {label: command for label, command, _ in self.supervisor.SERVICES}
        names = [
            next(
                (value for value in commands[label] if value.startswith("--hostname=")),
                None,
            )
            for label in ("worker", "agent-worker")
        ]
        self.assertNotIn(None, names)
        self.assertNotEqual(*names)

    def test_frontend_environment_does_not_receive_backend_credentials(self) -> None:
        with patch.dict(
            os.environ,
            {"POSTGRES_PASSWORD": "fixture", "OPENSANDBOX_API_KEY": "fixture"},
        ):
            self.assertNotIn(
                "POSTGRES_PASSWORD", self.supervisor.environment("frontend")
            )
            self.assertNotIn(
                "OPENSANDBOX_API_KEY", self.supervisor.environment("frontend")
            )
            self.assertEqual(
                self.supervisor.environment("api")["POSTGRES_PASSWORD"], "fixture"
            )

    def test_healthcheck_requires_both_api_and_frontend_proxy(self) -> None:
        with patch.object(self.supervisor.urllib.request, "urlopen") as request:
            self.supervisor.healthcheck()
            self.assertEqual(
                [call.args[0] for call in request.call_args_list],
                ["http://127.0.0.1:8000/health", "http://127.0.0.1:3000/health"],
            )
            request.side_effect = OSError("unavailable")
            with self.assertRaises(OSError):
                self.supervisor.healthcheck()

    def test_partial_startup_failure_stops_already_started_process(self) -> None:
        process = Mock(pid=12345, stdout=io.StringIO())
        with (
            patch.object(
                self.supervisor.subprocess,
                "Popen",
                side_effect=[process, OSError("missing executable")],
            ),
            patch.object(self.supervisor, "signal_group") as send_signal,
        ):
            result = self.supervisor.supervise(
                [("first", ["first"], "/"), ("missing", ["missing"], "/")]
            )
        self.assertEqual(result, 1)
        self.assertEqual(
            [call.args[1] for call in send_signal.call_args_list],
            [signal.SIGTERM, signal.SIGKILL],
        )
        process.wait.assert_called()

    def service(self, name: str, *, ignore_term: bool = False) -> tuple:
        marker = self.directory / name
        source = (
            "import os, signal, time\n"
            "from pathlib import Path\n"
            f"marker = Path({str(marker)!r})\n"
            "def stop(signum, frame):\n"
            " marker.with_suffix('.stopped').write_text('stopped')\n"
            " raise SystemExit(0)\n"
            f"signal.signal(signal.SIGTERM, {'signal.SIG_IGN' if ignore_term else 'stop'})\n"
            "marker.with_suffix('.pid').write_text(str(os.getpid()))\n"
            "print('ready', flush=True)\n"
            "while True: time.sleep(0.1)\n"
        )
        return name, [sys.executable, "-c", source], str(self.directory)

    def start(self, services: list[tuple]) -> subprocess.Popen:
        script = self.directory / "app.py"
        script.write_text(self.source, encoding="utf-8")
        runner = (
            "import runpy\n"
            f"module = runpy.run_path({str(script)!r})\n"
            "run = module['supervise']\n"
            "run.__globals__['SHUTDOWN_TIMEOUT'] = 0.5\n"
            f"raise SystemExit(run({services!r}))\n"
        )
        output = (self.directory / "output.log").open("w")
        self.addCleanup(output.close)
        process = subprocess.Popen(
            [sys.executable, "-c", runner], stdout=output, stderr=subprocess.STDOUT
        )

        def cleanup() -> None:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

        self.addCleanup(cleanup)
        return process

    def wait_ready(self, name: str) -> int:
        path = self.directory / f"{name}.pid"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.exists() and path.read_text():
                return int(path.read_text())
            time.sleep(0.02)
        self.fail(
            f"{name} did not start: {(self.directory / 'output.log').read_text()}"
        )

    def test_sigterm_stops_every_service_and_prefixes_logs(self) -> None:
        process = self.start([self.service("api"), self.service("worker")])
        self.wait_ready("api")
        self.wait_ready("worker")
        process.terminate()
        self.assertEqual(process.wait(timeout=5), 0)
        for name in ("api", "worker"):
            self.assertTrue((self.directory / f"{name}.stopped").exists())
            self.assertIn(
                f"[{name}] ready", (self.directory / "output.log").read_text()
            )

    def test_even_successful_child_exit_fails_app_and_stops_siblings(self) -> None:
        process = self.start([self.service("api"), self.service("worker")])
        api_pid = self.wait_ready("api")
        self.wait_ready("worker")
        os.kill(api_pid, signal.SIGTERM)
        self.assertEqual(process.wait(timeout=5), 1)
        self.assertTrue((self.directory / "worker.stopped").exists())

    def test_shutdown_kills_service_that_ignores_sigterm(self) -> None:
        process = self.start([self.service("stubborn", ignore_term=True)])
        pid = self.wait_ready("stubborn")
        process.terminate()
        self.assertEqual(process.wait(timeout=5), 0)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
