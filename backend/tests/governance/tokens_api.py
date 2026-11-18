"""A configured monthly quota blocks an Agent before provider dispatch."""

import asyncio
from unittest.mock import AsyncMock, patch

from tests.models.llm import (
    ModelTestHandler,
    model_payload,
    model_test_server,
    models_url,
)
from tests.support import activate_admin, auth_headers, settings, test_client

from app.application.agents.runs.executor import run_durable_agent_run


def check():
    with (
        test_client() as client,
        model_test_server() as provider,
        patch(
            "app.application.agents.runs.service.enqueue_prepared_agent_run",
            new=AsyncMock(),
        ),
    ):
        token, workspace = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            models_url(workspace), headers=headers, json=model_payload(provider)
        )
        assert model.status_code == 201, model.text
        agent = client.post(
            f"/api/v1/workspaces/{workspace}/agents",
            headers=headers,
            json={
                "name": "Quota acceptance",
                "instructions": "Answer directly.",
                "model_id": model.json()["id"],
            },
        )
        assert agent.status_code == 201, agent.text
        quota = client.patch(
            f"/api/v1/workspaces/{workspace}/governance",
            headers=headers,
            json={"monthly_token_limit": 1},
        )
        assert quota.status_code == 200, quota.text
        ModelTestHandler.calls = []
        base = f"/api/v1/workspaces/{workspace}/agents/{agent.json()['id']}/runs"
        created = client.post(base, headers=headers, json={"goal": "Answer once"})
        assert created.status_code == 201, created.text
        identity = created.json()["id"]
        asyncio.run(
            run_durable_agent_run(
                identity, settings(), worker_task_id="quota-test-worker"
            )
        )
        current = client.get(f"{base}/{identity}", headers=headers)
        assert current.status_code == 200, current.text
        assert current.json()["status"] == "failed", current.text
        assert (
            current.json()["last_error"] == "Workspace monthly token quota exceeded."
        ), current.text
        assert ModelTestHandler.calls == [], "A model request escaped quota admission"
    print("WORKSPACE_TOKEN_QUOTA_API_OK")


if __name__ == "__main__":
    check()
