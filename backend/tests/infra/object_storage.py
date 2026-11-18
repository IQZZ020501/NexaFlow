"""Local/S3 contract checks, including parsers with no shared local path."""

import asyncio
import io
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import tests.support  # noqa: F401
from botocore.exceptions import ClientError
from tests.support import settings

from app.infra.storage.object_storage import (
    EmptyObjectError,
    ObjectStorageError,
    ObjectTooLargeError,
    create_object_storage,
    with_local_file,
)
from scripts import migrate_object_storage as migration


class S3:
    objects = None
    closed = 0

    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body):
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, **kwargs):
        self.head_object(**kwargs)
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop(Key, None)

    def get_paginator(self, *_):
        return self

    def paginate(self, *, Bucket, Prefix):
        yield {
            "Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix)]
        }

    def delete_objects(self, *, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)
        return {}


async def contract(storage):
    prefix = uuid4().hex

    async def chunks():
        yield b"hello "
        yield b"world"

    key = prefix + "/one/file.txt"
    try:
        assert await storage.put_chunks(key, chunks(), 100) == 11
        assert storage.stat(key).size_bytes == 11
        assert storage.read_bytes(key, 11) == b"hello world"
        assert b"".join(storage.read_chunks(key)) == b"hello world"
        with storage.materialize(key) as local:
            assert local.read_bytes() == b"hello world"
        assert (
            with_local_file(storage, key, lambda path: path.read_text())
            == "hello world"
        )
        for invalid in ("../escape", "/absolute", "one/../escape", "one\\file", "a//b"):
            try:
                storage.stat(invalid)
            except ObjectStorageError:
                pass
            else:
                raise AssertionError(invalid)
        try:
            storage.read_bytes(key, 2)
        except ObjectTooLargeError:
            pass
        else:
            raise AssertionError("Unbounded read")
        try:
            await storage.put_chunks(prefix + "/too-large", chunks(), 2)
        except ObjectTooLargeError:
            pass
        assert not storage.exists(prefix + "/too-large")

        async def empty():
            if False:
                yield b""

        try:
            await storage.put_chunks(prefix + "/empty", empty(), 2)
        except EmptyObjectError:
            pass
        await storage.put_chunks(prefix + "/empty", empty(), 2, allow_empty=True)
        assert storage.stat(prefix + "/empty").size_bytes == 0
        storage.put_bytes(prefix + "/other", b"outside")
        storage.delete_prefix(prefix + "/one")
        assert not storage.exists(key) and storage.exists(prefix + "/other")
        storage.delete(prefix + "/missing")
    finally:
        storage.delete_prefix(prefix)


async def check():
    with tempfile.TemporaryDirectory(prefix="nexaflow-storage-test-") as directory:
        await contract(create_object_storage(Path(directory)))
        config = replace(
            settings(),
            object_storage_backend="s3",
            object_storage_bucket="test",
            object_storage_endpoint="http://127.0.0.1:9000",
            object_storage_access_key="fixture",
            object_storage_secret_key="fixture-secret",
        )
        for invalid in (
            replace(config, object_storage_backend="unknown"),
            replace(config, object_storage_bucket=""),
            replace(config, object_storage_secret_key=""),
            replace(config, object_storage_endpoint="http://user:secret@example.com"),
            replace(config, object_storage_endpoint="ftp://example.com"),
            replace(
                config,
                object_storage_endpoint="http://example.com",
                environment="production",
            ),
        ):
            try:
                invalid.validate()
            except RuntimeError:
                pass
            else:
                raise AssertionError("Invalid storage configuration was accepted")
        with patch("app.infra.storage.s3.boto3.client", return_value=S3()):
            await contract(create_object_storage(Path(directory), settings=config))
            source = Path(directory) / "legacy"
            (source / "nested").mkdir(parents=True)
            (source / "nested/file.txt").write_bytes(b"migrated")
            (source / "empty").write_bytes(b"")
            args = SimpleNamespace(source_root=source, copy=False)
            with patch.object(migration.Settings, "from_env", return_value=config):
                assert await migration.run(args) == 2
                args.copy = True
                assert await migration.run(args) == 0
                args.copy = False
                assert await migration.run(args) == 0
                storage = create_object_storage(source, settings=config)
                storage.put_bytes("nested/file.txt", b"different remote version")
                try:
                    await migration.run(args)
                except ValueError as exc:
                    assert "SHA-256 mismatch" in str(exc)
                else:
                    raise AssertionError("A conflicting remote object was overwritten")
                assert (source / "nested/file.txt").read_bytes() == b"migrated"

        started, finish = Event(), Event()

        class SlowS3(S3):
            def put_object(self, **kwargs):
                started.set()
                assert finish.wait(5)
                return super().put_object(**kwargs)

        with patch("app.infra.storage.s3.boto3.client", return_value=SlowS3()):
            storage = create_object_storage(Path(directory), settings=config)

            async def content():
                yield b"cancelled upload"

            task = asyncio.create_task(
                storage.put_chunks("cancelled/file", content(), 100)
            )
            assert await asyncio.to_thread(started.wait, 3)
            task.cancel()
            finish.set()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("Upload cancellation disappeared")
            assert not storage.exists("cancelled/file")
        endpoint = os.environ.get("NEXAFLOW_TEST_S3_ENDPOINT")
        if endpoint:
            config = replace(
                config,
                object_storage_endpoint=endpoint,
                object_storage_bucket=os.environ["NEXAFLOW_TEST_S3_BUCKET"],
                object_storage_access_key=os.environ["NEXAFLOW_TEST_S3_ACCESS_KEY"],
                object_storage_secret_key=os.environ["NEXAFLOW_TEST_S3_SECRET_KEY"],
            )
            await contract(create_object_storage(Path(directory), settings=config))
            print("OBJECT_STORAGE_LIVE_S3_OK")
    print("OBJECT_STORAGE_CONTRACT_OK")


if __name__ == "__main__":
    asyncio.run(check())
