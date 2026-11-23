"""Import Markdown into an existing knowledge base from a trusted local CLI.

Uses the configured database credentials, the named actor's existing permissions,
and the application's upload/document/task services. No login tokens are minted.
Preview first; pass --apply to persist documents and queue normal Celery work.
Run from backend/: uv run python -m scripts.import_knowledge --help
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import bindparam, text
from starlette.datastructures import Headers

from app.application.knowledge.documents.service import (
    create_knowledge_documents_from_attachments,
    dispatch_knowledge_task,
    enqueue_index_knowledge_document,
    enqueue_parse_knowledge_document,
    get_knowledge_base,
    get_knowledge_document,
    require_knowledge_base_permission,
    upload_knowledge_attachment,
)
from app.application.workspaces.service import get_workspace_for_user
from app.domain.knowledge.documents.service import (
    clean_upload_filename,
    knowledge_object_storage,
)
from app.infra.config.settings import Settings
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.knowledge import repository
from app.infra.db.session import (
    configure_database,
    get_engine,
    get_session_factory,
)
from app.schemas.knowledge import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentParseRequest,
)


def report(event, **values):
    print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


def file_hash(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


async def run(args):
    settings = Settings.from_env()
    if settings.environment == "production":
        raise ValueError("This local import script does not target production.")
    if not args.source.is_dir():
        raise ValueError("Source directory does not exist.")
    configure_database(settings)
    session = get_session_factory()
    storage = knowledge_object_storage(settings)
    try:
        async with session() as db:
            actor = await users.get_active_user_by_username(db, args.actor)
            if actor is None:
                raise ValueError("The named active actor does not exist.")
            kb = await repository.get_knowledge_base_by_id(db, args.knowledge_base_id)
            if kb is None:
                raise ValueError("Knowledge base does not exist.")
            workspace = await get_workspace_for_user(db, kb.workspace_id, actor)
            if workspace.status != "active":
                raise ValueError("Workspace is not active.")
            await require_knowledge_base_permission(db, kb, actor, {"edit"})
            existing = await repository.list_knowledge_documents(db, kb, include_staged=True)

        files = sorted(
            path for path in args.source.rglob("*")
            if path.is_file() and not path.is_symlink()
            and path.suffix.lower() in {".md", ".markdown"}
        )
        names = Counter(path.name for path in files)
        if any(count > 1 for count in names.values()):
            raise ValueError("Source contains duplicate basenames; resolve before import.")
        by_name = {}
        for document in existing:
            by_name.setdefault(document.filename, []).append(document)
        pending = []
        skipped = 0
        blocked = []
        tracked = []
        for path in files:
            try:
                clean_upload_filename(path.name)
            except HTTPException as exc:
                blocked.append(path.name)
                report("blocked_filename", filename=path.name, detail=exc.detail)
                continue
            matches = by_name.get(path.name, [])
            if not matches:
                pending.append((path, None))
                continue
            with path.open("rb") as stream:
                digest = file_hash(stream)
            for document in matches:
                with storage.open_reader(document.storage_path) as stream:
                    if file_hash(stream) == digest:
                        tracked.append(document.id)
                        if document.status in {"uploaded", "parsed"}:
                            pending.append((path, document.id))
                        else:
                            skipped += 1
                        break
            else:
                raise ValueError(f"Existing filename has different content: {path.name}")
        report(
            "plan", knowledge_base=kb.name, workspace=workspace.name,
            source_files=len(files), existing_documents=len(existing),
            skipped=skipped, blocked=len(blocked), to_process=len(pending), apply=args.apply,
        )
        if not args.apply:
            return

        semaphore = asyncio.Semaphore(4)
        imported = 0
        failures = []

        async def import_one(path, document_id):
            nonlocal imported
            async with semaphore, session() as db:
                current_kb = await get_knowledge_base(db, kb.workspace_id, kb.id)
                await require_knowledge_base_permission(db, current_kb, actor, {"edit"})
                if document_id is None:
                    with path.open("rb") as stream:
                        attachment = await upload_knowledge_attachment(
                            db, current_kb,
                            UploadFile(
                                stream, filename=path.name,
                                headers=Headers({"content-type": "text/markdown"}),
                            ), actor, settings,
                        )
                    documents = await create_knowledge_documents_from_attachments(
                        db, current_kb,
                        KnowledgeDocumentCreateRequest(
                            attachment_ids=[attachment.id], staged=False,
                        ), actor,
                    )
                    document_id = documents[0].id
                    tracked.append(document_id)
                    imported += 1
                document = await get_knowledge_document(
                    db, current_kb, document_id, include_staged=True,
                )
                if document.status == "uploaded":
                    task = await enqueue_parse_knowledge_document(
                        db, current_kb, document, actor,
                        KnowledgeDocumentParseRequest(auto_index=True),
                    )
                elif document.status == "parsed":
                    task = await enqueue_index_knowledge_document(
                        db, current_kb, document, actor,
                    )
                else:
                    return
                await dispatch_knowledge_task(task.id, settings)

        for offset in range(0, len(pending), 20):
            batch = pending[offset:offset + 20]
            results = await asyncio.gather(
                *(import_one(path, document_id) for path, document_id in batch),
                return_exceptions=True,
            )
            for (path, _), result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    detail = result.detail if isinstance(result, HTTPException) else str(result)
                    failures.append(path.name)
                    report("error", filename=path.name, detail=detail)
            if offset == 0 or (offset + 20) % 100 == 0 or offset + 20 >= len(pending):
                report("uploaded", processed=min(offset + 20, len(pending)),
                       total=len(pending), imported=imported, failures=len(failures))
            if failures:
                raise RuntimeError("Import stopped after a failed batch; completed files are retained.")
        report("upload_complete", imported=imported, skipped=skipped,
               blocked_filenames=blocked, failures=failures)
        if failures:
            raise RuntimeError("Some uploads or task submissions failed; inspect errors above.")

        if args.wait:
            statement = text(
                "SELECT status, count(*) AS count FROM knowledge_documents "
                "WHERE workspace_id=:workspace AND knowledge_base_id=:kb "
                "AND id IN :ids GROUP BY status"
            ).bindparams(bindparam("ids", expanding=True))
            while True:
                async with session() as db:
                    rows = (await db.execute(statement, {
                        "workspace": kb.workspace_id, "kb": kb.id, "ids": tracked,
                    })).mappings().all()
                statuses = {row["status"]: row["count"] for row in rows}
                report("processing", statuses=statuses, total=len(tracked))
                if sum(statuses.values()) != len(tracked):
                    raise RuntimeError("Imported documents changed while waiting.")
                if statuses.get("indexed", 0) == len(tracked):
                    break
                if all(status in {"indexed", "parse_failed", "index_failed"}
                       for status in statuses):
                    raise RuntimeError("Document processing finished with failures.")
                await asyncio.sleep(15)
    finally:
        await get_engine().dispose()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wait", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
