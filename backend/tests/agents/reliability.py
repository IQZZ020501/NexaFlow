"""Recovery contracts that do not require a live worker or model provider."""

import json
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401
from langchain_core.messages import HumanMessage
from tests.support import settings

from app.application.agents.access.service import external_progress_events
from app.application.agents.runs import history, service
from app.application.agents.runs.executor import _upsert_process_event
from app.domain.agents.runtime.capabilities import CapabilityRegistry
from app.domain.agents.runtime.extensions import ExtensionRuntime
from app.domain.agents.runtime.references import (
    PROJECTION_LIMIT,
    REFERENCE_MARKER,
    collect_references,
    reference_message,
)
from app.domain.agents.runtime.session import AgentSession
from app.domain.agents.runtime.usage import empty_usage
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.agents import live_stream
from app.schemas.agents.contracts import AgentRunEventResponse


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_live_cursor_keeps_durable_execution_available(self):
        redis = SimpleNamespace(
            xrevrange=AsyncMock(side_effect=TimeoutError),
            pipeline=AsyncMock(),
            aclose=AsyncMock(),
        )
        with patch.object(live_stream, "_redis_client", return_value=redis):
            publisher = live_stream.AgentLiveStreamPublisher(settings(), "run-1")
            await publisher.start()
            await publisher.publish({"type": "reasoning_delta", "delta": "AB"})
            self.assertEqual(publisher.cursor, "0-0")
            redis.pipeline.assert_not_called()
            await publisher.close()

    async def test_process_versions_and_live_watermarks_survive_public_projection(self):
        process = {
            "type": "thought",
            "turn": 2,
            "tool_name": "",
            "status": "running",
            "summary": "agent.reviewing_tool_results",
            "reasoning": "AB",
            "stream_epoch": "worker-private-id",
            "live_sequence": "1000-2",
        }
        events = []
        _upsert_process_event(events, process, sequence=7)
        snapshot = AgentRunEventResponse(**events[0]).model_dump(mode="json")
        self.assertEqual(snapshot["sequence"], 7)
        self.assertEqual(snapshot["live_sequence"], "1000-2")
        public = external_progress_events([snapshot], "running")[0].model_dump(
            mode="json"
        )
        self.assertEqual(public["sequence"], 7)
        self.assertEqual(public["live_sequence"], "1000-2")
        self.assertNotEqual(public["stream_epoch"], "worker-private-id")
        self.assertEqual(len(public["stream_epoch"]), 32)

        run = AgentRun(status="running")

        @asynccontextmanager
        async def session():
            yield object()

        reader = SimpleNamespace(
            read=AsyncMock(return_value=[]), close=AsyncMock(), available=False
        )
        with (
            patch.object(service, "get_session_factory", return_value=session),
            patch.object(service, "AgentLiveStreamReader", return_value=reader),
            patch.object(
                service,
                "run_to_response",
                return_value=SimpleNamespace(model_dump=lambda **_: {}),
            ),
            patch.object(
                service.agent_repository,
                "get_agent_run_poll_state",
                AsyncMock(side_effect=lambda *_, **__: (run.status, run.lease_expires_at)),
            ),
            patch.object(
                service.agent_repository,
                "get_agent_run_by_id",
                AsyncMock(return_value=run),
            ),
            patch.object(
                service.agent_repository,
                "list_agent_run_events",
                AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id=7, event={"type": "process", "event": process}
                        ),
                    ]
                ),
            ),
        ):
            stream = service.stream_agent_run(None, run, None, None, None, settings())
            await anext(stream)
            streamed = await anext(stream)
            self.assertEqual(streamed["event"]["sequence"], 7)
            self.assertEqual(streamed["event"]["live_sequence"], "1000-2")
            await stream.aclose()

    async def test_expired_lease_is_recovering_until_database_terminal(self):
        run = AgentRun(
            status="running", lease_expires_at=utc_now() - timedelta(seconds=1)
        )

        @asynccontextmanager
        async def session():
            yield object()

        reader = SimpleNamespace(
            read=AsyncMock(return_value=[]), close=AsyncMock(), available=False
        )
        response = SimpleNamespace(
            model_dump=lambda **_: {"id": run.id, "status": run.status}
        )
        with (
            patch.object(service, "get_session_factory", return_value=session),
            patch.object(service, "AgentLiveStreamReader", return_value=reader),
            patch.object(service, "run_to_response", return_value=response),
            patch.object(
                service.agent_repository,
                "get_agent_run_poll_state",
                AsyncMock(side_effect=lambda *_, **__: (run.status, run.lease_expires_at)),
            ),
            patch.object(
                service.agent_repository,
                "get_agent_run_by_id",
                AsyncMock(return_value=run),
            ),
            patch.object(
                service.agent_repository,
                "list_agent_run_events",
                AsyncMock(return_value=[]),
            ),
        ):
            stream = service.stream_agent_run(None, run, None, None, None, settings())
            self.assertEqual((await anext(stream))["run"]["status"], "running")
            recovering = await anext(stream)
            self.assertEqual(recovering["type"], "recovering")
            self.assertEqual(recovering["run"]["status"], "running")
            run.status = "succeeded"
            complete = await anext(stream)
            self.assertEqual(complete["type"], "complete")
            await stream.aclose()

    async def test_exact_references_survive_repeated_compaction_and_checkpoint(self):
        registry = CapabilityRegistry(ExtensionRuntime([]), [])
        # Simulate a summarizer that drops every ID and path.
        compactor = SimpleNamespace(
            restore=lambda _: None,
            prepare=AsyncMock(
                return_value=([HumanMessage(content="Prose only")], empty_usage())
            ),
            memory=None,
        )
        session = AgentSession(registry, compactor)
        state = {
            "messages": [HumanMessage(content="A, then B, then A")],
            "events": [],
            "harness": {"input_ids": [5, 8]},
            "model_usage": empty_usage(),
        }
        for index in range(3):
            state["events"].append(
                {
                    "status": "succeeded",
                    "call_id": f"call-{index}",
                    "output": {
                        "artifact_id": f"artifact-{index}",
                        "relative_path": "A/report.xlsx"
                        if index != 1
                        else "B/report.xlsx",
                        "content_hash": str(index) * 64,
                        "previous_artifact_id": f"artifact-{index - 1}"
                        if index
                        else None,
                        "result_id": f"result-{index}",
                        "total_characters": 80000,
                    },
                }
            )
            state = await session.prepare_turn(state)
            # Checkpoint JSON round trip must not depend on summary prose.
            state["harness"] = json.loads(json.dumps(state["harness"]))
        exact = state["harness"]["exact_references"]
        self.assertEqual(len(exact["artifacts"]), 3)
        self.assertEqual(
            exact["artifacts"]["artifact-2"]["previous_artifact_id"], "artifact-1"
        )
        self.assertEqual(
            exact["artifacts"]["artifact-2"]["relative_path"], "A/report.xlsx"
        )
        self.assertEqual(exact["results"]["result-0"]["call_id"], "call-0")
        self.assertEqual(exact["input_ids"], [5, 8])
        projections = [
            m for m in state["messages"] if m.additional_kwargs.get(REFERENCE_MARKER)
        ]
        self.assertEqual(len(projections), 1)
        self.assertIn("artifact-0", projections[0].content)

    async def test_history_range_reads_tail_and_rejects_every_other_scope(self):
        run = AgentRun(
            workspace_id="w",
            agent_id="a",
            consumer_id="u",
            execution_user_id="x",
            access_source="public",
            conversation_id="c",
        )
        source = replace(
            run, id="source", status="succeeded", result="x" * 15000 + "EXACT_TAIL"
        )

        @asynccontextmanager
        async def session():
            yield object()

        with (
            patch.object(history, "get_session_factory", return_value=session),
            patch.object(
                history.runs, "get_agent_run_by_id", AsyncMock(return_value=source)
            ) as get,
        ):
            result = await history.read_conversation_history(
                run, source.id, "result", 15000, 20
            )
            self.assertEqual(result.output["content"], "EXACT_TAIL")
            with patch(
                "app.application.agents.tools.results.read_run_tool_result",
                AsyncMock(return_value=result),
            ) as read_result:
                self.assertIs(
                    await history.read_conversation_history(
                        run, source.id, "tool_result", 100, 20, "saved-result"
                    ),
                    result,
                )
                read_result.assert_awaited_once_with(source, "saved-result", 100, 20)
            for field in (
                "workspace_id",
                "agent_id",
                "consumer_id",
                "execution_user_id",
                "access_source",
                "conversation_id",
            ):
                get.return_value = replace(source, **{field: "other"})
                self.assertTrue(
                    (
                        await history.read_conversation_history(
                            run, source.id, "result", 0, 20
                        )
                    ).is_error,
                    field,
                )
            with self.assertRaises(ValueError):
                await history.read_conversation_history(
                    run, source.id, "result", -1, 20
                )

    async def test_reference_projection_is_bounded_without_truncating_identities(self):
        events = [
            {
                "status": "succeeded",
                "call_id": str(index),
                "output": {
                    "artifact_id": f"artifact-{index}",
                    "relative_path": "long/" * 100 + f"report-{index}.html",
                    "result_id": "result-" + str(index) * 100,
                },
            }
            for index in range(40)
        ]
        exact = collect_references(
            {"exact_references": {"schema_version": 1, "source_run_id": "source"}},
            events,
        )
        message = reference_message(exact)
        projection = json.loads(message.content.rsplit("\n", 1)[-1])
        self.assertLessEqual(
            len(json.dumps(projection, ensure_ascii=False)), PROJECTION_LIMIT
        )
        self.assertEqual(len(exact["artifacts"]), 40)
        self.assertEqual(len(exact["results"]), 40)
        self.assertEqual(projection["totals"]["artifacts"], 40)
        for artifact in projection["artifacts"]:
            self.assertEqual(artifact, exact["artifacts"][artifact["artifact_id"]])
            self.assertEqual(artifact["run_id"], "source")


