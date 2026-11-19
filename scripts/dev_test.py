from __future__ import annotations

import json
import logging
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.dev import (
    BUILD_INPUTS_LABEL,
    DevError,
    LocalImageBuild,
    ManagedProcess,
    build_inputs_fingerprint,
    development_log_level,
    development_port,
    ensure_local_image,
    ensure_local_opensandbox,
    infrastructure_configuration,
    is_managed_opensandbox_url,
    prepare,
    read_env,
    set_env_value,
    should_forward_log,
    start_stack,
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


class OpenSandboxConfigurationTests(unittest.TestCase):
    def test_upgrades_generated_legacy_timeout_without_changing_other_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.toml"
            original = (
                "# Generated for opensandbox-server==0.2.3; keep this file private.\n"
                '[server]\napi_key = "local-test-key"\n'
                "max_sandbox_timeout_seconds = 360\n"
                '[docker]\nnetwork_mode = "bridge"\n'
            )
            path.write_text(original, encoding="utf-8")
            values = {
                "OPENSANDBOX_URL": "http://127.0.0.1:8088",
                "OPENSANDBOX_API_KEY": "local-test-key",
                "OPENSANDBOX_IMAGE": "nexaflow/execution:local",
            }
            with (
                patch("scripts.dev.OPEN_SANDBOX_CONFIG", path),
                patch("scripts.dev.read_env", return_value=values),
                patch("scripts.dev.run") as run_mock,
                patch("scripts.dev.log"),
            ):
                self.assertEqual(ensure_local_opensandbox(values), (values, True))
                updated = path.read_text(encoding="utf-8")
                self.assertEqual(updated, original.replace("= 360\n", "= 1860\n"))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                ensure_local_opensandbox(values)
                self.assertEqual(path.read_text(encoding="utf-8"), updated)
                run_mock.assert_not_called()

    def test_preserves_custom_and_current_configuration(self) -> None:
        for header, timeout in (
            ("# Operator-managed configuration\n", 360),
            (
                "# Generated for opensandbox-server==0.2.3; keep this file private.\n",
                600,
            ),
            (
                "# Generated for opensandbox-server==0.2.3; keep this file private.\n",
                1860,
            ),
        ):
            with (
                self.subTest(header=header, timeout=timeout),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "server.toml"
                original = (
                    header + '[server]\napi_key = "local-test-key"\n'
                    f"max_sandbox_timeout_seconds = {timeout}\n"
                )
                path.write_text(original, encoding="utf-8")
                values = {
                    "OPENSANDBOX_URL": "http://localhost:8088",
                    "OPENSANDBOX_API_KEY": "local-test-key",
                    "OPENSANDBOX_IMAGE": "nexaflow/execution:local",
                }
                with (
                    patch("scripts.dev.OPEN_SANDBOX_CONFIG", path),
                    patch("scripts.dev.read_env", return_value=values),
                    patch("scripts.dev.run") as run_mock,
                ):
                    ensure_local_opensandbox(values)
                self.assertEqual(path.read_text(encoding="utf-8"), original)
                run_mock.assert_not_called()


class DevelopmentPortTests(unittest.TestCase):
    def test_uses_default_port(self) -> None:
        self.assertEqual(development_port("NEXAFLOW_TEST_UNUSED_PORT", 8000), 8000)


class DevelopmentLogTests(unittest.TestCase):
    def test_hides_low_level_process_logs_and_keeps_errors_with_tracebacks(self) -> None:
        lines = [
            "DEBUG: request headers",
            "INFO: 127.0.0.1 - GET /health 200",
            "[2026-11-19 11:51:04,722: INFO/MainProcess] Task cleanup received",
            "2026-11-19 11:51:30,869 | INFO | NexaFlow | httpx | HTTP Request: GET /v1/sandboxes",
            "\033[32mINFO\033[0m: opensandbox_server.api.lifecycle: listSandboxes",
            "WARNING: lease is expiring",
            "[2026-11-19 11:51:04,722: WARNING/MainProcess] Worker retry",
            "2026-11-19 11:51:30,869 | ERROR | NexaFlow | executor | Run failed",
            "Traceback (most recent call last):",
            '  File "job.py", line 1, in run',
            "ValueError: invalid input",
            "CRITICAL: worker stopped",
            "Frontend ready; text mentions INFO without a log prefix",
        ]
        with patch("scripts.dev.log") as log_mock:
            process = ManagedProcess.start(
                "test",
                [sys.executable, "-c", f"import json; [print(line) for line in json.loads({json.dumps(json.dumps(lines))})]"],
                cwd=Path(__file__).parents[1],
                env={"PYTHONUNBUFFERED": "1"},
            )
            try:
                self.assertEqual(process.process.wait(timeout=5), 0)
                process.output_thread.join(timeout=5)
                self.assertFalse(process.output_thread.is_alive())
            finally:
                process.stop()
                process.process.stdout.close()
        self.assertEqual(
            [call.args[0] for call in log_mock.call_args_list],
            [f"[test] {line}" for line in lines[5:]],
        )

    def test_process_can_show_info_when_requested(self) -> None:
        with patch("scripts.dev.log") as log_mock:
            process = ManagedProcess.start(
                "test",
                [sys.executable, "-c", "print('DEBUG: hidden'); print('INFO: visible')"],
                cwd=Path(__file__).parents[1],
                env={"PYTHONUNBUFFERED": "1"},
                log_level=logging.INFO,
            )
            try:
                self.assertEqual(process.process.wait(timeout=5), 0)
                process.output_thread.join(timeout=5)
                self.assertFalse(process.output_thread.is_alive())
            finally:
                process.stop()
                process.process.stdout.close()
        self.assertEqual([call.args[0] for call in log_mock.call_args_list], ["[test] INFO: visible"])

    def test_configured_threshold_and_environment_precedence(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(development_log_level({}), logging.WARNING)
            self.assertEqual(development_log_level({"LOG_LEVEL": "info"}), logging.INFO)
            self.assertEqual(development_log_level({"LOG_LEVEL": "ERROR"}), logging.ERROR)
        with patch.dict(os.environ, {"LOG_LEVEL": "critical"}):
            self.assertEqual(development_log_level({"LOG_LEVEL": "INFO"}), logging.CRITICAL)
        with (
            patch.dict(os.environ, {"LOG_LEVEL": "TRACE"}),
            self.assertRaisesRegex(DevError, "Invalid LOG_LEVEL"),
        ):
            development_log_level({})

    def test_plain_diagnostics_and_level_words_inside_messages_are_not_hidden(self) -> None:
        self.assertTrue(should_forward_log("Request failed: INFO from upstream", logging.WARNING))
        self.assertTrue(should_forward_log("WARN: server retry", logging.WARNING))
        self.assertTrue(should_forward_log("FATAL: server stopped", logging.CRITICAL))
        self.assertFalse(should_forward_log("WARNING: retry", logging.ERROR))
        self.assertTrue(should_forward_log("DEBUG: diagnostic", logging.DEBUG))

    def test_stack_applies_the_same_display_threshold_to_all_processes(self) -> None:
        for configured, expected in (({}, logging.WARNING), ({"LOG_LEVEL": "INFO"}, logging.INFO)):
            with (
                self.subTest(configured=configured),
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.dev._request_status", return_value=None),
                patch("scripts.dev._port_available", return_value=True),
                patch("scripts.dev.wait_for_http"),
                patch("scripts.dev.time.sleep", side_effect=KeyboardInterrupt),
                patch("scripts.dev.log"),
                patch("scripts.dev.ManagedProcess.start") as start_mock,
            ):
                start_mock.return_value = SimpleNamespace(
                    process=SimpleNamespace(poll=lambda: None), stop=Mock(),
                )
                self.assertEqual(start_stack(
                    configured, local_opensandbox=True, api_port=8000, frontend_port=3000,
                ), 0)
                self.assertEqual([call.args[0] for call in start_mock.call_args_list], ["sandbox", "api", "worker", "web"])
                self.assertTrue(all(call.kwargs["log_level"] == expected for call in start_mock.call_args_list))


class DevelopmentPreparationTests(unittest.TestCase):
    @patch("scripts.dev.infrastructure_configuration", return_value={})
    @patch("scripts.dev.ensure_local_image")
    @patch("scripts.dev.run")
    def test_infrastructure_start_does_not_force_image_build(
        self,
        run_mock,
        ensure_image_mock,
        _configuration_mock,
    ) -> None:
        prepare({}, local_opensandbox=False)

        ensure_image_mock.assert_called_once()
        compose_command = next(
            call.args[0]
            for call in run_mock.call_args_list
            if call.args[0][:2] == ["docker", "compose"]
        )
        self.assertNotIn("--build", compose_command)

    @patch("scripts.dev.infrastructure_configuration", return_value={})
    @patch("scripts.dev.ensure_local_image")
    @patch("scripts.dev.run")
    def test_open_sandbox_uses_standalone_dockerfile(
        self,
        run_mock,
        ensure_image_mock,
        _configuration_mock,
    ) -> None:
        prepare(
            {"OPENSANDBOX_IMAGE": "nexaflow/execution:test"}, local_opensandbox=True
        )

        builds = [call.args[0] for call in ensure_image_mock.call_args_list]
        self.assertEqual(len(builds), 2)
        sandbox_build = ensure_image_mock.call_args_list[1].args[0]
        self.assertEqual(
            sandbox_build.dockerfile.name,
            "sandbox.Dockerfile",
        )
        self.assertIsNone(sandbox_build.target)
        self.assertEqual(sandbox_build.image, "nexaflow/execution:test")


class InfrastructureConfigurationTests(unittest.TestCase):
    @patch("scripts.dev.subprocess.run")
    def test_reuses_one_topology_without_deployment_secrets_or_services(
        self, run_mock
    ) -> None:
        run_mock.return_value = SimpleNamespace(
            stdout=json.dumps(
                {
                    "services": {
                        "db": {
                            "image": "published/postgres",
                            "environment": {"POSTGRES_PASSWORD": "deployment-only"},
                            "healthcheck": {},
                            "networks": {"default": None},
                        },
                        "redis": {"image": "redis:7-alpine"},
                        "qdrant": {"image": "qdrant/qdrant:v1.19.0"},
                        "api": {"image": "published/app"},
                    }
                }
            )
        )
        config = infrastructure_configuration(
            {"POSTGRES_PASSWORD": "local$credential", "POSTGRES_PORT": "15432"}
        )
        self.assertEqual(set(config["services"]), {"db", "redis", "qdrant"})
        database = config["services"]["db"]
        self.assertEqual(
            database["environment"]["POSTGRES_PASSWORD"], "local$$credential"
        )
        self.assertEqual(database["ports"], ["127.0.0.1:15432:5432"])
        self.assertEqual(database["container_name"], "nexaflow-db")
        self.assertNotIn("networks", database)
        self.assertNotIn("deployment-only", json.dumps(config))
        self.assertEqual(run_mock.call_args.args[0].count("-f"), 1)


class LocalImageBuildTests(unittest.TestCase):
    def build(self) -> LocalImageBuild:
        dockerfile = Path(__file__).parents[1] / "deploy" / "dockerfiles" / "postgres.Dockerfile"
        return LocalImageBuild(
            name="PostgreSQL",
            image="nexaflow/postgres:test",
            dockerfile=dockerfile,
            inputs=(dockerfile,),
        )

    @patch("scripts.dev.run")
    @patch("scripts.dev.docker_image_label")
    def test_reuses_image_when_inputs_match(self, image_label_mock, run_mock) -> None:
        build = self.build()
        image_label_mock.return_value = build_inputs_fingerprint(build.inputs)

        self.assertFalse(ensure_local_image(build))

        run_mock.assert_not_called()

    @patch("scripts.dev.run")
    @patch("scripts.dev.docker_image_label", return_value="stale")
    def test_rebuilds_image_when_inputs_change(self, _image_label_mock, run_mock) -> None:
        build = self.build()

        self.assertTrue(ensure_local_image(build))

        command = run_mock.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "build", "-f"])
        self.assertIn(
            f"{BUILD_INPUTS_LABEL}={build_inputs_fingerprint(build.inputs)}",
            command,
        )

    @patch("scripts.dev.run")
    @patch("scripts.dev.docker_image_label")
    def test_force_rebuild_ignores_matching_fingerprint(
        self,
        image_label_mock,
        run_mock,
    ) -> None:
        build = self.build()
        image_label_mock.return_value = build_inputs_fingerprint(build.inputs)

        self.assertTrue(ensure_local_image(build, force=True))

        run_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
