import asyncio
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from nexaflow.db.base import Base
from nexaflow.db.session import get_engine
from nexaflow.main import create_app
from nexaflow.testing import settings as testing_settings

INDEX_MARKER = "<title>NexaFlow Test UI</title>"
BUNDLE_MARKER = "nexaflow-test-bundle"


def main() -> None:
    dist_dir = Path(tempfile.mkdtemp(prefix="nexaflow-frontend-test-"))
    try:
        assets_dir = dist_dir / "assets"
        assets_dir.mkdir()
        (dist_dir / "index.html").write_text(
            f"<!doctype html><html><head>{INDEX_MARKER}</head><body></body></html>",
            encoding="utf-8",
        )
        (assets_dir / "app.js").write_text(
            f"console.log('{BUNDLE_MARKER}')", encoding="utf-8"
        )
        secret = dist_dir.parent / "secret.txt"
        secret.write_text("TOP-SECRET", encoding="utf-8")

        settings = replace(testing_settings(), web_dist_dir=dist_dir)
        app = create_app(settings)

        async def create_schema() -> None:
            async with get_engine().begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        asyncio.run(create_schema())

        with TestClient(app) as client:
            root = client.get("/")
            assert root.status_code == 200, root.text
            assert "text/html" in root.headers["content-type"], root.headers
            assert INDEX_MARKER in root.text

            deep_link = client.get("/system/teams")
            assert deep_link.status_code == 200, deep_link.text
            assert INDEX_MARKER in deep_link.text

            deep_link = client.get("/knowledge/kb_123")
            assert deep_link.status_code == 200, deep_link.text
            assert INDEX_MARKER in deep_link.text

            asset = client.get("/assets/app.js")
            assert asset.status_code == 200, asset.text
            assert "javascript" in asset.headers["content-type"], asset.headers
            assert BUNDLE_MARKER in asset.text

            unknown = client.get("/no-such-route")
            assert unknown.status_code == 200, unknown.text
            assert INDEX_MARKER in unknown.text

            traversal = client.get("/%2e%2e/secret.txt")
            assert "TOP-SECRET" not in traversal.text, traversal.text
            traversal = client.get("/../secret.txt")
            assert "TOP-SECRET" not in traversal.text, traversal.text

            api = client.get("/health")
            assert api.status_code == 200, api.text
            assert api.json() == {"status": "ok"}

            api = client.post(
                "/auth/login",
                json={"username": "admin", "password": "NexaFlow@123."},
            )
            assert api.status_code == 200, api.text
    finally:
        shutil.rmtree(dist_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
