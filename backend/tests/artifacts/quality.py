"""Inspection provenance and immutable persistence at the artifact boundary."""

import asyncio
import hashlib
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import tests.support  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.application.artifacts.service import create_generated_artifact
from app.domain.artifacts.services import (
    validate_artifact_inspection,
    validate_generated_artifact,
)
from app.infra.db.base import Base
from app.infra.db.repositories.artifacts import repository


def report(content):
    return {
        "schema_version": 1, "validator": "nexaflow-file-check/1", "status": "passed",
        "format": "txt", "sha256": hashlib.sha256(content).hexdigest(),
        "checks": ["size", "sha256", "text_parse"], "details": {"characters": len(content)}, "warnings": [],
    }


async def persistence():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            link = await create_generated_artifact(
                db, settings(), workspace_id="ws", run_id=None, invocation_id="invocation",
                idempotency_key="file", artifact_format="txt", filename="report.txt",
                content=b"version one", inspection=report(b"version one"),
            )
            await db.commit()
            saved = await repository.get_artifact(db, link.artifact_id)
            assert saved.inspection == report(b"version one")
            assert saved.invocation_id == "invocation"
            replay = await create_generated_artifact(
                db, settings(), workspace_id="ws", run_id=None, invocation_id="another",
                idempotency_key="file", artifact_format="txt", filename="report.txt",
                content=b"different", inspection=report(b"different"),
            )
            assert replay.artifact_id == link.artifact_id
            assert replay.inspection == link.inspection
    finally:
        await engine.dispose()


def main():
    assert validate_artifact_inspection(None, "txt", b"old image") == {}
    for bad in ({**report(b"other")}, {**report(b"file"), "status": "failed"}, {**report(b"file"), "details": {"invalid": float("nan")}}):
        try:
            validate_artifact_inspection(bad, "txt", b"file")
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid inspection was accepted.")
    data = BytesIO()
    with ZipFile(data, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", b"x" * (33 * 1024 * 1024))
    try:
        validate_generated_artifact("docx", "bomb.docx", data.getvalue())
    except ValueError as exc:
        assert "inspection limits" in str(exc)
    else:
        raise AssertionError("Unbounded Office expansion was accepted.")
    asyncio.run(persistence())
    print("ARTIFACT_QUALITY_OK")


if __name__ == "__main__":
    main()
