from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.dev import (
    BUILD_INPUTS_LABEL,
    LocalImageBuild,
    build_inputs_fingerprint,
    development_port,
    ensure_local_image,
    is_managed_opensandbox_url,
    prepare,
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


class DevelopmentPreparationTests(unittest.TestCase):
    @patch("scripts.dev.ensure_local_image")
    @patch("scripts.dev.run")
    def test_infrastructure_start_does_not_force_image_build(
        self,
        run_mock,
        ensure_image_mock,
    ) -> None:
        prepare({}, local_opensandbox=False)

        ensure_image_mock.assert_called_once()
        compose_command = next(
            call.args[0]
            for call in run_mock.call_args_list
            if call.args[0][:2] == ["docker", "compose"]
        )
        self.assertNotIn("--build", compose_command)


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
