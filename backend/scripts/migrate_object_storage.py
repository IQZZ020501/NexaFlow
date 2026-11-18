"""Verify/copy a stopped installation's local files into its private S3 bucket.

Default: read-only verification. --copy copies missing keys, verifies SHA-256,
and never overwrites a different remote object or deletes local files.
"""

import argparse
import asyncio
import hashlib
from pathlib import Path

from app.infra.config.settings import Settings
from app.infra.storage.object_storage import create_object_storage, validate_key


def digest(chunks):
    value = hashlib.sha256()
    for chunk in chunks:
        value.update(chunk)
    return value.digest()


def file_chunks(path):
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            yield chunk


async def run(args):
    settings = Settings.from_env()
    if settings.object_storage_backend != "s3":
        raise ValueError(
            "Configure the target OBJECT_STORAGE_BACKEND=s3 before migration."
        )
    source = args.source_root.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Source root must be a directory.")
    storage = create_object_storage(source, settings=settings)
    verified = copied = missing = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks cannot be migrated.")
        if not path.is_file():
            continue
        key = validate_key(path.relative_to(source).as_posix())
        if not await asyncio.to_thread(storage.exists, key):
            if not args.copy:
                missing += 1
                continue

            async def chunks():
                for chunk in file_chunks(path):
                    yield chunk

            await storage.put_chunks(
                key, chunks(), path.stat().st_size, allow_empty=True
            )
            copied += 1
        local = await asyncio.to_thread(digest, file_chunks(path))
        remote = await asyncio.to_thread(digest, storage.read_chunks(key))
        if local != remote:
            raise ValueError(
                "SHA-256 mismatch; migration stopped without overwriting the remote object."
            )
        verified += 1
    print(f"verified={verified} copied={copied} missing={missing}")
    return 2 if missing else 0


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--copy", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
