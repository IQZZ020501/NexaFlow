"""Storage access shared by local files and private S3-compatible buckets."""

import asyncio
import shutil
import tempfile
from collections.abc import AsyncIterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int


class ObjectStorage(Protocol):
    def stat(self, key: str) -> ObjectInfo: ...
    def open_reader(self, key: str) -> AbstractContextManager[BinaryIO]: ...
    def materialize(self, key: str) -> AbstractContextManager[Path]: ...
    def read_bytes(self, key: str, max_bytes: int) -> bytes: ...
    def read_chunks(self, key: str) -> Iterator[bytes]: ...
    def exists(self, key: str) -> bool: ...
    async def put_chunks(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        max_bytes: int | None,
        *,
        allow_empty: bool = False,
    ) -> int: ...
    def put_bytes(self, key: str, content: bytes) -> int: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...


def create_object_storage(root: Path, *, settings=None) -> ObjectStorage:
    if settings is not None and settings.object_storage_backend == "s3":
        from app.infra.storage.s3 import S3ObjectStorage

        return S3ObjectStorage(settings)
    return LocalObjectStorage(root)


class ObjectStorageError(Exception):
    pass


class ObjectTooLargeError(ObjectStorageError):
    pass


class EmptyObjectError(ObjectStorageError):
    pass


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not key or "\\" in key or "\x00" in key:
        raise ObjectStorageError("Invalid object key.")
    parts = key.split("/")
    if PurePosixPath(key).is_absolute() or any(
        part in {"", ".", ".."} for part in parts
    ):
        raise ObjectStorageError("Object key escapes the storage root.")
    return key


class ReadableStorage:
    def exists(self, key: str) -> bool:
        try:
            self.stat(key)
            return True
        except FileNotFoundError:
            return False

    def read_bytes(self, key: str, max_bytes: int) -> bytes:
        with self.open_reader(key) as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ObjectTooLargeError("Object is too large.")
        return content

    def read_chunks(self, key: str) -> Iterator[bytes]:
        with self.open_reader(key) as stream:
            while chunk := stream.read(64 * 1024):
                yield chunk

    @contextmanager
    def materialize(self, key: str):
        with tempfile.TemporaryDirectory(prefix="nexaflow-object-") as directory:
            target = Path(directory) / "input"
            with self.open_reader(key) as source, target.open("wb") as output:
                size = 0
                while chunk := source.read(64 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise ObjectTooLargeError("Object is too large.")
                    output.write(chunk)
            yield target


class LocalObjectStorage(ReadableStorage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        candidate = (self.root / validate_key(key)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ObjectStorageError("Object key escapes the storage root.")
        return candidate

    def stat(self, key: str) -> ObjectInfo:
        path = self.path(key)
        if not path.is_file():
            raise FileNotFoundError("Stored object is missing.")
        return ObjectInfo(path.stat().st_size)

    def open_reader(self, key: str):
        return self.path(key).open("rb")

    @contextmanager
    def materialize(self, key: str):
        yield self.path(key)

    async def put_chunks(self, key, chunks, max_bytes, *, allow_empty=False) -> int:
        target = self.path(key)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        size = 0
        output = await asyncio.to_thread(target.open, "wb")
        try:
            async for chunk in chunks:
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise ObjectTooLargeError("Object is too large.")
                await asyncio.to_thread(output.write, chunk)
        except BaseException:
            await asyncio.to_thread(output.close)
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
        await asyncio.to_thread(output.close)
        if size == 0 and not allow_empty:
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise EmptyObjectError("Object is empty.")
        return size

    def put_bytes(self, key: str, content: bytes) -> int:
        if not content:
            raise EmptyObjectError("Object is empty.")
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return len(content)

    def delete(self, key: str) -> None:
        target = self.path(key)
        target.unlink(missing_ok=True)
        parent = target.parent
        while parent != self.root and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def delete_prefix(self, prefix: str) -> None:
        try:
            shutil.rmtree(self.path(prefix))
        except FileNotFoundError:
            pass


def with_local_file(storage: ObjectStorage, key: str, operation, *args, **kwargs):
    """Call only in a worker thread; remote downloads and parsing may block."""
    with storage.materialize(key) as path:
        return operation(*args, path, **kwargs)