class RequestTests(unittest.TestCase):
    def test_create_replay_conflict_sources_and_regeneration(self):
        from tests.agents.agents import agent_model_server, agents_url, model_payload
        from tests.support import activate_admin, auth_headers, test_client

        from app.application.agents.access import service as access
        from app.application.artifacts import service as artifact_service
        from app.infra.db.session import get_session_factory

        async def finish(run_id):
            async with get_session_factory()() as db:
                await service.agent_repository.claim_agent_run(
                    db,
                    run_id,
                    "test-worker",
                    utc_now(),
                    utc_now() + timedelta(seconds=60),
                    generation="unified",
                )
                assert await service.agent_repository.finalize_agent_run(
                    db,
                    run_id,
                    "test-worker",
                    status="succeeded",
                    result="done",
                    events=[],
                    last_error=None,
                    finished_at=utc_now(),
                )
                await db.commit()

        async def expired_file(run_id):
            async with get_session_factory()() as db:
                with patch.object(
                    artifact_service,
                    "utc_now",
                    return_value=utc_now() - timedelta(days=2),
                ):
                    artifact = await artifact_service.create_generated_artifact(
                        db,
                        settings(),
                        workspace_id=workspace_id,
                        run_id=run_id,
                        idempotency_key="file-" + run_id,
                        artifact_format="html",
                        filename="report.html",
                        content=b"<h1>Retained</h1>",
                    )
                await db.commit()
                return artifact

        import asyncio

        with (
            test_client() as client,
            agent_model_server() as model_url,
            patch.object(service, "enqueue_prepared_agent_run", AsyncMock()) as enqueue,
            patch.object(
                access, "enqueue_prepared_agent_run", AsyncMock()
            ) as external_enqueue,
            patch(
                "app.application.uploads.service.resolve_workspace_agent_files",
                AsyncMock(return_value=("Original attachment text", [], [])),
            ) as resolve_upload,
        ):
            token, workspace_id = activate_admin(client)
            headers = auth_headers(token)
            model = client.post(
                f"/api/v1/workspaces/{workspace_id}/models",
                headers=headers,
                json=model_payload(model_url, "Reliability model"),
            )
            self.assertEqual(model.status_code, 201, model.text)
            agent = client.post(
                agents_url(workspace_id),
                headers=headers,
                json={
                    "name": "Reliable Agent",
                    "instructions": "Answer",
                    "model_id": model.json()["id"],
                },
            )
            self.assertEqual(agent.status_code, 201, agent.text)
            agent_id = agent.json()["id"]
            url = agents_url(workspace_id, f"/{agent_id}/runs")
            payload = {
                "goal": "Prepare the report",
                "request_id": "retry-1",
                "file_ids": ["one-time-upload"],
            }
            first = client.post(url, headers=headers, json=payload)
            self.assertEqual(first.status_code, 201, first.text)
            replay = client.post(url, headers=headers, json=payload)
            self.assertEqual(replay.status_code, 201, replay.text)
            self.assertEqual(replay.json()["id"], first.json()["id"])
            self.assertEqual(enqueue.await_count, 1)
            self.assertEqual(resolve_upload.await_count, 1)
            self.assertEqual(
                client.post(
                    url, headers=headers, json={**payload, "goal": "Different"}
                ).status_code,
                409,
            )
            self.assertEqual(
                client.post(
                    url, headers=headers, json={**payload, "request_id": "bad key"}
                ).status_code,
                422,
            )
            asyncio.run(finish(first.json()["id"]))
            replay = client.post(url, headers=headers, json=payload)
            self.assertEqual(replay.json()["status"], "succeeded")
            regenerate_url = f"{url}/{first.json()['id']}/regenerate"
            regenerate_payload = {
                "goal": "Revised report",
                "request_id": "regenerate-1",
            }
            regenerated = client.post(
                regenerate_url, headers=headers, json=regenerate_payload
            )
            self.assertEqual(regenerated.status_code, 200, regenerated.text)
            replay = client.post(
                regenerate_url, headers=headers, json=regenerate_payload
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json()["id"], regenerated.json()["id"])
            self.assertEqual(enqueue.await_count, 2)
            # Identical keys from different access sources are independent.
            published = client.patch(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=headers,
                json={"published": True},
            )
            self.assertEqual(published.status_code, 200, published.text)
            public_url = f"/api/v1/public/agents/{agent_id}/runs"
            public_payload = {
                key: value for key, value in payload.items() if key != "file_ids"
            }
            public = client.post(public_url, headers=headers, json=public_payload)
            self.assertEqual(public.status_code, 201, public.text)
            self.assertNotEqual(public.json()["id"], first.json()["id"])
            public_replay = client.post(
                public_url, headers=headers, json=public_payload
            )
            self.assertEqual(public_replay.json()["id"], public.json()["id"])
            self.assertEqual(external_enqueue.await_count, 1)
            self.assertEqual(
                client.post(
                    public_url,
                    headers=headers,
                    json={**public_payload, "conversation_id": "other"},
                ).status_code,
                409,
            )
            console_file = asyncio.run(expired_file(first.json()["id"]))
            stable_url = f"/api/v1/artifacts/{console_file.artifact_id}/content"
            self.assertEqual(client.get(stable_url).status_code, 401)
            download = client.get(stable_url, headers=headers)
            self.assertEqual(download.status_code, 200, download.text)
            self.assertEqual(download.content, b"<h1>Retained</h1>")
            self.assertEqual(download.headers["x-content-type-options"], "nosniff")
            self.assertIn("sandbox", download.headers["content-security-policy"])
            self.assertEqual(client.get(console_file.download_url).status_code, 404)
            public_file = asyncio.run(expired_file(public.json()["id"]))
            public_file_url = f"/api/v1/artifacts/{public_file.artifact_id}/content"
            self.assertEqual(
                client.get(public_file_url, headers=headers).status_code, 200
            )
            key_url = agents_url(workspace_id, f"/{agent_id}/api-credentials")
            key = client.post(key_url, headers=headers, json={"name": "Reliable API"})
            self.assertEqual(key.status_code, 201, key.text)
            api_headers = auth_headers(key.json()["token"])
            api_url = f"/api/v1/agent-api/{agent_id}/runs"
            api_run = client.post(api_url, headers=api_headers, json=public_payload)
            self.assertEqual(api_run.status_code, 201, api_run.text)
            self.assertEqual(
                client.post(api_url, headers=api_headers, json=public_payload).json()[
                    "id"
                ],
                api_run.json()["id"],
            )
            self.assertNotEqual(api_run.json()["id"], public.json()["id"])
            self.assertEqual(external_enqueue.await_count, 2)
            api_file = asyncio.run(expired_file(api_run.json()["id"]))
            api_file_url = f"{api_url}/{api_run.json()['id']}/artifacts/{api_file.artifact_id}/content"
            self.assertEqual(
                client.get(api_file_url, headers=api_headers).status_code, 200
            )
            self.assertEqual(
                client.get(
                    f"{api_url}/{public.json()['id']}/artifacts/{public_file.artifact_id}/content",
                    headers=api_headers,
                ).status_code,
                404,
            )
            revoked = client.delete(
                f"{key_url}/{key.json()['credential']['id']}", headers=headers
            )
            self.assertEqual(revoked.status_code, 204, revoked.text)
            self.assertEqual(
                client.get(api_file_url, headers=api_headers).status_code, 401
            )
            unpublished = client.patch(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=headers,
                json={"published": False},
            )
            self.assertEqual(unpublished.status_code, 200, unpublished.text)
            self.assertEqual(
                client.get(public_file_url, headers=headers).status_code, 404
            )
            self.assertEqual(client.get(stable_url, headers=headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
