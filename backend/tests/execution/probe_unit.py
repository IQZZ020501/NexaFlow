"""Probe safety checks without Docker, Redis, database or HTTP connections."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.execution import opensandbox_probe as probe_module


def probe():
    arguments = SimpleNamespace(
        url="http://127.0.0.1:8088",
        image="test-image",
        allow_development=False,
        redis_url="redis://127.0.0.1:6379/0",
        samples=1,
        stream_seconds=70,
    )
    with patch.dict("os.environ", {"OPENSANDBOX_API_KEY": "probe-fixture-key"}):
        return probe_module.Probe(arguments)


class ProbeSafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_development_missing_checks_or_cleanup_failure_never_pass_prerequisite(
        self,
    ):
        report = {
            "mode": "kata",
            "sdk_version": "0.1.16",
            "runtime_verified": "kata-runtime",
            "checks": {
                name: {"status": "passed"} for name in probe_module.REQUIRED_CHECKS
            },
        }
        self.assertTrue(probe_module.prerequisite_complete(report))
        report["mode"] = "development"
        self.assertFalse(probe_module.prerequisite_complete(report))
        report["mode"] = "kata"
        report["runtime_verified"] = "runc"
        self.assertFalse(probe_module.prerequisite_complete(report))
        report["runtime_verified"] = "kata-runtime"
        report["checks"]["cleanup"] = {"status": "failed"}
        self.assertFalse(probe_module.prerequisite_complete(report))
        del report["checks"]["cleanup"]
        self.assertFalse(probe_module.prerequisite_complete(report))

    async def test_unverified_runtime_stops_before_staging_or_executing(self):
        instance = probe()
        instance.server_version = AsyncMock(return_value={"version": "0.2.3"})
        instance.create = AsyncMock(return_value=SimpleNamespace(id="ours"))
        instance.runtime_check = AsyncMock(side_effect=RuntimeError("not Kata"))
        instance.platform._require_enforcement = AsyncMock()
        instance.command = AsyncMock()
        instance.cleanup = AsyncMock(return_value={"tagged_sandboxes_remaining": 0})
        await instance.run()
        instance.command.assert_not_called()
        instance.platform._require_enforcement.assert_not_called()
        instance.cleanup.assert_awaited_once()
        self.assertFalse(instance.report["phase_zero_complete"])
        self.assertEqual(instance.report["checks"]["connect"]["status"], "skipped")

    async def test_metadata_filter_must_not_admit_unrelated_sandboxes(self):
        instance = probe()
        instance.manager = AsyncMock()
        instance.manager.list_sandbox_infos.return_value = SimpleNamespace(
            sandbox_infos=[
                SimpleNamespace(id="someone-else", metadata={"owner": "nexaflow"})
            ],
            pagination=SimpleNamespace(has_next_page=False),
        )
        with self.assertRaises(RuntimeError):
            await instance.filtered_infos(instance.metadata)
        instance.manager.kill_sandbox.assert_not_called()

    async def test_metadata_listing_follows_every_page(self):
        instance = probe()
        instance.manager = AsyncMock()
        instance.manager.list_sandbox_infos.side_effect = [
            SimpleNamespace(
                sandbox_infos=[SimpleNamespace(id="first", metadata=instance.metadata)],
                pagination=SimpleNamespace(has_next_page=True),
            ),
            SimpleNamespace(
                sandbox_infos=[
                    SimpleNamespace(id="second", metadata=instance.metadata)
                ],
                pagination=SimpleNamespace(has_next_page=False),
            ),
        ]
        result = await instance.filtered_infos(instance.metadata)
        self.assertEqual([info.id for info in result], ["first", "second"])
        filters = [
            call.args[0] for call in instance.manager.list_sandbox_infos.await_args_list
        ]
        self.assertEqual([item.page for item in filters], [1, 2])

    async def test_failed_listing_still_destroys_known_sandboxes_and_closes_handles(
        self,
    ):
        instance = probe()
        instance.creation_attempted = True
        instance.ids.add("ours")
        instance.manager = AsyncMock()
        handle = SimpleNamespace(close=AsyncMock())
        instance.handles.append(handle)
        instance.filtered_infos = AsyncMock(
            side_effect=[RuntimeError("secret fixture text"), []]
        )
        with self.assertRaises(RuntimeError):
            await instance.cleanup()
        instance.manager.kill_sandbox.assert_awaited_once_with("ours")
        handle.close.assert_awaited_once()
        instance.manager.close.assert_awaited_once()
        self.assertEqual(
            instance.report["cleanup_failures"], [{"error_type": "RuntimeError"}]
        )


if __name__ == "__main__":
    unittest.main()
