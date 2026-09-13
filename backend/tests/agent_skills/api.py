"""Agent Skill control-plane API smoke tests."""

from tests.support import auth_headers, activate_user, test_client
from tests.models.llm import model_payload, model_test_server


def test_agent_skill_lifecycle() -> None:
    with test_client() as client, model_test_server() as model_base_url:
        token = activate_user(
            client, "admin", "NexaFlow@123.", "NexaFlow@12345."
        )
        me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["user"]
        workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(token),
            json={"name": "skill-api", "admin_user_id": me["id"]},
        )
        assert workspace.status_code == 201, workspace.text
        workspace_id = workspace.json()["workspace"]["id"]
        created = client.post(
            f"/api/v1/workspaces/{workspace_id}/agent-skills",
            headers=auth_headers(token),
            json={
                "name": "Research Skill",
                "description": "Evidence-backed answers",
                "definition": {
                    "intents": ["research"],
                    "instructions": "Use workspace evidence.",
                    "knowledge_base_ids": [],
                    "tools": [],
                },
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        published = client.post(
            f"/api/v1/workspaces/{workspace_id}/agent-skills/{skill['id']}/publish",
            headers=auth_headers(token),
        )
        assert published.status_code == 200, published.text
        listed = client.get(
            f"/api/v1/workspaces/{workspace_id}/agent-skills",
            headers=auth_headers(token),
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["current_version_number"] == 1
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=auth_headers(token),
            json={**model_payload(model_base_url), "name": "Skill API Model"},
        )
        assert model.status_code == 201, model.text
        agent = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=auth_headers(token),
            json={
                "name": "Skill API Agent",
                "instructions": "Use the attached skill.",
                "model_id": model.json()["id"],
                "skills": [
                    {"skill_id": skill["id"], "version_id": published.json()["id"]}
                ],
            },
        )
        assert agent.status_code == 201, agent.text
        assert agent.json()["skills"] == [
            {"skill_id": skill["id"], "version_id": published.json()["id"]}
        ]


def main() -> None:
    test_agent_skill_lifecycle()
    print("AGENT_SKILLS_API_OK")


if __name__ == "__main__":
    main()
