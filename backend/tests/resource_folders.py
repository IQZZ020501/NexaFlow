import asyncio

from app.capabilities.llm.models import RegisteredModel
from app.infra.db.session import get_session_factory
from tests.support import activate_admin, activate_user, auth_headers, test_client

MEMBER_PASSWORD = "FolderMember@12345."


async def create_registered_model(workspace_id: str, user_id: str) -> str:
    async with get_session_factory()() as db:
        model = RegisteredModel(
            workspace_id=workspace_id,
            name="目录模型",
            provider="model_custom_provider",
            provider_type="openai_compatible",
            api_base="https://models.example.com/v1",
            credential_config={},
            credential_secret_hints={},
            model_type="LLM",
            model_name="folder-model",
            status="active",
            meta={},
            created_by_user_id=user_id,
        )
        db.add(model)
        await db.commit()
        await db.refresh(model)
        return model.id


def main() -> None:
    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        headers = auth_headers(admin_token)
        base = f"/api/v1/workspaces/{workspace_id}"

        rules = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "规章制度", "resource_type": "knowledge", "parent_id": None},
        )
        assert rules.status_code == 201, rules.text
        rules_id = rules.json()["id"]

        hr = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "人事制度", "resource_type": "knowledge", "parent_id": rules_id},
        )
        assert hr.status_code == 201, hr.text
        hr_id = hr.json()["id"]

        cycle = client.patch(
            f"{base}/resource-folders/{rules_id}",
            headers=headers,
            json={"parent_id": hr_id},
        )
        assert cycle.status_code == 422, cycle.text

        knowledge = client.post(
            f"{base}/knowledge-bases",
            headers=headers,
            json={"name": "员工手册", "description": ""},
        )
        assert knowledge.status_code == 201, knowledge.text
        knowledge_id = knowledge.json()["id"]
        second_knowledge = client.post(
            f"{base}/knowledge-bases",
            headers=headers,
            json={"name": "薪酬制度", "description": ""},
        )
        assert second_knowledge.status_code == 201, second_knowledge.text
        second_knowledge_id = second_knowledge.json()["id"]

        moved = client.put(
            f"{base}/resource-folders/resources/move",
            headers=headers,
            json={
                "resource_type": "knowledge",
                "resource_id": knowledge_id,
                "folder_id": hr_id,
            },
        )
        assert moved.status_code == 204, moved.text

        batch_moved = client.put(
            f"{base}/resource-folders/resources/move-batch",
            headers=headers,
            json={
                "resource_type": "knowledge",
                "resource_ids": [knowledge_id, second_knowledge_id],
                "folder_id": hr_id,
            },
        )
        assert batch_moved.status_code == 204, batch_moved.text

        rejected_batch = client.put(
            f"{base}/resource-folders/resources/move-batch",
            headers=headers,
            json={
                "resource_type": "knowledge",
                "resource_ids": [
                    knowledge_id,
                    "00000000-0000-0000-0000-000000000000",
                ],
                "folder_id": rules_id,
            },
        )
        assert rejected_batch.status_code == 404, rejected_batch.text

        empty_batch = client.put(
            f"{base}/resource-folders/resources/move-batch",
            headers=headers,
            json={
                "resource_type": "knowledge",
                "resource_ids": [],
                "folder_id": hr_id,
            },
        )
        assert empty_batch.status_code == 422, empty_batch.text

        listed = client.get(f"{base}/knowledge-bases", headers=headers)
        assert listed.status_code == 200, listed.text
        folders_by_knowledge_id = {
            item["id"]: item["folder_id"] for item in listed.json()
        }
        assert folders_by_knowledge_id[knowledge_id] == hr_id
        assert folders_by_knowledge_id[second_knowledge_id] == hr_id

        deleted = client.delete(
            f"{base}/resource-folders/{hr_id}",
            headers=headers,
        )
        assert deleted.status_code == 204, deleted.text

        listed = client.get(f"{base}/knowledge-bases", headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["folder_id"] == rules_id

        application_folder = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "应用目录", "resource_type": "application", "parent_id": None},
        )
        assert application_folder.status_code == 201, application_folder.text
        by_type = client.get(
            f"{base}/resource-folders?resource_type=application",
            headers=headers,
        )
        assert by_type.status_code == 200, by_type.text
        assert [item["name"] for item in by_type.json()] == ["应用目录"]

        cross_type_child = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "错误目录", "resource_type": "tool", "parent_id": rules_id},
        )
        assert cross_type_child.status_code == 422, cross_type_child.text
        cross_type_move = client.put(
            f"{base}/resource-folders/resources/move",
            headers=headers,
            json={
                "resource_type": "knowledge",
                "resource_id": knowledge_id,
                "folder_id": application_folder.json()["id"],
            },
        )
        assert cross_type_move.status_code == 422, cross_type_move.text

        # ---- error branches ----
        missing_parent = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={
                "name": "无父目录",
                "resource_type": "knowledge",
                "parent_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert missing_parent.status_code == 422, missing_parent.text

        # Duplicate names conflict per parent (NULL parents never collide).
        sibling = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "甲目录", "resource_type": "knowledge", "parent_id": rules_id},
        )
        assert sibling.status_code == 201, sibling.text
        sibling_id = sibling.json()["id"]
        duplicate = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "甲目录", "resource_type": "knowledge", "parent_id": rules_id},
        )
        assert duplicate.status_code == 409, duplicate.text

        missing_update = client.patch(
            f"{base}/resource-folders/00000000-0000-0000-0000-000000000000",
            headers=headers,
            json={"name": "不存在"},
        )
        assert missing_update.status_code == 404, missing_update.text

        self_parent = client.patch(
            f"{base}/resource-folders/{rules_id}",
            headers=headers,
            json={"parent_id": rules_id},
        )
        assert self_parent.status_code == 422, self_parent.text

        rename_target = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "乙目录", "resource_type": "knowledge", "parent_id": rules_id},
        )
        assert rename_target.status_code == 201, rename_target.text
        duplicate_update = client.patch(
            f"{base}/resource-folders/{rename_target.json()['id']}",
            headers=headers,
            json={"name": "甲目录"},
        )
        assert duplicate_update.status_code == 409, duplicate_update.text

        missing_delete = client.delete(
            f"{base}/resource-folders/00000000-0000-0000-0000-000000000000",
            headers=headers,
        )
        assert missing_delete.status_code == 404, missing_delete.text

        # Deleting a non-empty folder reparents its contents instead of failing.
        reparent_delete = client.delete(
            f"{base}/resource-folders/{rules_id}",
            headers=headers,
        )
        assert reparent_delete.status_code == 204, reparent_delete.text

        # Move branches for the other resource types surface as not found
        # when the target resource does not exist.
        missing_application_move = client.put(
            f"{base}/resource-folders/resources/move",
            headers=headers,
            json={
                "resource_type": "application",
                "resource_id": "00000000-0000-0000-0000-000000000000",
                "folder_id": application_folder.json()["id"],
            },
        )
        assert missing_application_move.status_code == 404, missing_application_move.text
        tool_folder = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "工具目录", "resource_type": "tool", "parent_id": None},
        )
        assert tool_folder.status_code == 201, tool_folder.text
        missing_tool_move = client.put(
            f"{base}/resource-folders/resources/move",
            headers=headers,
            json={
                "resource_type": "tool",
                "resource_id": "00000000-0000-0000-0000-000000000000",
                "folder_id": tool_folder.json()["id"],
            },
        )
        assert missing_tool_move.status_code == 404, missing_tool_move.text

        model_id = asyncio.run(
            create_registered_model(
                workspace_id,
                client.get("/api/v1/auth/me", headers=headers).json()["user"]["id"],
            )
        )
        model_folder = client.post(
            f"{base}/resource-folders",
            headers=headers,
            json={"name": "模型目录", "resource_type": "model", "parent_id": None},
        )
        assert model_folder.status_code == 201, model_folder.text
        model_folder_id = model_folder.json()["id"]
        member = client.post(
            f"{base}/members/users",
            headers=headers,
            json={
                "username": "folder-member",
                "email": "folder-member@example.com",
                "name": "Folder Member",
            },
        )
        assert member.status_code == 201, member.text
        member_token = activate_user(
            client,
            "folder-member",
            member.json()["initial_password"],
            MEMBER_PASSWORD,
        )
        denied_model_move = client.put(
            f"{base}/resource-folders/resources/move",
            headers=auth_headers(member_token),
            json={
                "resource_type": "model",
                "resource_id": model_id,
                "folder_id": model_folder_id,
            },
        )
        assert denied_model_move.status_code == 403, denied_model_move.text
        moved_model = client.put(
            f"{base}/resource-folders/resources/move",
            headers=headers,
            json={
                "resource_type": "model",
                "resource_id": model_id,
                "folder_id": model_folder_id,
            },
        )
        assert moved_model.status_code == 204, moved_model.text
        listed_models = client.get(f"{base}/models", headers=headers)
        assert listed_models.status_code == 200, listed_models.text
        assert listed_models.json()[0]["folder_id"] == model_folder_id

        deleted_model_folder = client.delete(
            f"{base}/resource-folders/{model_folder_id}",
            headers=headers,
        )
        assert deleted_model_folder.status_code == 204, deleted_model_folder.text
        listed_models = client.get(f"{base}/models", headers=headers)
        assert listed_models.json()[0]["folder_id"] is None


if __name__ == "__main__":
    main()
