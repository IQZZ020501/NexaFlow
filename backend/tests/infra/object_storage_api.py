"""Knowledge upload/parse/download/cleanup without a shared filesystem."""

import asyncio
import os
import tempfile
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import tests.support as support
from tests.infra.object_storage import S3
from tests.knowledge.knowledge import docx_bytes, knowledge_url, upload_document

from app.application.governance.service import _probe_storage
from app.infra.storage.object_storage import create_object_storage


def check():
    endpoint = os.environ.get("NEXAFLOW_TEST_S3_ENDPOINT")
    with tempfile.TemporaryDirectory(prefix="nexaflow-storage-api-") as directory:
        config = replace(
            support.settings(),
            knowledge_storage_dir=Path(directory),
            object_storage_backend="s3",
            object_storage_bucket=os.environ.get("NEXAFLOW_TEST_S3_BUCKET", "test"),
            object_storage_endpoint=endpoint or "http://127.0.0.1:9000",
            object_storage_access_key=os.environ.get(
                "NEXAFLOW_TEST_S3_ACCESS_KEY", "fixture"
            ),
            object_storage_secret_key=os.environ.get(
                "NEXAFLOW_TEST_S3_SECRET_KEY", "fixture-secret"
            ),
        )
        client_patch = (
            nullcontext()
            if endpoint
            else patch("app.infra.storage.s3.boto3.client", return_value=S3())
        )
        env = {
            "OBJECT_STORAGE_BACKEND": "s3",
            "OBJECT_STORAGE_BUCKET": config.object_storage_bucket,
            "OBJECT_STORAGE_ENDPOINT": config.object_storage_endpoint,
            "OBJECT_STORAGE_ACCESS_KEY": config.object_storage_access_key,
            "OBJECT_STORAGE_SECRET_KEY": config.object_storage_secret_key,
        }
        with (
            client_patch,
            patch.object(support, "settings", return_value=config),
            patch.dict(os.environ, env),
            support.test_client() as client,
        ):
            token, workspace = support.activate_admin(client)
            asyncio.run(_probe_storage(config))
            headers = support.auth_headers(token)
            created = client.post(
                knowledge_url(workspace),
                headers=headers,
                json={"name": "Remote files", "description": ""},
            )
            assert created.status_code == 201, created.text
            base = created.json()["id"]
            original = docx_bytes("Remote document body")
            document = upload_document(
                client,
                token,
                workspace,
                base,
                "report.docx",
                original,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            document_url = knowledge_url(
                workspace, f"/{base}/documents/{document['id']}"
            )
            parsed = client.post(
                document_url + "/parse", headers=headers, json={"auto_index": False}
            )
            assert parsed.status_code == 202, parsed.text
            # Readers are newly created clients and cannot use any local upload.
            assert not list(Path(directory).rglob("*"))
            content = client.get(document_url + "/content", headers=headers)
            assert (
                content.status_code == 200 and "Remote document body" in content.text
            ), content.text
            download = client.get(document_url + "/download", headers=headers)
            assert download.status_code == 200 and download.content == original
            assert download.headers["x-content-type-options"] == "nosniff"
            assert download.headers["content-disposition"].startswith("attachment;")
            denied = client.get(document_url + "/download")
            assert denied.status_code in {401, 403}
            deleted = client.delete(document_url, headers=headers)
            assert deleted.status_code == 204, deleted.text
            assert (
                client.get(document_url + "/download", headers=headers).status_code
                == 404
            )
            deleted = client.delete(
                knowledge_url(workspace, f"/{base}"), headers=headers
            )
            assert deleted.status_code == 204, deleted.text
            # Durable cleanup jobs run eagerly in this fixture.
            storage = create_object_storage(Path(directory), settings=config)
            pages = storage.client.get_paginator("list_objects_v2").paginate(
                Bucket=config.object_storage_bucket, Prefix=f"{workspace}/{base}/"
            )
            assert all(not page.get("Contents") for page in pages)
    print("OBJECT_STORAGE_API_OK" + (" live_s3" if endpoint else " fake_s3"))


if __name__ == "__main__":
    check()
