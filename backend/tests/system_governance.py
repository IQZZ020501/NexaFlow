from tests.support import ADMIN_PASSWORD, auth_headers, activate_admin, login, test_client


def main() -> None:
    """
    Run the end-to-end governance and access-control integration test.
    """
    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        admin_headers = auth_headers(admin_token)

        health = client.get(
            "/api/v1/admin/governance/health", headers=admin_headers
        )
        assert health.status_code == 200, health.text
        assert health.json()["components"]["database"]["status"] == "ok"

        updated = client.patch(
            f"/api/v1/workspaces/{workspace_id}/governance",
            headers=admin_headers,
            json={
                "daily_run_limit": 50,
                "monthly_token_limit": 100_000,
                "alert_threshold_percent": 80,
                "retention_days": 90,
                "timezone": "Asia/Shanghai",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["daily_run_limit"] == 50

        inventory = client.get(
            f"/api/v1/workspaces/{workspace_id}/inventory", headers=admin_headers
        )
        assert inventory.status_code == 200, inventory.text
        assert inventory.json()["members_total"] == 1

        sessions = client.get("/api/v1/auth/sessions", headers=admin_headers)
        assert sessions.status_code == 200, sessions.text
        assert any(item["is_current"] for item in sessions.json())
        current_session = next(item for item in sessions.json() if item["is_current"])
        assert current_session["user_agent"] == "testclient"
        assert current_session["ip_address"] == "testclient"

        failed_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Wrong@12345."},
        )
        assert failed_login.status_code == 401, failed_login.text
        system_logs = client.get(
            "/api/v1/admin/system-logs?event=auth.login_failed",
            headers=admin_headers,
        )
        assert system_logs.status_code == 200, system_logs.text
        assert system_logs.json()[0]["message"] == "Login failed."

        invitation = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={
                "username": "workspace-admin",
                "email": "workspace-admin@example.com",
                "name": "Workspace Admin",
                "role": "admin",
            },
        )
        assert invitation.status_code == 201, invitation.text
        assert invitation.json()["kind"] == "personal"
        assert invitation.json()["invite_url"].startswith("/invite/")
        assert "?" not in invitation.json()["invite_url"]
        invite_token = invitation.json()["token"]

        accepted = client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": invite_token, "password": ADMIN_PASSWORD},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["workspaces"][0]["role"] == "admin"
        reused_personal = client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": invite_token, "password": ADMIN_PASSWORD},
        )
        assert reused_personal.status_code == 400, reused_personal.text

        ambiguous_invitation = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"role": "member"},
        )
        assert ambiguous_invitation.status_code == 422, ambiguous_invitation.text

        generic = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"kind": "generic", "role": "member"},
        )
        assert generic.status_code == 201, generic.text
        generic_payload = generic.json()
        assert generic_payload["kind"] == "generic"
        assert generic_payload["username"] is None
        assert generic_payload["invite_url"].endswith("?mode=generic")
        generic_token = generic_payload["token"]

        generic_admin = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"kind": "generic", "role": "admin"},
        )
        assert generic_admin.status_code == 422, generic_admin.text

        missing_identity = client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": generic_token, "password": ADMIN_PASSWORD},
        )
        assert missing_identity.status_code == 422, missing_identity.text

        for suffix in ("one", "two"):
            generic_acceptance = client.post(
                "/api/v1/auth/invitations/accept",
                json={
                    "token": generic_token,
                    "username": f"generic-{suffix}",
                    "email": f"generic-{suffix}@example.com",
                    "name": f"Generic {suffix.title()}",
                    "password": ADMIN_PASSWORD,
                },
            )
            assert generic_acceptance.status_code == 200, generic_acceptance.text
            assert generic_acceptance.json()["workspaces"][0]["role"] == "member"

        generic_invitation = next(
            item
            for item in client.get(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                headers=admin_headers,
            ).json()
            if item["id"] == generic_payload["id"]
        )
        assert generic_invitation["accepted_at"] is None

        revoked = client.delete(
            f"/api/v1/workspaces/{workspace_id}/invitations/{generic_payload['id']}",
            headers=admin_headers,
        )
        assert revoked.status_code == 204, revoked.text
        after_revoke = client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": generic_token,
                "username": "generic-three",
                "email": "generic-three@example.com",
                "name": "Generic Three",
                "password": ADMIN_PASSWORD,
            },
        )
        assert after_revoke.status_code == 400, after_revoke.text

        workspace_admin_token = login(
            client, "workspace-admin", ADMIN_PASSWORD
        )["access_token"]
        workspace_admin_headers = auth_headers(workspace_admin_token)
        assert (
            client.get(
                f"/api/v1/workspaces/{workspace_id}/governance",
                headers=workspace_admin_headers,
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/admin/system-logs", headers=workspace_admin_headers
            ).status_code
            == 403
        )


if __name__ == "__main__":
    main()
