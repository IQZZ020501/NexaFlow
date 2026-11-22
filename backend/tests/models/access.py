"""Personal/shared model isolation through the real API and database."""

import asyncio
from unittest.mock import AsyncMock, patch

from tests.models.llm import MEMBER_PASSWORD, create_workspace_user, models_url
from tests.support import activate_admin, activate_user, auth_headers, test_client

from app.infra.db.repositories.models import registry as model_repository
from app.infra.db.session import get_session_factory


def main() -> None:
    with (
        test_client() as client,
        patch(
            "app.application.models.service.test_registered_model",
            new=AsyncMock(return_value={}),
        ) as connection_test,
        patch(
            "app.adapters.llm.network.public_addresses", return_value=("93.184.216.34",)
        ),
    ):
        admin, workspace_id = activate_admin(client)
        tokens = []
        for username in ("model-owner", "model-peer"):
            password = create_workspace_user(client, admin, workspace_id, username)
            tokens.append(activate_user(client, username, password, MEMBER_PASSWORD))
        owner, peer = tokens
        url = models_url(workspace_id)
        payload = {
            "name": "My model",
            "provider": "model_custom_provider",
            "provider_type": "openai_compatible",
            "model_type": "LLM",
            "model_name": "custom-chat",
            "credential": {
                "api_base": "https://models.example.com/v1",
                "api_key": "test-key",
            },
        }

        personal = client.post(url, headers=auth_headers(owner), json=payload)
        assert personal.status_code == 201, personal.text
        model = personal.json()
        assert model["visibility"] == "personal" and model["can_manage"]
        assert model["credential"]["api_key"] != "test-key"
        model_url = f"{url}/{model['id']}"
        for token in (peer, admin):
            assert client.get(url, headers=auth_headers(token)).json() == []
            assert client.get(model_url, headers=auth_headers(token)).status_code == 404
            assert (
                client.patch(
                    model_url, headers=auth_headers(token), json={"name": "Stolen"}
                ).status_code
                == 404
            )
            assert (
                client.delete(model_url, headers=auth_headers(token)).status_code == 404
            )

        updated = client.patch(
            model_url, headers=auth_headers(owner), json={"name": "Renamed"}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["visibility"] == "personal"
        count = connection_test.await_count
        denied = client.post(
            url,
            headers=auth_headers(owner),
            json={**payload, "visibility": "workspace"},
        )
        assert denied.status_code == 403, denied.text
        assert connection_test.await_count == count
        promoted = client.patch(
            model_url, headers=auth_headers(owner), json={"visibility": "workspace"}
        )
        assert promoted.status_code == 422, promoted.text

        # Equal names are independent across owners and the shared catalog.
        for token, visibility in (
            (peer, "personal"),
            (admin, "personal"),
            (admin, "workspace"),
        ):
            response = client.post(
                url,
                headers=auth_headers(token),
                json={**payload, "name": "Renamed", "visibility": visibility},
            )
            assert response.status_code == 201, response.text
        shared = client.get(
            url + "?visibility=workspace", headers=auth_headers(owner)
        ).json()
        assert len(shared) == 1 and not shared[0]["can_manage"]
        shared_url = f"{url}/{shared[0]['id']}"
        assert (
            client.patch(
                shared_url, headers=auth_headers(owner), json={"status": "disabled"}
            ).status_code
            == 403
        )
        assert client.delete(shared_url, headers=auth_headers(owner)).status_code == 403
        mine = client.get(
            url + "?visibility=personal&limit=1", headers=auth_headers(owner)
        ).json()
        assert len(mine) == 1 and mine[0]["id"] == model["id"]
        duplicate = client.post(
            url, headers=auth_headers(owner), json={**payload, "name": "Renamed"}
        )
        assert duplicate.status_code == 409, duplicate.text

        for token, expected in ((owner, 201), (peer, 422), (admin, 422)):
            agent = client.post(
                f"/api/v1/workspaces/{workspace_id}/agents",
                headers=auth_headers(token),
                json={"name": "Private model agent", "model_id": model["id"]},
            )
            assert agent.status_code == expected, agent.text
            if token == owner:
                own_agent_id = agent.json()["id"]
        peer_id = client.get("/api/v1/auth/me", headers=auth_headers(peer)).json()[
            "user"
        ]["id"]
        agents_url = f"/api/v1/workspaces/{workspace_id}/agents"
        granted = client.put(
            f"{agents_url}/{own_agent_id}/permissions/{peer_id}",
            headers=auth_headers(owner),
            json={"permission": "view"},
        )
        assert granted.status_code == 200, granted.text
        denied_run = client.post(
            f"{agents_url}/{own_agent_id}/runs",
            headers=auth_headers(peer),
            json={"goal": "Call another user's private model"},
        )
        assert denied_run.status_code == 422, denied_run.text
        # AI prompt generation is another direct model-call surface.
        prompt = client.post(
            f"{agents_url}/{own_agent_id}/generate-instructions",
            headers=auth_headers(peer),
            json={"model_id": model["id"], "content": "Write a prompt"},
        )
        assert prompt.status_code in {403, 422}, prompt.text

        admin_personal = client.get(
            url + "?visibility=personal", headers=auth_headers(admin)
        ).json()[0]
        private_agent = client.post(
            agents_url,
            headers=auth_headers(admin),
            json={"name": "Private admin agent", "model_id": admin_personal["id"]},
        )
        assert private_agent.status_code == 201, private_agent.text
        publish = client.patch(
            f"{agents_url}/{private_agent.json()['id']}",
            headers=auth_headers(admin),
            json={"published": True},
        )
        assert publish.status_code == 422, publish.text

        from tests.workflows.workflows import graph

        workflow = client.post(
            agents_url,
            headers=auth_headers(admin),
            json={
                "name": "Private workflow",
                "app_type": "workflow",
                "model_id": admin_personal["id"],
            },
        )
        assert workflow.status_code == 201, workflow.text
        workflow_url = (
            f"/api/v1/workspaces/{workspace_id}/workflows/{workflow.json()['id']}"
        )
        definition = client.get(
            workflow_url + "/definition", headers=auth_headers(admin)
        )
        updated_definition = client.put(
            workflow_url + "/definition",
            headers=auth_headers(admin),
            json={"graph": graph(), "expected_revision": definition.json()["revision"]},
        )
        assert updated_definition.status_code == 200, updated_definition.text
        assert (
            client.post(
                workflow_url + "/publish", headers=auth_headers(admin), json={}
            ).status_code
            == 422
        )

        with patch("app.ports.runs.enqueue_agent_run", new=AsyncMock()):
            own_run = client.post(
                f"{agents_url}/{own_agent_id}/runs",
                headers=auth_headers(owner),
                json={"goal": "Use my model"},
            )
        assert own_run.status_code == 201, own_run.text
        assert own_run.json()["model_id"] == model["id"]

        # Members can organize their personal models; private folders do not
        # reveal model metadata to peers or workspace administrators.
        folders_url = f"/api/v1/workspaces/{workspace_id}/resource-folders"
        folder = client.post(
            folders_url,
            headers=auth_headers(owner),
            json={"name": "Private models", "resource_type": "model"},
        )
        assert folder.status_code == 201, folder.text
        move = {
            "resource_type": "model",
            "resource_id": model["id"],
            "folder_id": folder.json()["id"],
        }
        assert (
            client.put(
                folders_url + "/resources/move", headers=auth_headers(owner), json=move
            ).status_code
            == 204
        )
        assert (
            client.get(model_url, headers=auth_headers(owner)).json()["folder_id"]
            == folder.json()["id"]
        )
        assert (
            client.get(
                folders_url + "?resource_type=model", headers=auth_headers(peer)
            ).json()
            == []
        )
        assert (
            client.put(
                folders_url + "/resources/move",
                headers=auth_headers(peer),
                json={**move, "folder_id": None},
            ).status_code
            == 404
        )
        assert (
            client.put(
                folders_url + "/resources/move",
                headers=auth_headers(owner),
                json={**move, "resource_id": shared[0]["id"]},
            ).status_code
            == 403
        )

        embedding = client.post(
            url,
            headers=auth_headers(owner),
            json={**payload, "name": "My embeddings", "model_type": "EMBEDDING"},
        )
        assert embedding.status_code == 201, embedding.text
        knowledge_url = f"/api/v1/workspaces/{workspace_id}/knowledge-bases"
        for token, expected in ((owner, 201), (peer, 422), (admin, 422)):
            knowledge = client.post(
                knowledge_url,
                headers=auth_headers(token),
                json={
                    "name": "Private embedding",
                    "embedding_model_id": embedding.json()["id"],
                },
            )
            assert knowledge.status_code == expected, knowledge.text
            if token == owner:
                knowledge_id = knowledge.json()["id"]
        granted = client.put(
            f"{knowledge_url}/{knowledge_id}/permissions/{peer_id}",
            headers=auth_headers(owner),
            json={"permission": "view"},
        )
        assert granted.status_code == 200, granted.text
        denied_query = client.post(
            f"{knowledge_url}/{knowledge_id}/query",
            headers=auth_headers(peer),
            json={"query": "test", "search_mode": "embedding"},
        )
        assert denied_query.status_code == 422, denied_query.text
        assert client.delete(model_url, headers=auth_headers(owner)).status_code == 409

        owner_id = client.get("/api/v1/auth/me", headers=auth_headers(owner)).json()[
            "user"
        ]["id"]
        deleted = client.delete(
            f"/api/v1/admin/users/{owner_id}", headers=auth_headers(admin)
        )
        assert deleted.status_code == 204, deleted.text

        async def verify_retired_credentials():
            async with get_session_factory()() as db:
                retired = await model_repository.get_registered_model_by_id(
                    db, model["id"]
                )
                assert retired.status == "disabled"
                assert retired.api_key_ciphertext is None
                assert (
                    retired.credential_config == {}
                    and retired.credential_secret_hints == {}
                )
                shared_model = await model_repository.get_registered_model_by_id(
                    db, shared[0]["id"]
                )
                assert (
                    shared_model.status == "active" and shared_model.api_key_ciphertext
                )

        asyncio.run(verify_retired_credentials())

    print("MODEL_ACCESS_OK")


if __name__ == "__main__":
    main()
