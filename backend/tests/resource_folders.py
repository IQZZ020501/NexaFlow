from tests.support import activate_admin, auth_headers, test_client


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

        listed = client.get(f"{base}/knowledge-bases", headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["folder_id"] == hr_id

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


if __name__ == "__main__":
    main()
