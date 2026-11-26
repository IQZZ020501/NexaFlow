"""Private S3 objects; no public ACLs or bearer URLs are created here."""

import asyncio
import tempfile
from contextlib import contextmanager
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.infra.storage.object_storage import (
    EmptyObjectError,
    ObjectInfo,
    ObjectStorageError,
    ObjectTooLargeError,
    ReadableStorage,
    validate_key,
)


@lru_cache(maxsize=8)
def _cached_s3_client(
    endpoint_url: str | None,
    region_name: str,
    access_key: str,
    secret_key: str,
):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 2},
            s3={"addressing_style": "path"},
        ),
    )


class S3ObjectStorage(ReadableStorage):
    def __init__(self, settings):
        self.bucket = settings.object_storage_bucket
        self.client = _cached_s3_client(
            settings.object_storage_endpoint or None,
            settings.object_storage_region,
            settings.object_storage_access_key,
            settings.object_storage_secret_key,
        )

    @contextmanager
    def _errors(self):
        try:
            yield
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "NotFound", "404"}:
                raise FileNotFoundError("Stored object is missing.") from exc
            raise ObjectStorageError("Object storage request failed.") from exc
        except BotoCoreError as exc:
            raise ObjectStorageError("Object storage request failed.") from exc

    def stat(self, key):
        with self._errors():
            value = self.client.head_object(Bucket=self.bucket, Key=validate_key(key))
            return ObjectInfo(value["ContentLength"])

    @contextmanager
    def open_reader(self, key):
        with self._errors():
            body = self.client.get_object(Bucket=self.bucket, Key=validate_key(key))[
                "Body"
            ]
            try:
                yield body
            finally:
                body.close()

    async def put_chunks(self, key, chunks, max_bytes, *, allow_empty=False):
        validate_key(key)
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as content:
            async for chunk in chunks:
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise ObjectTooLargeError("Object is too large.")
                await asyncio.to_thread(content.write, chunk)
            if not size and not allow_empty:
                raise EmptyObjectError("Object is empty.")
            content.seek(0)
            # Shield cancellation until the upload thread finishes using the spool.
            task = asyncio.create_task(asyncio.to_thread(self._put, key, content))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                try:
                    await task
                finally:
                    # A cancelled caller cannot commit the object's metadata.
                    # Keys are generated per upload, so this removes only its blob.
                    await asyncio.to_thread(self.delete, key)
                raise
        return size

    def _put(self, key, content):
        with self._errors():
            self.client.put_object(
                Bucket=self.bucket, Key=validate_key(key), Body=content
            )

    def put_bytes(self, key, content):
        if not content:
            raise EmptyObjectError("Object is empty.")
        self._put(key, content)
        return len(content)

    def delete(self, key):
        with self._errors():
            self.client.delete_object(Bucket=self.bucket, Key=validate_key(key))

    def delete_prefix(self, prefix):
        prefix = validate_key(prefix.rstrip("/")) + "/"
        with self._errors():
            for page in self.client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    result = self.client.delete_objects(
                        Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True}
                    )
                    if result.get("Errors"):
                        raise ObjectStorageError("Object deletion was not confirmed.")
