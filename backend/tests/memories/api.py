"""Ownership, project isolation, extraction recovery and deletion fences."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.agents.agents import (
    AgentModelHandler,
    agent_model_server,
    agents_url,
    model_payload,
)
from tests.projects.runtime import claim, finish
from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    settings,
    test_client,
)

from app.application.agents.access import service as access
from app.application.agents.runs import service as run_service
from app.application.agents.runs.executor import run_durable_agent_run
from app.application.memories import memory_context, queue_memory_job
from app.application.memories.extraction import extract_memories
from app.infra.db.repositories import memories as repository
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.session import get_session_factory
from app.tasks.maintenance.jobs import _recover_user_memories


async def context(run_id, query="Docker"):
    async with get_session_factory()() as db:
        run = await runs.get_agent_run_by_id(db, run_id)
        return await memory_context(db, run, query)


async def queue(run_id):
    async with get_session_factory()() as db:
        run = await runs.get_agent_run_by_id(db, run_id)
        await queue_memory_job(db, run)
        await db.commit()
        return await repository.due_jobs(db)


def main():
    with (
        test_client() as client,
        agent_model_server() as model_url,
        patch.object(access, "enqueue_prepared_agent_run", AsyncMock()),
        patch.object(run_service, "enqueue_prepared_agent_run", AsyncMock()),
    ):
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_url, "Memory model"),
        ).json()

        def agent(name):
            result = client.post(
                agents_url(workspace_id),
                headers=headers,
                json={"name": name, "model_id": model["id"]},
            )
            assert result.status_code == 201, result.text
            aid = result.json()["id"]
            assert (
                client.patch(
                    agents_url(workspace_id, f"/{aid}"),
                    headers=headers,
                    json={"published": True},
                ).status_code
                == 200
            )
            return aid

        agent_id, other_agent = agent("Memory Agent"), agent("Other Agent")
        agent_base = f"/api/v1/public/agents/{agent_id}"
        memory_base = f"/api/v1/workspaces/{workspace_id}/memories"
        other_id, other_token = create_active_user(client, token, "memory-reader")
        client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            headers=headers,
            json={"user_id": other_id, "role": "member"},
        )
        other_headers = auth_headers(other_token)

        def call(method, suffix, code=200, **kwargs):
            base = kwargs.pop("base", memory_base)
            response = getattr(client, method)(
                base + suffix,
                headers=kwargs.pop("headers", headers),
                **kwargs,
            )
            assert response.status_code == code, response.text
            return response.json() if response.content else None

        assert client.get(memory_base).status_code == 401
        assert call("get", "") == {
            "enabled": True,
            "automatic": False,
            "items": [],
        }
        payload = {
            "key": "language",
            "content": "Prefer concise Chinese",
            "category": "preference",
        }
        profile = call("post", "", 201, json=payload)
        memory_id = profile["items"][0]["id"]
        assert call("get", "", headers=other_headers)["items"] == []
        assert (
            client.get(
                memory_base, headers=headers
            ).json()["items"]
            == profile["items"]
        )
        admin_id = client.get("/api/v1/auth/me", headers=headers).json()["user"][
            "id"
        ]
        other_workspace_response = client.post(
            "/api/v1/workspaces",
            headers=headers,
            json={"name": "Other Memory Workspace", "admin_user_id": admin_id},
        )
        assert other_workspace_response.status_code == 201
        other_workspace = other_workspace_response.json()["workspace"]["id"]
        other_memory_base = f"/api/v1/workspaces/{other_workspace}/memories"
        assert client.get(other_memory_base, headers=headers).json()["items"] == []
        other_profile = client.post(
            other_memory_base, headers=headers, json=payload
        )
        assert other_profile.status_code == 201, other_profile.text
        assert client.get(memory_base, headers=headers).json()["items"] == profile[
            "items"
        ]
        call("put", f"/{memory_id}", 404, headers=other_headers, json=payload)
        call("delete", f"/{memory_id}", 404, headers=other_headers)
        call("put", "/missing", 404, json=payload)
        call("post", "", 409, json=payload)
        call(
            "post",
            "",
            422,
            json={**payload, "key": "password", "content": "secret"},
        )
        call("post", "", 422, json={**payload, "content": "  "})
        call(
            "put",
            f"/{memory_id}",
            json={**payload, "content": "Prefer concise English"},
        )

        def create_run(*, actor_headers=headers, for_agent=agent_id, **payload):
            return call(
                "post",
                "/runs",
                201,
                headers=actor_headers,
                json={"goal": "Explain Docker", **payload},
                base=f"/api/v1/public/agents/{for_agent}",
            )["id"]

        run_id = create_run()
        assert "concise English" in asyncio.run(context(run_id))
        shared_run = create_run(for_agent=other_agent)
        assert "concise English" in asyncio.run(context(shared_run))

        async def stored(run_id):
            async with get_session_factory()() as db:
                return await runs.get_agent_run_by_id(db, run_id)

        run = asyncio.run(stored(run_id))
        AgentModelHandler.calls = []
        assert (
            asyncio.run(run_durable_agent_run(run_id, settings(), "memory-worker"))
            == "finished"
        )
        assert "concise English" in str(AgentModelHandler.calls[0]["messages"])
        suggestion = json.loads(AgentModelHandler.calls[-1]["messages"][-1]["content"])
        assert "concise English" in suggestion["related_context"]
        assert asyncio.run(queue(run_id)) == []  # automatic is off

        other_run = create_run(actor_headers=other_headers)
        assert asyncio.run(context(other_run)) == ""
        public = asyncio.run(stored(other_run))
        assert public.execution_user_id != public.consumer_id
        asyncio.run(claim(other_run))
        asyncio.run(finish(other_run))
        temp = create_run(use_memory=False)
        assert asyncio.run(context(temp)) == ""
        assert "disabled or unavailable" in asyncio.run(
            context(temp, "请记住，回答简洁")
        )
        asyncio.run(claim(temp))
        asyncio.run(finish(temp))
        assert asyncio.run(queue(temp)) == []

        project = call(
            "post",
            "/projects",
            201,
            json={"name": "Docker project"},
            base=agent_base,
        )
        pid = project["id"]
        other_project = call(
            "post",
            "/projects",
            201,
            json={"name": "Other Agent project"},
            base=f"/api/v1/public/agents/{other_agent}",
        )
        listed_projects = call("get", "/projects")["items"]
        assert {pid, other_project["id"]}.issubset(
            {item["id"] for item in listed_projects}
        )
        call(
            "post",
            "",
            201,
            json={
                "key": "docker-decision",
                "content": "Docker uses private database",
                "category": "project",
                "project_id": pid,
            },
        )
        assert "private database" not in asyncio.run(context(run_id))
        conv = call(
            "post", f"/projects/{pid}/conversations", 201, base=agent_base
        )
        project_run = create_run(conversation_id=conv["conversation_id"])
        assert "private database" in asyncio.run(context(project_run))
        asyncio.run(claim(project_run))
        asyncio.run(finish(project_run))
        call(
            "put", "/preferences", json={"enabled": False, "automatic": False}
        )
        assert asyncio.run(context(project_run)) == ""
        call("put", "/preferences", json={"enabled": True, "automatic": False})

        # Explicit requests work while automatic extraction is off.
        explicit = create_run(goal="请记住，我偏好分点回答")
        assert (
            asyncio.run(run_durable_agent_run(explicit, settings(), "remember-worker"))
            == "finished"
        )
        job_id = asyncio.run(queue(explicit))[0]
        with patch(
            "app.tasks.maintenance.jobs.extract_user_memories_job.apply_async"
        ) as dispatch:
            _recover_user_memories(settings())
            dispatch.assert_called_once_with(args=(job_id,))
        candidate = [
            {
                "action": "upsert",
                "category": "preference",
                "scope": "user",
                "key": "answer-style",
                "content": "偏好分点回答",
                "quote": "我偏好分点回答",
                "source_index": 0,
            }
        ]
        fake = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=SimpleNamespace(
                    text=json.dumps(candidate), response_metadata={}
                )
            )
        )
        with patch(
            "app.application.memories.extraction.build_chat_model", return_value=fake
        ):
            asyncio.run(extract_memories(job_id, settings()))
            asyncio.run(extract_memories(job_id, settings()))
        assert fake.ainvoke.await_count == 1
        item = next(
            item
            for item in call("get", "")["items"]
            if item["key"] == "answer-style"
        )
        assert item["origin"] == "explicit" and item["source_run_id"] == explicit
        assert item["source_conversation_id"]
        assert item["source_agent_id"] == agent_id
        assert "分点回答" in asyncio.run(context(project_run))

        # Clear while a provider request is in flight: no stale resurrection.
        pending = create_run(goal="请记住，我偏好分点回答")
        asyncio.run(claim(pending))
        asyncio.run(finish(pending))
        job_id = asyncio.run(queue(pending))[0]

        async def delayed(*args, **kwargs):
            async with get_session_factory()() as db:
                profile = await repository.get_preferences(
                    db, run.workspace_id, run.consumer_id, lock=True
                )
                profile.epoch += 1
                await repository.delete_memory(db, profile.id)
                await repository.save_preferences(db, profile)
                await db.commit()
            return SimpleNamespace(text=json.dumps(candidate), response_metadata={})

        with patch(
            "app.application.memories.extraction.build_chat_model",
            return_value=SimpleNamespace(ainvoke=delayed),
        ):
            asyncio.run(extract_memories(job_id, settings()))
        assert call("get", "")["items"] == []
        assert asyncio.run(context(run_id)) == ""

        # Clicking a suggestion is never a new profile fact.
        call("put", "/preferences", json={"enabled": True, "automatic": True})
        clicked = create_run(from_suggestion=True)
        asyncio.run(claim(clicked))
        asyncio.run(finish(clicked))
        assert asyncio.run(queue(clicked)) == []
        call("delete", "", 204)
    print("Memory ownership, runtime scope, extraction and deletion checks passed.")


if __name__ == "__main__":
    main()
