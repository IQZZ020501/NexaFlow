from collections.abc import AsyncIterable
from pathlib import Path
import shutil


class ObjectStorageError(Exception):
    pass


class ObjectTooLargeError(ObjectStorageError):
    pass


class EmptyObjectError(ObjectStorageError):
    pass


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ObjectStorageError("Object key escapes the storage root.")
        return candidate

    async def put_chunks(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        max_bytes: int,
    ) -> int:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            with target.open("wb") as output:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise ObjectTooLargeError("Object is too large.")
                    output.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if size == 0:
            target.unlink(missing_ok=True)
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
        target = self.path(prefix)
        shutil.rmtree(target, ignore_errors=True)
