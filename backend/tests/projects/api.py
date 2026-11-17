"""Private project API, immutable versions, atomic renames and stale writes."""

from tests.support import activate_admin, auth_headers, create_active_user, test_client


def main():
    with test_client() as client:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        root = f"/api/v1/workspaces/{workspace_id}/projects"
        created = client.post(root, json={"name": "Durable files"}, headers=headers)
        assert created.status_code == 201, created.text
        project = created.json()
        base = f"{root}/{project['id']}"

        def upload(path, content, expected=None, role="work"):
            data = {"path": path, "role": role}
            if expected:
                data["expected_version_id"] = expected
            return client.post(f"{base}/files", headers=headers, data=data, files={"file": ("file.txt", content)})

        source = upload("data/source.csv", b"value\n12\n", role="source")
        assert source.status_code == 200, source.text
        first = upload("scripts/convert.py", b"print(12)")
        assert first.status_code == 200, first.text
        first = first.json()
        assert upload("scripts/convert.py", b"stale").status_code == 409
        second = upload("scripts/convert.py", b"print(24)", first["id"])
        assert second.status_code == 200, second.text
        second = second.json()
        retry = upload("scripts/convert.py", b"print(24)", first["id"])
        assert retry.status_code == 200 and retry.json()["id"] == second["id"]
        assert upload("scripts/convert.py", b"print(36)", first["id"]).status_code == 409
        old = client.get(f"{base}/versions/{first['id']}/content", headers=headers)
        assert old.content == b"print(12)" and old.headers["x-content-type-options"] == "nosniff"
        rename = {"path": "scripts/convert.py", "new_path": "scripts/main.py", "expected_version_id": second["id"]}
        renamed = client.post(f"{base}/files/rename", headers=headers, json=rename)
        assert renamed.status_code == 200, renamed.text
        assert client.post(f"{base}/files/rename", headers=headers, json=rename).json()["id"] == renamed.json()["id"]
        heads = {item["path"]: item for item in client.get(f"{base}/files", headers=headers).json()}
        assert heads["scripts/convert.py"]["deleted"] and not heads["scripts/main.py"]["deleted"]
        delete = {"path": "scripts/main.py", "expected_version_id": renamed.json()["id"]}
        deleted = client.request("DELETE", f"{base}/files", headers=headers, json=delete)
        assert deleted.status_code == 200 and deleted.json()["deleted"], deleted.text
        assert client.request("DELETE", f"{base}/files", headers=headers, json=delete).json()["id"] == deleted.json()["id"]
        assert upload("scripts/main.py", b"resurrect", renamed.json()["id"]).status_code == 409
        history = client.get(f"{base}/versions", headers=headers, params={"path": "scripts/main.py"})
        assert [item["deleted"] for item in history.json()] == [True, False]
        for path in ("../escape.txt", "a//b.txt", "node_modules/package.json", ".git/config", "a\\b.txt"):
            assert upload(path, b"bad").status_code == 422, path
        assert upload("parent.txt", b"file").status_code == 200
        assert upload("parent.txt/child.txt", b"collision").status_code == 409
        assert upload("empty.txt", b"").status_code == 422
        owner_id = client.get("/api/v1/auth/me", headers=headers).json()["user"]["id"]
        other_workspace = client.post("/api/v1/workspaces", headers=headers, json={"name": "Other", "admin_user_id": owner_id})
        assert other_workspace.status_code == 201, other_workspace.text
        other_root = f"/api/v1/workspaces/{other_workspace.json()['workspace']['id']}/projects"
        assert client.get(f"{other_root}/{project['id']}", headers=headers).status_code == 404
        assert client.get(f"{other_root}/{project['id']}/versions/{first['id']}/content", headers=headers).status_code == 404
        other_id, other_token = create_active_user(client, token, "project-other")
        member = client.post(f"/api/v1/workspaces/{workspace_id}/members", headers=headers, json={"user_id": other_id, "role": "admin"})
        assert member.status_code == 201, member.text
        other_headers = auth_headers(other_token)
        assert client.get(base, headers=other_headers).status_code == 404
        assert client.get(f"{base}/versions/{first['id']}/content", headers=other_headers).status_code == 404
        own = client.post(root, json={"name": "Other owner"}, headers=other_headers)
        assert own.status_code == 201, own.text
        # A global/workspace administrator has no implicit access to another owner's files.
        assert client.get(f"{root}/{own.json()['id']}", headers=headers).status_code == 404
        assert client.delete(base, headers=headers).status_code == 204
        assert client.get(base, headers=headers).status_code == 404
    print("PROJECT_API_OK")


if __name__ == "__main__":
    main()
