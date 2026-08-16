"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import tests.support  # noqa: F401  (sets required env before app imports)

from fastapi import HTTPException

from app.capabilities.llm.registry import (
    is_masked_secret,
    normalize_model_type,
    normalize_provider_credentials,
    normalize_url_credential,
    validate_status,
)
from app.capabilities.rag.retrieval import (
    MAX_PARENT_CONTEXT_CHARS,
    RankedHit,
    parent_context,
    reciprocal_rank_fusion,
)
from app.capabilities.rag.vector_store import VectorHit
from app.entities.agents import Agent
from app.entities.knowledge import KnowledgeBase
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User
from app.shareddomain.agents.permissions import (
    effective_agent_permission,
    validate_agent_permission,
)
from app.shareddomain.knowledge.orchestration import parse_task_options
from app.shareddomain.knowledge.services import (
    clean_upload_filename,
    effective_permission,
    validate_permission,
)


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError("expected HTTPException")


# ---------------------------------------------------------------- permissions


def test_effective_permission_matrix() -> None:
    knowledge_base = KnowledgeBase(
        id="kb-1",
        workspace_id="ws-1",
        created_by_user_id="owner-1",
    )
    owner = User(id="owner-1", username="owner")
    other = User(id="other-1", username="other")

    # workspace admin and owner always get edit
    assert effective_permission(knowledge_base, owner, "admin") == "edit"
    assert effective_permission(knowledge_base, owner, None) == "edit"
    assert effective_permission(knowledge_base, other, "admin") == "edit"
    # no grant, no admin -> none
    assert effective_permission(knowledge_base, other, None) == "none"
    assert effective_permission(knowledge_base, other, "member") == "none"
    # explicit grant wins for non-owner members
    grant = SimpleNamespace(permission="view")
    assert (
        effective_permission(knowledge_base, other, "member", grant=grant)
        == "view"
    )


def test_validate_permission_rejects_unknown() -> None:
    expect_http_error(lambda: validate_permission("delete"), 422)


def test_effective_agent_permission_matrix() -> None:
    agent = Agent(
        id="agent-1",
        workspace_id="ws-1",
        created_by_user_id="owner-1",
    )
    owner = User(id="owner-1", username="owner")
    member = User(id="member-1", username="member")
    grant = ResourcePermission(
        workspace_id="ws-1",
        resource_type="agent",
        resource_id="agent-1",
        user_id="member-1",
        permission="view",
    )

    assert effective_agent_permission(agent, owner, "member") == "edit"
    assert effective_agent_permission(agent, member, "admin") == "edit"
    assert effective_agent_permission(agent, member, "member") == "none"
    assert effective_agent_permission(agent, member, "member", grant) == "view"


def test_validate_agent_permission_only_accepts_view() -> None:
    validate_agent_permission("view")
    expect_http_error(lambda: validate_agent_permission("edit"), 422)


def test_knowledge_writes_recheck_locked_owner() -> None:
    from app.schemas.knowledge import KnowledgeBaseUpdateRequest
    from app.shareddomain.knowledge import kb as knowledge_kb

    stale = KnowledgeBase(
        id="kb-1",
        workspace_id="ws-1",
        name="Docs",
        created_by_user_id="actor-1",
    )
    locked = KnowledgeBase(
        id="kb-1",
        workspace_id="ws-1",
        name="Docs",
        created_by_user_id="new-owner",
    )
    actor = User(id="actor-1", username="actor")

    async def lock_knowledge_base(db, knowledge_base):
        return locked

    async def get_user_grant(
        db,
        workspace_id,
        resource_type,
        resource_id,
        user_id,
    ):
        return None

    original_lock = knowledge_kb.knowledge_base_repository.lock_knowledge_base
    original_grant = knowledge_kb.permission_repository.get_user_grant
    knowledge_kb.knowledge_base_repository.lock_knowledge_base = lock_knowledge_base
    knowledge_kb.permission_repository.get_user_grant = get_user_grant

    async def assert_denied() -> None:
        for operation in (
            knowledge_kb.update_knowledge_base(
                SimpleNamespace(),
                stale,
                KnowledgeBaseUpdateRequest(description="stale write"),
                actor,
                None,
            ),
            knowledge_kb.transfer_knowledge_base_owner(
                SimpleNamespace(),
                stale,
                "target-1",
                actor,
                None,
            ),
        ):
            try:
                await operation
            except HTTPException as exc:
                assert exc.status_code == 403, exc.status_code
                continue
            raise AssertionError("stale knowledge owner was allowed to write")

    try:
        asyncio.run(assert_denied())
    finally:
        knowledge_kb.knowledge_base_repository.lock_knowledge_base = original_lock
        knowledge_kb.permission_repository.get_user_grant = original_grant


def test_clean_upload_filename_sanitizes_path_and_classification() -> None:
    assert clean_upload_filename("../../etc/passwd") == "passwd"
    expect_http_error(lambda: clean_upload_filename("报告-机密.docx"), 422)
    expect_http_error(lambda: clean_upload_filename("   "), 422)
    assert clean_upload_filename("photo.png") == "photo.png"


# ---------------------------------------------------------------- parse options


def payload_with(**fields):
    return SimpleNamespace(model_dump=lambda: fields)


def test_parse_task_options_validates_boundaries() -> None:
    # overlap must be smaller than size
    expect_http_error(
        lambda: parse_task_options(
            payload_with(chunk_size=100, chunk_overlap=100)
        ),
        422,
    )
    # separator must be in the supported set
    expect_http_error(
        lambda: parse_task_options(payload_with(split_separator="|")),
        422,
    )
    # cleaning rules are whitelisted and deduplicated
    options = parse_task_options(
        payload_with(cleaning_rules=["trim_lines", "trim_lines"])
    )
    assert options["cleaning_rules"] == ["trim_lines"]
    expect_http_error(
        lambda: parse_task_options(payload_with(cleaning_rules=["drop_table"])),
        422,
    )


def test_markdown_tables_split_only_between_rows_and_repeat_headers() -> None:
    from app.capabilities.embedding.pipeline import split_text

    header = "| Name | Description |"
    alignment = "| --- | --- |"
    rows = [
        "| alpha | first value |",
        "| beta | second value |",
        "| gamma | third value |",
    ]
    table = "\n".join([header, alignment, *rows])

    chunks = split_text(table, chunk_size=55, overlap=20, separator=".")

    assert len(chunks) == 3
    assert all(chunk.splitlines()[:2] == [header, alignment] for chunk in chunks)
    assert all(row in chunk for row, chunk in zip(rows, chunks, strict=True))
    assert all(row not in "\n".join(chunks[index + 1 :]) for index, row in enumerate(rows))


def test_markdown_table_keeps_single_overlong_row_intact() -> None:
    from app.capabilities.embedding.pipeline import split_text

    long_cell = "word " * 30
    row = f"| 1 | {long_cell.strip()} |"
    table = f"| ID | Notes |\n| --- | --- |\n{row}"

    chunks = split_text(table, chunk_size=40, overlap=0)

    assert len(chunks) == 1
    assert row in chunks[0]


def test_markdown_table_rules_apply_to_parent_and_child_chunks() -> None:
    from app.capabilities.embedding.pipeline import (
        build_hierarchical_chunks,
        split_parent_chunks,
    )

    header = "| Key | Value |"
    alignment = "| --- | --- |"
    rows = [f"| {index} | value-{index} |" for index in range(8)]
    table = "\n".join([header, alignment, *rows])

    parents = split_parent_chunks(table, max_size=90)
    drafts = build_hierarchical_chunks(table, chunk_size=45, overlap=0, separator=".")

    assert all(parent.content.splitlines()[:2] == [header, alignment] for parent in parents)
    assert all(child.content.splitlines()[:2] == [header, alignment] for child in drafts.children)
    assert all(
        drafts.parents[child.parent_index].content[child.start_offset : child.end_offset]
        == child.content
        or child.content.endswith(
            drafts.parents[child.parent_index].content[child.start_offset : child.end_offset]
        )
        for child in drafts.children
    )


def test_docx_images_without_alt_text_do_not_add_placeholder_content() -> None:
    from io import BytesIO
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from app.capabilities.embedding import pipeline

    images = [
        SimpleNamespace(
            content_type="image/png",
            alt_text=None,
            open=lambda: BytesIO(b"image-without-alt"),
        ),
        SimpleNamespace(
            content_type="image/png",
            alt_text="Network diagram",
            open=lambda: BytesIO(b"image-with-alt"),
        ),
    ]

    def fake_convert_to_html(_stream, *, convert_image):
        return SimpleNamespace(value=[convert_image(image) for image in images])

    def fake_convert_string(_converter, image_attributes):
        markdown = "\n\n".join(
            f"![{attributes['alt']}](nexaflow-asset://{index})"
            for index, attributes in enumerate(image_attributes)
        )
        return SimpleNamespace(text_content=f"Before\n\n{markdown}\n\nAfter")

    with TemporaryDirectory() as directory:
        path = Path(directory) / "images.docx"
        path.touch()
        with (
            patch.object(pipeline, "pre_process_docx", lambda stream: stream),
            patch.object(pipeline.mammoth.images, "img_element", lambda callback: callback),
            patch.object(pipeline.mammoth, "convert_to_html", fake_convert_to_html),
            patch.object(pipeline.HtmlConverter, "convert_string", fake_convert_string),
        ):
            text, assets = pipeline.extract_document(
                path.name,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                path,
            )

    drafts = pipeline.build_flat_chunks(
        pipeline.split_text(text, chunk_size=1000, overlap=0)
    )
    assert [asset.alt_text for asset in assets] == ["", "Network diagram"]
    assert len(drafts.children) == 1
    assert " ".join(drafts.children[0].content.split()) == (
        "Before Network diagram After"
    )
    assert drafts.children[0].asset_indexes == [0, 1]


def test_docx_image_mime_cannot_shape_asset_paths() -> None:
    from io import BytesIO
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from app.capabilities.embedding import pipeline

    image = SimpleNamespace(
        content_type="image/../../../../other-document/asset",
        alt_text="Diagram",
        open=lambda: BytesIO(b"image"),
    )

    def fake_convert_to_html(_stream, *, convert_image):
        return SimpleNamespace(value=convert_image(image))

    with TemporaryDirectory() as directory:
        path = Path(directory) / "image.docx"
        path.touch()
        with (
            patch.object(pipeline, "pre_process_docx", lambda stream: stream),
            patch.object(pipeline.mammoth.images, "img_element", lambda callback: callback),
            patch.object(pipeline.mammoth, "convert_to_html", fake_convert_to_html),
            patch.object(
                pipeline.HtmlConverter,
                "convert_string",
                return_value=SimpleNamespace(text_content="Diagram"),
            ),
        ):
            _text, assets = pipeline.extract_document(
                path.name,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                path,
            )

    assert assets[0].filename.endswith(".bin")
    assert "/" not in assets[0].filename
    assert assets[0].content_type == "application/octet-stream"


def test_archive_limits_run_before_document_conversion() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    from zipfile import ZIP_DEFLATED, ZipFile

    from app.capabilities.embedding import pipeline

    with TemporaryDirectory() as directory:
        path = Path(directory) / "expanded.zip"
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("large.txt", b"x" * 9)

        with (
            patch.object(
                pipeline,
                "MAX_ARCHIVE_UNCOMPRESSED_BYTES",
                8,
                create=True,
            ),
            patch.object(
                pipeline.MARKITDOWN,
                "convert_local",
                return_value=SimpleNamespace(text_content="converted"),
            ),
        ):
            try:
                pipeline.extract_document(path.name, "application/zip", path)
            except pipeline.KnowledgePipelineError as exc:
                assert "expanded data" in str(exc)
            else:
                raise AssertionError("oversized archive was converted")


def test_supported_document_formats_are_accepted() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from app.capabilities.embedding import pipeline

    expected_extensions = {
        ".docx",
        ".md",
        ".markdown",
        ".pdf",
        ".txt",
        ".pptx",
        ".xlsx",
        ".xls",
        ".html",
        ".csv",
        ".json",
        ".xml",
        ".ipynb",
        ".epub",
        ".zip",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }
    assert expected_extensions == pipeline.SUPPORTED_DOCUMENT_EXTENSIONS

    def fake_convert_local(*_args, **_kwargs):
        return SimpleNamespace(text_content="converted")

    with TemporaryDirectory() as directory:
        for extension in expected_extensions - {
            ".docx",
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        }:
            path = Path(directory) / f"document{extension}"
            path.write_bytes(b"content")
            with patch.object(pipeline.MARKITDOWN, "convert_local", fake_convert_local):
                text, assets = pipeline.extract_document(
                    path.name,
                    "application/octet-stream",
                    path,
                )
            assert text == "converted"
            assert assets == []


def test_pdf_documents_use_pymupdf_markdown_with_ocr() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from app.capabilities.embedding import pipeline

    with TemporaryDirectory() as directory:
        path = Path(directory) / "通知.pdf"
        path.write_bytes(b"pdf")
        with (
            patch.object(
                pipeline.MARKITDOWN,
                "convert_local",
                side_effect=AssertionError("PDF must not use MarkItDown"),
            ),
            patch.object(
                pipeline.pymupdf4llm,
                "to_markdown",
                return_value="提 高 思想 认识， 压 实 防 灾 责 任。",
            ) as convert_pdf,
        ):
            text, assets = pipeline.extract_document(
                path.name,
                "application/pdf",
                path,
            )

    assert text == "# 通知\n\n提高思想认识，压实防灾责任。"
    assert assets == []
    convert_pdf.assert_called_once_with(
        path,
        use_ocr=True,
        force_ocr=False,
        ocr_language="chi_sim+eng",
        ocr_dpi=300,
        write_images=False,
    )


def test_image_documents_use_pymupdf_ocr() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from app.capabilities.embedding import pipeline

    with TemporaryDirectory() as directory:
        path = Path(directory) / "通知.png"
        path.write_bytes(b"png")
        with (
            patch.object(
                pipeline.MARKITDOWN,
                "convert_local",
                side_effect=AssertionError("Images must not use MarkItDown"),
            ),
            patch.object(
                pipeline.pymupdf4llm,
                "to_markdown",
                return_value="识 别 文 本",
            ) as convert_image,
        ):
            text, assets = pipeline.extract_document(
                path.name,
                "image/png",
                path,
            )

    assert text == "# 通知\n\n识别文本"
    assert assets == []
    convert_image.assert_called_once_with(
        path,
        use_ocr=True,
        force_ocr=True,
        ocr_language="chi_sim+eng",
        ocr_dpi=300,
        write_images=False,
    )


def test_webp_documents_are_normalized_for_pymupdf_ocr() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import pymupdf
    from PIL import Image

    from app.capabilities.embedding import pipeline

    with TemporaryDirectory() as directory:
        path = Path(directory) / "通知.webp"
        Image.new("RGB", (10, 10), "white").save(path, format="WEBP")
        with patch.object(
            pipeline.pymupdf4llm,
            "to_markdown",
            return_value="识 别 文 本",
        ) as convert_image:
            text, assets = pipeline.extract_document(
                path.name,
                "image/webp",
                path,
            )

    assert text == "# 通知\n\n识别文本"
    assert assets == []
    source = convert_image.call_args.args[0]
    assert isinstance(source, pymupdf.Document)
    assert convert_image.call_args.kwargs == {
        "use_ocr": True,
        "force_ocr": True,
        "ocr_language": "chi_sim+eng",
        "ocr_dpi": 300,
        "write_images": False,
    }


# ---------------------------------------------------------------- retrieval math


def test_reciprocal_rank_fusion_merges_and_ranks() -> None:
    fused = reciprocal_rank_fusion(
        [VectorHit(chunk_id="vector-only", distance=0.1)],
        ["vector-only", "keyword-only"],
    )
    assert [hit.chunk_id for hit in fused] == ["vector-only", "keyword-only"]
    # a chunk present in both rankings ranks first and keeps its distance
    fused_shared = reciprocal_rank_fusion(
        [VectorHit(chunk_id="shared", distance=0.2)],
        ["shared"],
    )
    assert fused_shared[0].chunk_id == "shared"
    assert fused_shared[0].distance == 0.2


def test_reciprocal_rank_fusion_reports_named_rankings_deterministically() -> None:
    ranked = reciprocal_rank_fusion(
        [
            VectorHit(chunk_id="a", distance=0.2),
            VectorHit(chunk_id="b", distance=0.3),
        ],
        ["b", "c"],
        ["c"],
    )

    assert ranked == [
        RankedHit(
            chunk_id="b",
            distance=0.3,
            rrf_score=1 / 62 + 1 / 61,
            vector_rank=2,
            keyword_rank=1,
            reference_rank=None,
            sources=("vector", "keywords"),
        ),
        RankedHit(
            chunk_id="c",
            distance=None,
            rrf_score=1 / 62 + 1 / 61,
            vector_rank=None,
            keyword_rank=2,
            reference_rank=1,
            sources=("keywords", "reference"),
        ),
        RankedHit(
            chunk_id="a",
            distance=0.2,
            rrf_score=1 / 61,
            vector_rank=1,
            keyword_rank=None,
            reference_rank=None,
            sources=("vector",),
        ),
    ]
    try:
        ranked[0].rrf_score = 0  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("Ranked hits must be immutable.")


def test_keyword_repository_uses_scoped_bm25_query() -> None:
    from app.infrastructure.repositories import knowledge as knowledge_repository

    class FakeResult:
        def scalars(self):
            return ["chunk-2", "chunk-1"]

    class FakeDatabase:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def execute(self, statement, parameters):
            sql = str(statement)
            assert "chunk.search_text ||| CAST(:query AS text)" in sql
            assert "pdb.score(chunk.id) DESC" in sql
            assert "ts_rank" not in sql
            assert parameters == {
                "workspace_id": "ws-1",
                "knowledge_base_id": "kb-1",
                "query": "数据库 回滚",
                "candidate_limit": 10,
                "document_ids": ["doc-1", "doc-2"],
            }
            return FakeResult()

    result = asyncio.run(
        knowledge_repository.query_keyword_chunk_ids(
            FakeDatabase(),  # type: ignore[arg-type]
            KnowledgeBase(id="kb-1", workspace_id="ws-1"),
            "数据库 回滚",
            10,
            {"doc-2", "doc-1"},
        )
    )
    assert result == ["chunk-2", "chunk-1"]


def test_detailed_knowledge_query_contract_defaults() -> None:
    from app.schemas.knowledge import (
        KnowledgeQueryHitResponse,
        KnowledgeQueryInspectResponse,
        KnowledgeQueryRequest,
        KnowledgeRetrievalTraceResponse,
    )

    request = KnowledgeQueryRequest(query="  private customer question  ")
    assert request.query == "private customer question"
    assert request.include_references is False
    assert KnowledgeQueryRequest(query="question", similarity=0.75).similarity == 0.75
    try:
        KnowledgeQueryRequest(query="   ")
    except ValueError:
        pass
    else:
        raise AssertionError("Whitespace-only retrieval queries must be rejected.")
    try:
        KnowledgeQueryRequest(query="question", similarity=1.01)
    except ValueError:
        pass
    else:
        raise AssertionError("Retrieval similarity must stay within 0..1.")

    hit = KnowledgeQueryHitResponse(
        chunk_id="chunk-1",
        document_id="document-1",
        document_filename="guide.md",
        chunk_index=0,
        content="answer",
    )
    assert hit.model_dump() == {
        "chunk_id": "chunk-1",
        "document_id": "document-1",
        "document_filename": "guide.md",
        "parent_id": None,
        "parent_title": None,
        "parent_index": None,
        "chunk_index": 0,
        "content": "answer",
        "distance": None,
        "similarity": None,
        "kind": "document",
        "question": None,
        "source": None,
        "sources": [],
        "reference_hops": 0,
        "rerank_score": None,
    }

    trace = KnowledgeRetrievalTraceResponse(
        trace_id="trace-1",
        search_mode="blend",
        limit=5,
        min_similarity=None,
        max_distance=None,
        vector_candidates=2,
        keyword_candidates=1,
        reference_candidates=0,
        fused_candidates=2,
        rerank_status="not_configured",
        returned_hits=1,
        duration_ms=1.25,
        stage_duration_ms={"retrieve": 0.5, "assemble": 0.75},
    )
    dumped_trace = trace.model_dump()
    assert "query" not in dumped_trace
    assert all("hash" not in field for field in dumped_trace)
    assert KnowledgeQueryInspectResponse(hits=[hit], trace=trace).trace is trace


def test_retrieval_evaluation_metrics_are_deterministic() -> None:
    from app.capabilities.rag.evaluation import (
        aggregate_retrieval_metrics,
        retrieval_case_metrics,
    )

    metrics = retrieval_case_metrics(
        returned_document_ids=["doc-b", "doc-x", "doc-a"],
        expected_document_ids={"doc-a", "doc-b"},
        limit=3,
    )
    assert metrics.hit_at_k == 1
    assert metrics.recall_at_k == 1.0
    assert metrics.reciprocal_rank == 1.0
    assert abs(metrics.ndcg_at_k - 0.9197) < 1e-4

    later_hit = retrieval_case_metrics(["doc-x", "doc-a"], {"doc-a"}, 2)
    assert later_hit.reciprocal_rank == 0.5
    missed_expected = retrieval_case_metrics(["doc-a"], {"doc-a", "doc-b"}, 3)
    assert missed_expected.ndcg_at_k < 1.0
    aggregate = aggregate_retrieval_metrics(
        [metrics, later_hit],
        [100.0, 300.0],
    )
    assert aggregate.count == 2
    assert aggregate.mean_hit_at_k == 1.0
    assert aggregate.mean_recall_at_k == 1.0
    assert aggregate.mean_reciprocal_rank == 0.75
    assert aggregate.p50_latency_ms == 200.0
    assert aggregate.p95_latency_ms == 290.0
    empty = aggregate_retrieval_metrics([], [])
    assert empty.count == 0
    assert empty.p95_latency_ms == 0.0


def test_evaluation_mutations_lock_before_validation_and_require_lease() -> None:
    from app.application import knowledge_evaluation as evaluation_application
    from app.entities.knowledge import KnowledgeTask
    from app.ports.parsing import KnowledgePipelineError
    from app.schemas.knowledge import KnowledgeEvaluationRunRequest
    from app.shareddomain.knowledge import evaluation as evaluation_service

    assert evaluation_application._evaluation_run_request(
        {"case_ids": ["case-1"], "similarity": 0.4}
    ).similarity == 0.8
    assert evaluation_application._evaluation_run_request(
        {
            "case_ids": ["case-1"],
            "similarity": 0.4,
            "similarity_semantics": evaluation_service.EVALUATION_SIMILARITY_SEMANTICS,
        }
    ).similarity == 0.4

    knowledge_base = KnowledgeBase(
        id="kb-1",
        workspace_id="ws-1",
        status="active",
    )
    actor = User(id="user-1", username="user")
    events: list[str] = []
    state = {
        "locked": knowledge_base,
        "open_task": None,
        "deleted": True,
        "cases": [SimpleNamespace(id="case-1")],
        "documents": [SimpleNamespace(id="doc-1")],
        "evaluation_task": KnowledgeTask(
            id="task-1",
            workspace_id="ws-1",
            knowledge_base_id="kb-1",
            task_type="evaluate",
            status="succeeded",
        ),
        "evaluation_task_deleted": True,
        "task_options": None,
    }

    class FakeDb:
        async def commit(self) -> None:
            events.append("commit")

    async def lock_knowledge_base(_db, value):
        events.append("lock")
        return state["locked"]

    async def get_open_task(*_args):
        events.append("open-task")
        return state["open_task"]

    async def delete_case(*_args):
        events.append("delete")
        return state["deleted"]

    async def list_cases(*_args):
        events.append("cases")
        return state["cases"]

    async def list_expectations(*_args):
        events.append("expectations")
        return [SimpleNamespace(document_id="doc-1")]

    async def list_documents(*_args):
        events.append("documents")
        return state["documents"]

    async def create_task(*_args):
        events.append("task")
        state["task_options"] = _args[-1]
        return SimpleNamespace(id="task-1")

    async def lock_evaluation_task(*_args):
        events.append("lock-run")
        return state["evaluation_task"]

    async def delete_evaluation_task(*_args):
        events.append("delete-run")
        return state["evaluation_task_deleted"]

    originals = (
        evaluation_service.knowledge_repository.lock_knowledge_base,
        evaluation_service.knowledge_repository.get_open_knowledge_task,
        evaluation_service.evaluation_repository.delete_case,
        evaluation_service.evaluation_repository.list_cases_by_ids,
        evaluation_service.evaluation_repository.list_expectations_for_cases,
        evaluation_service.knowledge_repository.list_active_documents_by_ids,
        evaluation_service.create_knowledge_task,
        evaluation_service.evaluation_repository.lock_evaluation_task,
        evaluation_service.evaluation_repository.delete_evaluation_task,
        evaluation_service.record_audit_log,
    )
    evaluation_service.knowledge_repository.lock_knowledge_base = lock_knowledge_base
    evaluation_service.knowledge_repository.get_open_knowledge_task = get_open_task
    evaluation_service.evaluation_repository.delete_case = delete_case
    evaluation_service.evaluation_repository.list_cases_by_ids = list_cases
    evaluation_service.evaluation_repository.list_expectations_for_cases = (
        list_expectations
    )
    evaluation_service.knowledge_repository.list_active_documents_by_ids = (
        list_documents
    )
    evaluation_service.create_knowledge_task = create_task
    evaluation_service.evaluation_repository.lock_evaluation_task = lock_evaluation_task
    evaluation_service.evaluation_repository.delete_evaluation_task = (
        delete_evaluation_task
    )
    evaluation_service.record_audit_log = lambda *_args, **_kwargs: None
    try:
        async def expect_status(coroutine, expected_status: int) -> None:
            try:
                await coroutine
            except HTTPException as exc:
                assert exc.status_code == expected_status, exc.status_code
            else:
                raise AssertionError("expected HTTPException")

        asyncio.run(
            evaluation_service.delete_evaluation_case(
                FakeDb(),
                knowledge_base,
                "case-1",
                actor,
            )
        )
        assert events[:3] == ["lock", "open-task", "delete"]

        events.clear()
        asyncio.run(
            evaluation_service.delete_evaluation_run(
                FakeDb(), knowledge_base, "task-1", actor
            )
        )
        assert events == ["lock", "lock-run", "delete-run", "commit"]

        events.clear()
        state["evaluation_task"] = KnowledgeTask(
            id="task-1",
            workspace_id="ws-1",
            knowledge_base_id="kb-1",
            task_type="evaluate",
            status="running",
        )
        asyncio.run(
            expect_status(
                evaluation_service.delete_evaluation_run(
                    FakeDb(), knowledge_base, "task-1", actor
                ),
                409,
            )
        )
        assert events == ["lock", "lock-run"]
        state["evaluation_task"] = None
        asyncio.run(
            expect_status(
                evaluation_service.delete_evaluation_run(
                    FakeDb(), knowledge_base, "task-1", actor
                ),
                404,
            )
        )
        state["evaluation_task"] = KnowledgeTask(
            id="task-1",
            workspace_id="ws-1",
            knowledge_base_id="kb-1",
            task_type="evaluate",
            status="succeeded",
        )

        events.clear()
        asyncio.run(
            evaluation_service.enqueue_evaluation_run(
                FakeDb(),
                knowledge_base,
                KnowledgeEvaluationRunRequest(case_ids=["case-1"]),
                actor,
            )
        )
        assert events[:4] == ["lock", "cases", "expectations", "documents"]
        assert events[-1] == "task"
        assert state["task_options"]["similarity_semantics"] == (
            evaluation_service.EVALUATION_SIMILARITY_SEMANTICS
        )

        state["locked"] = None
        asyncio.run(
            expect_status(
                evaluation_service.delete_evaluation_case(
                    FakeDb(), knowledge_base, "case-1", actor
                ),
                404,
            )
        )
        state["locked"] = knowledge_base
        state["open_task"] = object()
        asyncio.run(
            expect_status(
                evaluation_service.delete_evaluation_case(
                    FakeDb(), knowledge_base, "case-1", actor
                ),
                409,
            )
        )
        state["open_task"] = None
        state["deleted"] = False
        asyncio.run(
            expect_status(
                evaluation_service.delete_evaluation_case(
                    FakeDb(), knowledge_base, "case-1", actor
                ),
                404,
            )
        )
        state["deleted"] = True

        state["locked"] = None
        asyncio.run(
            expect_status(
                evaluation_service.enqueue_evaluation_run(
                    FakeDb(),
                    knowledge_base,
                    KnowledgeEvaluationRunRequest(case_ids=["case-1"]),
                    actor,
                ),
                404,
            )
        )
        state["locked"] = knowledge_base
        state["cases"] = []
        asyncio.run(
            expect_status(
                evaluation_service.enqueue_evaluation_run(
                    FakeDb(),
                    knowledge_base,
                    KnowledgeEvaluationRunRequest(case_ids=["case-1"]),
                    actor,
                ),
                404,
            )
        )
        state["cases"] = [SimpleNamespace(id="case-1")]
        state["documents"] = []
        asyncio.run(
            expect_status(
                evaluation_service.enqueue_evaluation_run(
                    FakeDb(),
                    knowledge_base,
                    KnowledgeEvaluationRunRequest(case_ids=["case-1"]),
                    actor,
                ),
                422,
            )
        )
    finally:
        (
            evaluation_service.knowledge_repository.lock_knowledge_base,
            evaluation_service.knowledge_repository.get_open_knowledge_task,
            evaluation_service.evaluation_repository.delete_case,
            evaluation_service.evaluation_repository.list_cases_by_ids,
            evaluation_service.evaluation_repository.list_expectations_for_cases,
            evaluation_service.knowledge_repository.list_active_documents_by_ids,
            evaluation_service.create_knowledge_task,
            evaluation_service.evaluation_repository.lock_evaluation_task,
            evaluation_service.evaluation_repository.delete_evaluation_task,
            evaluation_service.record_audit_log,
        ) = originals

    async def reject_stale_worker(*_args):
        return False

    original_progress_update = (
        evaluation_application.knowledge_repository.update_owned_knowledge_task_progress
    )
    evaluation_application.knowledge_repository.update_owned_knowledge_task_progress = (
        reject_stale_worker
    )
    try:
        try:
            asyncio.run(
                evaluation_application._persist_owned_progress(
                    FakeDb(),
                    KnowledgeTask(
                        id="task-1",
                        worker_task_id="stale-worker",
                    ),
                )
            )
        except KnowledgePipelineError:
            pass
        else:
            raise AssertionError("stale evaluation worker retained its lease")
    finally:
        evaluation_application.knowledge_repository.update_owned_knowledge_task_progress = (
            original_progress_update
        )


def test_evaluation_case_service_and_repository_edges() -> None:
    from app.entities.knowledge import (
        KnowledgeEvaluationCase,
        KnowledgeEvaluationExpectation,
        KnowledgeTask,
    )
    from app.infrastructure.repositories import (
        knowledge_evaluation as evaluation_repository,
    )
    from app.schemas.knowledge import KnowledgeEvaluationCaseCreateRequest
    from app.shareddomain.knowledge import evaluation as evaluation_service

    knowledge_base = KnowledgeBase(id="kb-1", workspace_id="ws-1")
    actor = User(id="user-1", username="user")
    existing_case = KnowledgeEvaluationCase(
        id="case-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        question="Existing question",
        created_by_user_id=actor.id,
    )
    expectation = KnowledgeEvaluationExpectation(
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        case_id=existing_case.id,
        document_id="doc-1",
    )
    task = KnowledgeTask(
        id="task-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        task_type="evaluate",
        created_by_user_id=actor.id,
    )
    state = {
        "knowledge_base": knowledge_base,
        "documents": [SimpleNamespace(id="doc-1")],
        "task": task,
    }
    created: list[tuple[KnowledgeEvaluationCase, list]] = []

    class FakeDb:
        async def commit(self) -> None:
            return None

    async def list_cases(*_args, **_kwargs):
        return [existing_case]

    async def list_expectations(*_args, **_kwargs):
        return [expectation]

    async def list_documents(*_args, **_kwargs):
        return state["documents"]

    async def lock_knowledge_base(*_args, **_kwargs):
        return state["knowledge_base"]

    async def create_case(_db, case, expectations):
        created.append((case, expectations))
        return case

    async def get_task(*_args):
        return state["task"]

    async def list_tasks(*_args, **_kwargs):
        return [task]

    originals = (
        evaluation_service.evaluation_repository.list_cases,
        evaluation_service.evaluation_repository.list_expectations_for_cases,
        evaluation_service.knowledge_repository.list_active_documents_by_ids,
        evaluation_service.knowledge_repository.lock_knowledge_base,
        evaluation_service.evaluation_repository.create_case,
        evaluation_service.knowledge_repository.get_knowledge_task_by_id,
        evaluation_service.evaluation_repository.list_evaluation_tasks,
        evaluation_service.record_audit_log,
    )
    evaluation_service.evaluation_repository.list_cases = list_cases
    evaluation_service.evaluation_repository.list_expectations_for_cases = (
        list_expectations
    )
    evaluation_service.knowledge_repository.list_active_documents_by_ids = (
        list_documents
    )
    evaluation_service.knowledge_repository.lock_knowledge_base = lock_knowledge_base
    evaluation_service.evaluation_repository.create_case = create_case
    evaluation_service.knowledge_repository.get_knowledge_task_by_id = get_task
    evaluation_service.evaluation_repository.list_evaluation_tasks = list_tasks
    evaluation_service.record_audit_log = lambda *_args, **_kwargs: None
    try:
        listed = asyncio.run(
            evaluation_service.list_evaluation_cases(
                FakeDb(), knowledge_base, limit=10, offset=2
            )
        )
        assert listed[0].expected_document_ids == ["doc-1"]

        response = asyncio.run(
            evaluation_service.create_evaluation_case(
                FakeDb(),
                knowledge_base,
                KnowledgeEvaluationCaseCreateRequest(
                    question="  New question  ",
                    expected_document_ids=["doc-1", "doc-1"],
                ),
                actor,
            )
        )
        assert response.question == "New question"
        assert response.expected_document_ids == ["doc-1"]
        assert len(created[0][1]) == 1

        async def create_invalid(payload, expected_status: int) -> None:
            try:
                await evaluation_service.create_evaluation_case(
                    FakeDb(), knowledge_base, payload, actor
                )
            except HTTPException as exc:
                assert exc.status_code == expected_status
            else:
                raise AssertionError("invalid evaluation case was accepted")

        asyncio.run(
            create_invalid(
                KnowledgeEvaluationCaseCreateRequest(
                    question=" ",
                    expected_document_ids=["doc-1"],
                ),
                422,
            )
        )
        state["documents"] = []
        asyncio.run(
            create_invalid(
                KnowledgeEvaluationCaseCreateRequest(
                    question="question",
                    expected_document_ids=["doc-1"],
                ),
                404,
            )
        )
        state["documents"] = [SimpleNamespace(id="doc-1")]
        state["knowledge_base"] = KnowledgeBase(
            id="kb-1",
            workspace_id="ws-1",
            status="archived",
        )
        asyncio.run(
            create_invalid(
                KnowledgeEvaluationCaseCreateRequest(
                    question="question",
                    expected_document_ids=["doc-1"],
                ),
                403,
            )
        )
        state["knowledge_base"] = knowledge_base

        assert asyncio.run(
            evaluation_service.get_evaluation_task(
                FakeDb(), knowledge_base, task.id
            )
        ) is task
        assert asyncio.run(
            evaluation_service.list_evaluation_runs(
                FakeDb(), knowledge_base, limit=1
            )
        )[0].id == task.id
        state["task"] = KnowledgeTask(
            id="task-2",
            workspace_id="ws-1",
            knowledge_base_id="kb-1",
            task_type="parse",
        )

        async def get_invalid_task() -> None:
            try:
                await evaluation_service.get_evaluation_task(
                    FakeDb(), knowledge_base, "task-2"
                )
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("non-evaluation task was accepted")

        asyncio.run(get_invalid_task())
    finally:
        (
            evaluation_service.evaluation_repository.list_cases,
            evaluation_service.evaluation_repository.list_expectations_for_cases,
            evaluation_service.knowledge_repository.list_active_documents_by_ids,
            evaluation_service.knowledge_repository.lock_knowledge_base,
            evaluation_service.evaluation_repository.create_case,
            evaluation_service.knowledge_repository.get_knowledge_task_by_id,
            evaluation_service.evaluation_repository.list_evaluation_tasks,
            evaluation_service.record_audit_log,
        ) = originals

    assert asyncio.run(
        evaluation_repository.list_cases_by_ids(FakeDb(), knowledge_base, set())
    ) == []
    assert asyncio.run(
        evaluation_repository.list_expectations_for_cases(
            FakeDb(), knowledge_base, set()
        )
    ) == []


def test_evaluation_result_upsert_recovers_concurrent_insert() -> None:
    from sqlalchemy.exc import IntegrityError

    from app.entities.knowledge import KnowledgeEvaluationResult
    from app.infrastructure.repositories import (
        knowledge_evaluation as evaluation_repository,
    )
    from app.shareddomain.knowledge.models import (
        KnowledgeEvaluationResult as KnowledgeEvaluationResultORM,
    )

    result = KnowledgeEvaluationResult(
        id="loser-result",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        task_id="task-1",
        case_id="case-1",
        returned_document_ids=["doc-1"],
        returned_chunk_ids=["chunk-1"],
        hit_at_k=1,
    )
    winner = KnowledgeEvaluationResultORM(
        id="winner-result",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        task_id="task-1",
        case_id="case-1",
        returned_document_ids=[],
        returned_chunk_ids=[],
        hit_at_k=0,
        recall_at_k=0.0,
        reciprocal_rank=0.0,
        ndcg_at_k=0.0,
        latency_ms=0.0,
        trace={},
        error="first attempt failed",
        created_at=result.created_at,
    )

    class NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeDb:
        scalar_calls = 0
        flush_calls = 0

        async def scalar(self, _statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else winner

        def begin_nested(self):
            return NestedTransaction()

        def add(self, _row) -> None:
            return None

        async def flush(self) -> None:
            self.flush_calls += 1
            if self.flush_calls == 1:
                raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    db = FakeDb()
    persisted = asyncio.run(evaluation_repository.upsert_result(db, result))

    assert db.scalar_calls == 2
    assert persisted.id == "winner-result"
    assert persisted.error is None
    assert persisted.hit_at_k == 1


def test_evaluation_routes_delegate_to_application() -> None:
    from app.api.v1.endpoints import knowledge_evaluation as evaluation_api
    from app.schemas.knowledge import (
        KnowledgeEvaluationCaseCreateRequest,
        KnowledgeEvaluationRunRequest,
    )

    knowledge_base = KnowledgeBase(id="kb-1", workspace_id="ws-1")
    context = SimpleNamespace(
        workspace=SimpleNamespace(id="ws-1"),
        user=User(id="user-1", username="user"),
        membership_role="member",
    )
    db = object()
    settings = object()
    calls: list[tuple] = []

    async def get_knowledge_base(*args):
        calls.append(("get", args[1], args[2]))
        return knowledge_base

    async def require_permission(*args):
        calls.append(("permission", args[-1]))

    async def list_cases(*_args, **kwargs):
        calls.append(("list-cases", kwargs))
        return ["case"]

    async def create_case(*_args):
        return "created"

    async def delete_case(*_args):
        calls.append(("delete",))

    async def delete_run(*_args):
        calls.append(("delete-run",))

    async def list_runs(*_args, **kwargs):
        calls.append(("list-runs", kwargs))
        return ["run"]

    async def enqueue_run(*_args):
        return SimpleNamespace(id="task-1")

    async def dispatch(*args):
        calls.append(("dispatch", args[0]))

    async def get_run(*_args):
        return "run"

    async def get_summary(*_args):
        return "summary"

    async def get_latest(*_args):
        return "latest"

    originals = (
        evaluation_api.get_knowledge_base,
        evaluation_api.require_knowledge_base_permission,
        evaluation_api.list_evaluation_cases,
        evaluation_api.create_evaluation_case,
        evaluation_api.delete_evaluation_case,
        evaluation_api.delete_evaluation_run,
        evaluation_api.list_evaluation_runs,
        evaluation_api.enqueue_evaluation_run,
        evaluation_api.dispatch_knowledge_task,
        evaluation_api.get_evaluation_run,
        evaluation_api.get_evaluation_summary,
        evaluation_api.get_latest_evaluation_summary,
    )
    (
        evaluation_api.get_knowledge_base,
        evaluation_api.require_knowledge_base_permission,
        evaluation_api.list_evaluation_cases,
        evaluation_api.create_evaluation_case,
        evaluation_api.delete_evaluation_case,
        evaluation_api.delete_evaluation_run,
        evaluation_api.list_evaluation_runs,
        evaluation_api.enqueue_evaluation_run,
        evaluation_api.dispatch_knowledge_task,
        evaluation_api.get_evaluation_run,
        evaluation_api.get_evaluation_summary,
        evaluation_api.get_latest_evaluation_summary,
    ) = (
        get_knowledge_base,
        require_permission,
        list_cases,
        create_case,
        delete_case,
        delete_run,
        list_runs,
        enqueue_run,
        dispatch,
        get_run,
        get_summary,
        get_latest,
    )
    try:
        async def run() -> None:
            assert await evaluation_api.list_workspace_evaluation_cases(
                "kb-1", context, db, 10, 2
            ) == ["case"]
            assert await evaluation_api.create_workspace_evaluation_case(
                "kb-1",
                KnowledgeEvaluationCaseCreateRequest(
                    question="question", expected_document_ids=["doc-1"]
                ),
                context,
                db,
            ) == "created"
            deleted = await evaluation_api.delete_workspace_evaluation_case(
                "kb-1", "case-1", context, db
            )
            assert deleted.status_code == 204
            deleted_run = await evaluation_api.delete_workspace_evaluation_run(
                "kb-1", "task-1", context, db
            )
            assert deleted_run.status_code == 204
            assert await evaluation_api.list_workspace_evaluation_runs(
                "kb-1", context, db, 5
            ) == ["run"]
            assert (
                await evaluation_api.create_workspace_evaluation_run(
                    "kb-1",
                    KnowledgeEvaluationRunRequest(case_ids=["case-1"]),
                    context,
                    settings,
                    db,
                )
            ).id == "task-1"
            assert await evaluation_api.get_workspace_evaluation_run(
                "kb-1", "task-1", context, db
            ) == "run"
            assert await evaluation_api.get_workspace_evaluation_results(
                "kb-1", "task-1", context, db
            ) == "summary"
            assert await evaluation_api.get_workspace_latest_evaluation_results(
                "kb-1", context, db
            ) == "latest"

        asyncio.run(run())
    finally:
        (
            evaluation_api.get_knowledge_base,
            evaluation_api.require_knowledge_base_permission,
            evaluation_api.list_evaluation_cases,
            evaluation_api.create_evaluation_case,
            evaluation_api.delete_evaluation_case,
            evaluation_api.delete_evaluation_run,
            evaluation_api.list_evaluation_runs,
            evaluation_api.enqueue_evaluation_run,
            evaluation_api.dispatch_knowledge_task,
            evaluation_api.get_evaluation_run,
            evaluation_api.get_evaluation_summary,
            evaluation_api.get_latest_evaluation_summary,
        ) = originals

    assert ("dispatch", "task-1") in calls
    assert ("permission", {"edit"}) in calls
    assert ("permission", {"view", "edit"}) in calls


def test_qa_import_is_explicit_validated_and_bounded() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference

    from app.capabilities.embedding.pipeline import KnowledgePipelineError
    from app.capabilities.embedding.qa_import import (
        QaRow,
        extract_qa_rows,
        validate_qa_rows,
    )

    def expect_error(rows, fragment: str) -> None:
        try:
            validate_qa_rows(rows)
        except KnowledgePipelineError as exc:
            assert fragment in str(exc), str(exc)
        else:
            raise AssertionError("invalid QA rows were accepted")

    with TemporaryDirectory() as directory:
        root = Path(directory)
        csv_path = root / "qa.csv"
        csv_path.write_text(
            "问题,答案,来源\n如何回滚？,需要管理员批准。,运维手册 3.2\n",
            encoding="utf-8-sig",
        )
        expected = [
            QaRow(
                question="如何回滚？",
                answer="需要管理员批准。",
                source="运维手册 3.2",
                row_number=2,
            )
        ]
        assert extract_qa_rows(csv_path.name, csv_path) == expected

        xlsx_path = root / "qa.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        assert worksheet is not None
        worksheet.append(["question", "answer", "source"])
        worksheet.append(["如何回滚？", "需要管理员批准。", "运维手册 3.2"])
        chart = BarChart()
        chart.add_data(
            Reference(worksheet, min_col=2, min_row=1, max_row=2),
            titles_from_data=True,
        )
        chartsheet = workbook.create_chartsheet("Chart")
        chartsheet.add_chart(chart)
        workbook.active = chartsheet
        workbook.save(xlsx_path)
        workbook.close()
        assert extract_qa_rows(xlsx_path.name, xlsx_path) == expected

        empty_workbook = SimpleNamespace(worksheets=[], close=lambda: None)
        with patch(
            "app.capabilities.embedding.qa_import.load_workbook",
            return_value=empty_workbook,
        ):
            try:
                extract_qa_rows(xlsx_path.name, xlsx_path)
            except KnowledgePipelineError as exc:
                assert "no worksheet" in str(exc)
            else:
                raise AssertionError("QA workbook without worksheets was accepted")

        try:
            extract_qa_rows("qa.txt", csv_path)
        except KnowledgePipelineError as exc:
            assert "CSV and XLSX" in str(exc)
        else:
            raise AssertionError("unsupported QA file was accepted")

        invalid_csv = root / "invalid.csv"
        invalid_csv.write_bytes(b"question,answer\n\xff,answer\n")
        try:
            extract_qa_rows(invalid_csv.name, invalid_csv)
        except KnowledgePipelineError as exc:
            assert "UTF-8" in str(exc)
        else:
            raise AssertionError("non-UTF-8 QA CSV was accepted")

        invalid_xlsx = root / "invalid.xlsx"
        invalid_xlsx.write_bytes(b"not an xlsx archive")
        try:
            extract_qa_rows(invalid_xlsx.name, invalid_xlsx)
        except KnowledgePipelineError as exc:
            assert "invalid" in str(exc)
        else:
            raise AssertionError("invalid QA XLSX was accepted")

    expect_error([], "no header")
    expect_error([["", ""], ["question", "answer"]], "no data")
    assert validate_qa_rows(
        [["ignored", "question", "answer"], ["unused", "q", "a"]]
    ) == [QaRow(question="q", answer="a", source="", row_number=2)]
    assert validate_qa_rows(
        [["", ""], ["question", "answer"], ["", ""], ["q", "a"]]
    ) == [QaRow(question="q", answer="a", source="", row_number=4)]
    expect_error([["source"]], "requires")
    expect_error([["question", "问题", "answer"]], "duplicate question")
    expect_error([["question", "answer"], ["", "answer"]], "row 2")
    expect_error([["question", "answer"], ["question", ""]], "row 2")
    expect_error(
        [["question", "answer"], ["q" * 2001, "answer"]],
        "row 2",
    )
    expect_error(
        [["question", "answer"], ["question", "a" * 20001]],
        "row 2",
    )

    def too_many_rows():
        yield ["question", "answer"]
        for index in range(5001):
            yield [f"question {index}", "answer"]
        raise AssertionError("QA parser consumed beyond its row limit")

    expect_error(too_many_rows(), "row 5002")


def test_explicit_reference_extraction_is_bounded_and_internal() -> None:
    from app.entities.knowledge import (
        KnowledgeDocument,
        KnowledgeDocumentParentChunk,
    )
    from app.shareddomain.knowledge.references import (
        _resolution_context,
        _resolved_target,
        extract_reference_labels,
    )

    labels = extract_reference_labels(
        "详见《发布手册.md》第三章，或参考 "
        "[回滚章节](docs/%E5%8F%91%E5%B8%83%E6%89%8B%E5%86%8C.md#%E5%9B%9E%E6%BB%9A)。"
        "![架构图](architecture.png)"
        "[外链](https://example.com/发布手册.md)"
    )
    assert [
        (item.target_label, item.target_section, item.reference_type)
        for item in labels
    ] == [
        ("发布手册.md", "第三章", "text"),
        ("发布手册.md", "回滚", "markdown"),
    ]

    many = " ".join(f"[文档 {index}](doc-{index}.md)" for index in range(101))
    assert len(extract_reference_labels(many)) == 100

    document = KnowledgeDocument(id="document-1", filename="release.md")
    parent = KnowledgeDocumentParentChunk(
        id="parent-1",
        document_id=document.id,
        title="Rollback Procedure",
    )
    documents_by_alias, parents_by_document = _resolution_context(
        [document],
        [parent],
    )
    assert _resolved_target(
        "release.md",
        "rollback-procedure",
        documents_by_alias,
        parents_by_document,
    ) == (document.id, parent.id)
    duplicate = KnowledgeDocumentParentChunk(
        id="parent-2",
        document_id=document.id,
        title="Rollback Procedure",
    )
    _, duplicate_parents = _resolution_context([document], [parent, duplicate])
    assert _resolved_target(
        "release.md",
        "rollback-procedure",
        documents_by_alias,
        duplicate_parents,
    ) == (document.id, None)


def test_reference_rebuild_reuses_resolution_context() -> None:
    from unittest.mock import AsyncMock, patch

    from app.entities.knowledge import (
        KnowledgeDocument,
        KnowledgeDocumentChunk,
        KnowledgeDocumentParentChunk,
        KnowledgeDocumentReference,
    )
    from app.shareddomain.knowledge import references as reference_service

    knowledge_base = KnowledgeBase(id="kb-1", workspace_id="ws-1")
    source = KnowledgeDocument(
        id="source-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        filename="source.md",
    )
    target = KnowledgeDocument(
        id="target-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        filename="target.md",
    )
    parent = KnowledgeDocumentParentChunk(
        id="parent-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        document_id=target.id,
        title="Section",
    )
    chunk = KnowledgeDocumentChunk(
        id="chunk-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        document_id=source.id,
        content="[Target](target.md#section)",
    )
    incoming = KnowledgeDocumentReference(
        id="reference-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        source_document_id=target.id,
        source_chunk_id="chunk-2",
        target_label="source.md",
    )

    with (
        patch.object(
            reference_service.reference_repository,
            "delete_source_references",
            new=AsyncMock(),
        ),
        patch.object(
            reference_service.reference_repository,
            "list_active_documents",
            new=AsyncMock(return_value=[source, target]),
        ) as list_documents,
        patch.object(
            reference_service.reference_repository,
            "list_parent_chunks_for_documents",
            new=AsyncMock(return_value=[parent]),
        ) as list_parents,
        patch.object(
            reference_service.reference_repository,
            "add_references",
            new=AsyncMock(),
        ) as add_references,
        patch.object(
            reference_service.reference_repository,
            "list_references_matching_aliases",
            new=AsyncMock(return_value=[incoming]),
        ),
        patch.object(
            reference_service.reference_repository,
            "save_reference",
            new=AsyncMock(),
        ),
    ):
        asyncio.run(
            reference_service.rebuild_document_references(
                SimpleNamespace(),
                knowledge_base,
                source,
                [chunk],
            )
        )

    assert list_documents.await_count == 1
    assert list_parents.await_count == 1
    outgoing = add_references.await_args.args[1][0]
    assert (outgoing.target_document_id, outgoing.target_parent_id) == (
        target.id,
        parent.id,
    )
    assert incoming.target_document_id == source.id


def test_parent_context_windows_around_child_offsets() -> None:
    long_content = "x" * (MAX_PARENT_CONTEXT_CHARS + 500)
    parent = SimpleNamespace(content=long_content)

    # no offsets -> head truncation
    head = parent_context(parent, SimpleNamespace(start_offset=None, end_offset=None))
    assert len(head) == MAX_PARENT_CONTEXT_CHARS
    assert head == long_content[:MAX_PARENT_CONTEXT_CHARS]

    # offsets near the end -> tail window
    tail = parent_context(
        parent,
        SimpleNamespace(
            start_offset=len(long_content) - 10,
            end_offset=len(long_content),
        ),
    )
    assert len(tail) == MAX_PARENT_CONTEXT_CHARS
    assert tail == long_content[-MAX_PARENT_CONTEXT_CHARS:]

    # short parent returns the whole content
    short_parent = SimpleNamespace(content="short")
    assert (
        parent_context(short_parent, SimpleNamespace(start_offset=0, end_offset=2))
        == "short"
    )


# ---------------------------------------------------------------- model registry helpers


def test_model_type_normalization() -> None:
    assert normalize_model_type("llm") == "LLM"
    assert normalize_model_type(" embeddings ") == "EMBEDDING"
    assert normalize_model_type("rerank") == "RERANKER"
    expect_http_error(lambda: normalize_model_type("vision"), 422)


def test_status_validation() -> None:
    assert validate_status("active") == "active"
    expect_http_error(lambda: validate_status("paused"), 422)


def test_url_credential_validation() -> None:
    assert (
        normalize_url_credential("https://api.example.com/", "api_base")
        == "https://api.example.com"
    )
    expect_http_error(
        lambda: normalize_url_credential("file:///tmp/x", "api_base"),
        422,
    )


def test_masked_secret_detection() -> None:
    assert is_masked_secret("****abcd", "abcd")
    assert not is_masked_secret("real-secret", "abcd")


def test_provider_credentials_aws_pairing_rule() -> None:
    entry = {
        "credential_fields": [
            {"field": "aws_access_key_id", "input_type": "PasswordInput", "required": False},
            {"field": "aws_secret_access_key", "input_type": "PasswordInput", "required": False},
            {"field": "aws_session_token", "input_type": "PasswordInput", "required": False},
        ]
    }
    expect_http_error(
        lambda: normalize_provider_credentials(
            entry,
            {"aws_access_key_id": "AKIA123"},
        ),
        422,
    )
    expect_http_error(
        lambda: normalize_provider_credentials(
            entry,
            {"aws_session_token": "token"},
        ),
        422,
    )
    config, secrets, hints, changed = normalize_provider_credentials(
        entry,
        {"aws_access_key_id": "AKIA123", "aws_secret_access_key": "secret"},
    )
    assert changed == {"aws_access_key_id", "aws_secret_access_key"}
    assert secrets["aws_access_key_id"] == "AKIA123"


# ------------------------------------------------- knowledge model test with mocked ports


def test_run_knowledge_model_test_uses_injected_providers() -> None:
    from app.schemas.knowledge import KnowledgeModelTestRequest
    from app.shareddomain.knowledge.services import run_knowledge_model_test

    embedding_model = SimpleNamespace(id="emb-1")
    reranker_model = SimpleNamespace(id="rerank-1")
    calls = {"embed": 0, "rerank": 0}

    class FakeEmbeddings:
        def embed_query(self, text: str) -> list[float]:
            assert text == "query"
            calls["embed"] += 1
            return [1.0, 2.0, 3.0]

    class FakeReranker:
        def rerank(self, query: str, documents: list[str]) -> list[dict]:
            assert query == "query"
            assert documents == ["doc"]
            calls["rerank"] += 1
            return [{"index": 0, "relevance_score": 0.9}]

    from app.shareddomain.knowledge import kb as knowledge_kb

    original_embeddings = knowledge_kb.build_embeddings
    original_reranker = knowledge_kb.build_reranker
    knowledge_kb.build_embeddings = lambda _settings, _model: FakeEmbeddings()
    knowledge_kb.build_reranker = lambda _settings, _model: FakeReranker()
    try:
        response = run_knowledge_model_test(
            embedding_model,
            reranker_model,
            KnowledgeModelTestRequest(query="query", documents=["doc"]),
            settings=object(),
        )
        assert response.embedding_dimensions == 3
        assert response.reranker_results == 1
        assert calls == {"embed": 1, "rerank": 1}

        # without a reranker the rerank port is never touched
        no_rerank = run_knowledge_model_test(
            embedding_model,
            None,
            KnowledgeModelTestRequest(query="query", documents=["doc"]),
            settings=object(),
        )
        assert no_rerank.reranker_model_id is None
        assert calls["rerank"] == 1
    finally:
        knowledge_kb.build_embeddings = original_embeddings
        knowledge_kb.build_reranker = original_reranker


# ---------------------------------------------------------------- agent helpers


def test_safe_agent_error_classification() -> None:
    from app.application.agent_tools import safe_agent_error
    from app.ports.llm import ModelProviderError, ModelProviderStatusError
    from app.shareddomain.agents.runtime import AgentRunnerError

    status_error = ModelProviderStatusError(429, "rate limited")
    assert safe_agent_error(status_error) == str(status_error)

    runner_error = AgentRunnerError("planning failed")
    assert safe_agent_error(runner_error) == str(runner_error)

    provider_error = ModelProviderError("boom")
    assert safe_agent_error(provider_error) == "Agent model request failed."
    assert safe_agent_error(ValueError("other")) == "Agent execution failed."


def test_agent_process_events_update_in_place() -> None:
    from app.application.agent_executor import (
        _completed_process_events,
        _upsert_process_event,
    )

    knowledge = {"type": "tool", "turn": 0, "call_id": "knowledge"}
    thought = {
        "type": "thought",
        "turn": 1,
        "tool_name": "",
        "summary": "agent.answer_ready",
    }
    tool = {"type": "tool", "turn": 1, "call_id": "mcp"}
    events = [knowledge, thought, tool]

    updated_thought = {**thought, "summary": "agent.tools_selected"}
    _upsert_process_event(events, updated_thought)

    assert events == [knowledge, updated_thought, tool]

    first_running = {
        "type": "tool",
        "turn": 2,
        "call_id": "first",
        "status": "running",
    }
    second_running = {
        "type": "tool",
        "turn": 2,
        "call_id": "second",
        "status": "running",
    }
    parallel_events: list[dict] = []
    for event in (first_running, second_running):
        _upsert_process_event(parallel_events, event)
    _upsert_process_event(parallel_events, {**second_running, "status": "succeeded"})
    _upsert_process_event(parallel_events, {**first_running, "status": "succeeded"})

    completed = _completed_process_events(parallel_events)
    assert [event["call_id"] for event in completed] == ["first", "second"]


def test_agent_event_replay_reads_every_page() -> None:
    from app.application import agent_executor

    rows = [
        SimpleNamespace(id=index)
        for index in range(1, agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE + 3)
    ]
    calls: list[tuple[int, int]] = []

    async def list_events(_db, _run_id, after=0, limit=200):
        calls.append((after, limit))
        return [row for row in rows if row.id > after][:limit]

    original_list_events = agent_executor.agent_repository.list_agent_run_events
    agent_executor.agent_repository.list_agent_run_events = list_events
    try:
        replayed = asyncio.run(
            agent_executor._list_all_agent_run_events(
                SimpleNamespace(),
                "run-1",
            )
        )
    finally:
        agent_executor.agent_repository.list_agent_run_events = original_list_events

    assert replayed == rows
    assert calls == [
        (0, agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE),
        (
            agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE,
            agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE,
        ),
    ]


def test_stale_mcp_policy_requires_approval() -> None:
    from app.application import agent_executor
    from app.entities.agents import AgentRun
    from app.entities.tools import McpToolPolicy
    from app.shareddomain.agents.runtime import AgentExecutionPaused

    created_calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def commit(self):
            return None

    async def get_policy(*_args, **_kwargs):
        return McpToolPolicy(
            definition_hash="stale-definition",
            mode="read_only",
        )

    async def get_call(*_args, **_kwargs):
        return None

    async def create_call(_db, call):
        created_calls.append(call)
        return call

    original_factory = agent_executor.get_session_factory
    original_get_policy = agent_executor.get_mcp_tool_policy
    original_get_call = agent_executor.agent_repository.get_agent_tool_call
    original_create_call = agent_executor.agent_repository.create_agent_tool_call
    agent_executor.get_session_factory = lambda: lambda: FakeSession()
    agent_executor.get_mcp_tool_policy = get_policy
    agent_executor.agent_repository.get_agent_tool_call = get_call
    agent_executor.agent_repository.create_agent_tool_call = create_call

    async def assert_paused() -> None:
        ledger = agent_executor.DurableToolLedger(
            AgentRun(id="run-1", workspace_id="ws-1"),
            "worker-1",
            SimpleNamespace(),
            asyncio.Event(),
        )
        try:
            await ledger.before(
                1,
                {"id": "call-1", "name": "mcp_search", "arguments": "{}"},
                {
                    "kind": "mcp",
                    "server_name": "Search",
                    "server_id": "server-1",
                    "source_tool_name": "search",
                    "definition_hash": "current-definition",
                    "policy_mode": "read_only",
                },
                {},
            )
        except AgentExecutionPaused as exc:
            assert exc.call_id == "call-1"
            return
        raise AssertionError("stale read-only policy did not require approval")

    try:
        asyncio.run(assert_paused())
    finally:
        agent_executor.get_session_factory = original_factory
        agent_executor.get_mcp_tool_policy = original_get_policy
        agent_executor.agent_repository.get_agent_tool_call = original_get_call
        agent_executor.agent_repository.create_agent_tool_call = original_create_call

    assert created_calls[0].policy_mode == "approval_required"
    assert created_calls[0].approval_required is True


def test_external_mcp_policy_public_reconciles_like_console() -> None:
    from app.application.agent_executor import current_mcp_policy_mode
    from app.entities.tools import McpToolPolicy

    metadata = {
        "definition_hash": "current-definition",
        "policy_mode": "read_only",
    }
    current = McpToolPolicy(
        definition_hash="current-definition",
        mode="read_only",
    )
    assert (
        current_mcp_policy_mode(
            "public",
            metadata,
            current,
            "current-definition",
        )
        == "read_only"
    )
    assert (
        current_mcp_policy_mode(
            "api",
            metadata,
            None,
            "current-definition",
        )
        == "disabled"
    )
    # Public runs reconcile like console runs: a stale or drifted policy
    # definition falls back to approval, never to a silent disable.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="stale-definition",
            mode="read_only",
        ),
        "current-definition",
    ) == "approval_required"
    assert current_mcp_policy_mode(
        "api",
        metadata,
        McpToolPolicy(
            definition_hash="current-definition",
            mode="approval_required",
        ),
        "current-definition",
    ) == "disabled"
    # A live definition that drifted from the durable call snapshot requires
    # renewed approval on public runs; only the API read-only gate compares
    # the live hash directly.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        current,
        "drifted-definition",
    ) == "approval_required"
    # Disabled stays disabled everywhere, including during live drift.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="current-definition",
            mode="disabled",
        ),
        "current-definition",
    ) == "disabled"
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="stale-definition",
            mode="disabled",
        ),
        "drifted-definition",
    ) == "disabled"
    # Approval-required policies now reach the approval flow on public runs.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="current-definition",
            mode="approval_required",
        ),
        "current-definition",
    ) == "approval_required"


def test_external_mcp_policy_drift_requires_public_approval_but_blocks_api() -> None:
    from app.application import agent_executor
    from app.entities.agents import AgentRun
    from app.entities.tools import McpToolPolicy

    created_calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def commit(self):
            return None

    async def get_policy(*_args, **_kwargs):
        return McpToolPolicy(
            definition_hash="current-definition",
            mode="approval_required",
        )

    async def get_call(_db, run_id, _turn, _call_id):
        for call in reversed(created_calls):
            if call.run_id == run_id:
                return call
        return None

    async def resolve_tools(*_args, **_kwargs):
        return [SimpleNamespace(definition=SimpleNamespace())]

    async def create_call(_db, call):
        created_calls.append(call)
        return call

    async def block_call(_db, _call_id, reason, blocked_at, result_summary):
        call = created_calls[-1]
        call.status = "rejected"
        call.last_error = reason
        call.result_content = reason
        call.result_summary = result_summary
        call.result_is_error = True
        call.finished_at = blocked_at
        return True

    original_factory = agent_executor.get_session_factory
    original_get_policy = agent_executor.get_mcp_tool_policy
    original_get_call = agent_executor.agent_repository.get_agent_tool_call
    original_create_call = agent_executor.agent_repository.create_agent_tool_call
    original_block_call = agent_executor.agent_repository.block_agent_tool_call
    original_resolve_tools = agent_executor.resolve_mcp_tools
    original_definition_hash = agent_executor.mcp_tool_definition_hash
    agent_executor.get_session_factory = lambda: lambda: FakeSession()
    agent_executor.get_mcp_tool_policy = get_policy
    agent_executor.agent_repository.get_agent_tool_call = get_call
    agent_executor.agent_repository.create_agent_tool_call = create_call
    agent_executor.agent_repository.block_agent_tool_call = block_call
    agent_executor.resolve_mcp_tools = resolve_tools
    agent_executor.mcp_tool_definition_hash = lambda _definition: "current-definition"

    metadata = {
        "kind": "mcp",
        "server_name": "Search",
        "server_id": "server-1",
        "source_tool_name": "search",
        "definition_hash": "current-definition",
        "policy_mode": "read_only",
    }

    async def assert_public_requires_approval() -> None:
        ledger = agent_executor.DurableToolLedger(
            AgentRun(
                id="run-1",
                workspace_id="ws-1",
                access_source="public",
                consumer_id="visitor-1",
            ),
            "worker-1",
            SimpleNamespace(),
            asyncio.Event(),
        )
        try:
            await ledger.before(
                1,
                {"id": "call-1", "name": "mcp_search", "arguments": "{}"},
                metadata,
                {},
            )
        except agent_executor.AgentExecutionPaused:
            return
        raise AssertionError("expected AgentExecutionPaused")

    async def assert_api_stays_blocked() -> None:
        ledger = agent_executor.DurableToolLedger(
            AgentRun(
                id="run-2",
                workspace_id="ws-1",
                access_source="api",
                consumer_id="credential-1",
            ),
            "worker-1",
            SimpleNamespace(),
            asyncio.Event(),
        )
        result = await ledger.before(
            1,
            {"id": "call-2", "name": "mcp_search", "arguments": "{}"},
            metadata,
            {},
        )
        assert result is not None and result.is_error is True

    try:
        asyncio.run(assert_public_requires_approval())
        public_call = created_calls[-1]
        assert public_call.policy_mode == "approval_required"
        assert public_call.approval_required is True
        assert public_call.status == "awaiting_approval"
        asyncio.run(assert_api_stays_blocked())
        api_call = created_calls[-1]
        assert api_call.policy_mode == "disabled"
        assert api_call.approval_required is False
        assert api_call.status == "rejected"
    finally:
        agent_executor.get_session_factory = original_factory
        agent_executor.get_mcp_tool_policy = original_get_policy
        agent_executor.agent_repository.get_agent_tool_call = original_get_call
        agent_executor.agent_repository.create_agent_tool_call = original_create_call
        agent_executor.agent_repository.block_agent_tool_call = original_block_call
        agent_executor.resolve_mcp_tools = original_resolve_tools
        agent_executor.mcp_tool_definition_hash = original_definition_hash


def test_external_stream_epoch_is_stable_and_sanitized() -> None:
    from app.application.agent_access import sanitize_external_agent_stream
    from app.infrastructure.model_utils import utc_now

    now = utc_now()
    raw_epoch = "worker-task-internal-epoch"
    running = {
        "id": "run-1",
        "conversation_id": "conversation-1",
        "goal": "Question",
        "status": "running",
        "result": "",
        "created_at": now,
        "started_at": now,
        "finished_at": None,
        "updated_at": now,
    }
    completed = {
        **running,
        "status": "succeeded",
        "result": "Answer",
        "finished_at": now,
    }

    async def source():
        yield {
            "type": "run",
            "run": running,
            "sequence": 0,
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "reasoning_delta",
            "turn": 1,
            "delta": "Let me think",
            "live_sequence": "1-0",
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "process",
            "event": {
                "type": "thought",
                "turn": 1,
                "status": "succeeded",
                "summary": "agent.answer_ready",
                "reasoning": "Let me think",
                "call_id": "internal-call-1",
                "tool_name": "mcp_internal_search",
            },
            "sequence": 1,
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "answer_delta",
            "delta": "Answer",
            "live_sequence": "2-0",
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "complete",
            "run": completed,
            "sequence": 2,
            "stream_epoch": raw_epoch,
        }

    async def collect():
        return [event async for event in sanitize_external_agent_stream(source())]

    events = asyncio.run(collect())
    epochs = [event["stream_epoch"] for event in events]
    assert len(set(epochs)) == 1
    assert len(epochs[0]) == 32
    assert raw_epoch not in repr(events)
    assert epochs[0] != raw_epoch
    assert "internal-call-1" not in repr(events)
    assert "mcp_internal_search" not in repr(events)
    reasoning_deltas = [event for event in events if event["type"] == "reasoning_delta"]
    assert len(reasoning_deltas) == 1
    assert {
        key: reasoning_deltas[0][key]
        for key in ("type", "turn", "delta")
    } == {"type": "reasoning_delta", "turn": 1, "delta": "Let me think"}
    progress_events = [event for event in events if event["type"] == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0]["event"] == {
        "id": progress_events[0]["event"]["id"],
        "type": "answer",
        "status": "running",
        "stage": "running",
        "turn": 1,
        "count": None,
        "reasoning": "Let me think",
        "tool_name": "",
        "tool_label": "",
        "tool_kind": "unknown",
        "server_name": "",
        "input": {},
        "output": None,
        "input_truncated": False,
        "hits": [],
    }


def test_external_progress_events_carry_knowledge_hits() -> None:
    from app.application.agent_access import external_progress_events

    events = [
        {
            "type": "tool",
            "turn": 0,
            "tool_name": "search_knowledge",
            "tool_kind": "knowledge",
            "status": "running",
            "summary": "agent.tool_running",
            "call_id": "call-1",
        },
        {
            "type": "tool",
            "turn": 0,
            "tool_name": "search_knowledge",
            "tool_kind": "knowledge",
            "status": "succeeded",
            "summary": "agent.knowledge_chunks_returned:2",
            "call_id": "call-1",
            "output": {
                "query": "release process",
                "hits": [
                    {
                        "knowledge_base": "Release KB",
                        "document": "release.md",
                        "content": "Cut the release on Fridays.",
                    },
                    {
                        "knowledge_base": "Release KB",
                        "document": "handbook.md",
                        "content": "Tag with semantic versions.",
                    },
                    "not-a-dict",
                ],
                "evidence_status": "found",
            },
        },
    ]
    progress = external_progress_events(events, "succeeded")
    assert len(progress) == 1
    event = progress[0]
    assert event.type == "knowledge"
    assert event.status == "succeeded"
    assert event.count == 2
    assert [hit.model_dump() for hit in event.hits] == [
        {
            "knowledge_base": "Release KB",
            "document": "release.md",
            "content": "Cut the release on Fridays.",
        },
        {
            "knowledge_base": "Release KB",
            "document": "handbook.md",
            "content": "Tag with semantic versions.",
        },
    ]


def test_external_progress_events_carry_mcp_tool_details() -> None:
    from app.application.agent_access import external_progress_events

    progress = external_progress_events(
        [
            {
                "type": "tool",
                "turn": 1,
                "tool_name": "web_search",
                "tool_label": "Web search",
                "tool_kind": "mcp",
                "server_name": "Tavily",
                "status": "succeeded",
                "summary": "agent.tool_running",
                "call_id": "call-2",
                "input": {"query": "GitHub trending"},
                "output": {"results": [{"title": "NexaFlow"}]},
            }
        ],
        "succeeded",
    )

    assert len(progress) == 1
    event = progress[0]
    assert event.tool_name == "web_search"
    assert event.tool_label == "Web search"
    assert event.tool_kind == "mcp"
    assert event.server_name == "Tavily"
    assert event.input == {"query": "GitHub trending"}
    assert event.output == {"results": [{"title": "NexaFlow"}]}


def test_external_progress_events_bound_tool_inputs_and_pass_output() -> None:
    import json

    from app.application.agent_access import (
        TOOL_INPUT_LIMITS,
        _bounded_tool_payload,
        external_progress_events,
    )

    # input 用紧限制：字符串/深度/集合/全局预算都被约束
    oversized = {
        "query": "x" * (TOOL_INPUT_LIMITS.max_string + 100),
        "nested": {"deep": {"deeper": {"deepest": {"value": "too deep"}}}},
        "items": list(range(100)),
    }
    bounded, truncated = _bounded_tool_payload(oversized, TOOL_INPUT_LIMITS)
    assert truncated
    assert len(bounded["query"]) <= TOOL_INPUT_LIMITS.max_string + 1
    assert len(bounded["items"]) <= TOOL_INPUT_LIMITS.max_items
    assert bounded["nested"]["deep"]["deeper"]["deepest"] == "…"
    assert len(json.dumps(bounded)) < TOOL_INPUT_LIMITS.max_serialized

    # input 全局预算：结构巨大时整体受限，序列化保持有界
    huge = {"key": {f"k{i}": "v" * 200 for i in range(100)}}
    bounded_huge, huge_truncated = _bounded_tool_payload(huge, TOOL_INPUT_LIMITS)
    assert huge_truncated
    assert len(json.dumps(bounded_huge)) < TOOL_INPUT_LIMITS.max_serialized

    # input 扁平超大 dict：只消费前 max_items 项，不 materialize 全部
    flat = {f"key-{i}": "value" for i in range(10000)}
    bounded_flat, flat_truncated = _bounded_tool_payload(flat, TOOL_INPUT_LIMITS)
    assert flat_truncated
    assert len(bounded_flat) <= TOOL_INPUT_LIMITS.max_items

    # output 完整透传：事件中的任意大小/深度结果原样返回，不截断
    huge_output = {
        "text": "z" * 50000,
        "nested": {"a": {"b": {"c": {"d": {"e": {"f": {"g": "deep"}}}}}}},
        "rows": list(range(5000)),
    }
    progress = external_progress_events(
        [
            {
                "type": "tool",
                "turn": 1,
                "tool_kind": "mcp",
                "status": "succeeded",
                "summary": "agent.tool_running",
                "call_id": "call-3",
                "input": {"query": "x" * (TOOL_INPUT_LIMITS.max_string + 50)},
                "output": huge_output,
            }
        ],
        "succeeded",
    )
    assert progress[0].input_truncated is True
    assert progress[0].output == huge_output


def test_external_progress_events_knowledge_failure_has_no_hits() -> None:
    from app.application.agent_access import external_progress_events

    progress = external_progress_events(
        [
            {
                "type": "tool",
                "turn": 0,
                "tool_name": "search_knowledge",
                "tool_kind": "knowledge",
                "status": "failed",
                "summary": "Knowledge search unavailable.",
                "call_id": "call-1",
                "output": {"query": "missing", "hits": [], "evidence_status": "unavailable"},
            }
        ],
        "failed",
    )
    assert len(progress) == 1
    event = progress[0]
    assert event.status == "failed"
    assert event.hits == []


def test_mcp_policy_concurrent_first_write_reloads_existing() -> None:
    from sqlalchemy.exc import IntegrityError

    from app.entities.tools import McpToolPolicy
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import mcp as mcp_repository
    from app.shareddomain.tools.models import McpToolPolicy as McpToolPolicyOrm

    now = utc_now()
    existing = McpToolPolicyOrm(
        id="policy-existing",
        workspace_id="ws-1",
        mcp_server_id="server-1",
        tool_name="search",
        definition_hash="old-definition",
        mode="approval_required",
        reviewed_by_user_id="user-old",
        reviewed_at=now,
        created_at=now,
        updated_at=now,
    )

    class FakeSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeSession:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.flush_calls = 0

        async def scalar(self, _statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else existing

        def begin_nested(self):
            return FakeSavepoint()

        def add(self, _row):
            return None

        async def flush(self):
            self.flush_calls += 1
            if self.flush_calls == 1:
                raise IntegrityError("insert", {}, Exception("unique"))

    async def save_policy() -> McpToolPolicy:
        return await mcp_repository.save_mcp_tool_policy(
            FakeSession(),  # type: ignore[arg-type]
            McpToolPolicy(
                workspace_id="ws-1",
                mcp_server_id="server-1",
                tool_name="search",
                definition_hash="current-definition",
                mode="read_only",
                reviewed_by_user_id="user-new",
                reviewed_at=now,
            ),
        )

    saved = asyncio.run(save_policy())
    assert saved.id == "policy-existing"
    assert saved.definition_hash == "current-definition"
    assert saved.mode == "read_only"
    assert saved.reviewed_by_user_id == "user-new"
    assert saved.created_at == now


def test_mcp_function_name_is_stable_and_sanitized() -> None:
    import hashlib

    from mcp.types import Tool as McpTool

    from app.application.agent_tools import build_mcp_agent_tool, mcp_function_name
    from app.entities.tools import McpServer
    from app.shareddomain.tools.services import ResolvedMcpTool

    server = McpServer(id="server-1", name="orders")
    tool = ResolvedMcpTool(
        server=server,
        definition=McpTool(
            name="order items!",
            input_schema={"type": "object"},
            description="",
            annotations={"readOnlyHint": True, "destructiveHint": False},
        ),
    )
    name = mcp_function_name(tool)
    assert name.startswith("mcp_order_items_")
    digest = hashlib.sha256(b"server-1:order items!").hexdigest()[:8]
    assert name == f"mcp_order_items_{digest}"
    # deterministic for the same server/tool pair
    assert mcp_function_name(tool) == name
    built = build_mcp_agent_tool(tool, SimpleNamespace())
    assert built.metadata is not None
    assert built.metadata["policy_mode"] == "approval_required"


def test_run_to_response_maps_run_fields() -> None:
    from app.application.agent_tools import run_to_response
    from app.entities.agents import AgentRun

    run = AgentRun(
        id="run-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        requested_by_user_id="user-1",
        conversation_id="conversation-1",
        goal="goal",
        instructions="instructions",
        model_id="model-1",
        model_name="deepseek-chat",
        status="succeeded",
        result="answer",
        model_usage={"model_calls": 1, "total_tokens": 12},
    )
    response = run_to_response(run, trace_id="trace-1")
    assert response.id == "run-1"
    assert response.workspace_id == "ws-1"
    assert response.agent_id == "agent-1"
    assert response.conversation_id == "conversation-1"
    assert response.status == "succeeded"
    assert response.result == "answer"
    assert response.model_name == "deepseek-chat"
    assert response.plan == []
    assert response.events == []
    assert response.model_usage["total_tokens"] == 12
    assert response.trace_id == "trace-1"


def test_agent_usage_normalizes_provider_metadata() -> None:
    from langchain_core.messages import AIMessage

    from app.shareddomain.agents.runtime import (
        add_compaction_usage,
        merge_usage,
        usage_from_message,
    )

    standard = usage_from_message(
        AIMessage(
            content="one",
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 3,
                "total_tokens": 13,
                "input_token_details": {"cache_read": 4},
            },
        )
    )
    openai_compatible = usage_from_message(
        AIMessage(
            content="two",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 2,
                    "total_tokens": 9,
                }
            },
        )
    )
    unreported = usage_from_message(AIMessage(content="three"))
    merged = merge_usage(standard, openai_compatible, unreported)

    assert merged["model_calls"] == 3
    assert merged["reported_model_calls"] == 2
    assert merged["input_tokens"] == 17
    assert merged["output_tokens"] == 5
    assert merged["total_tokens"] == 22
    assert merged["cache_read_input_tokens"] == 4

    compacted = add_compaction_usage(None, standard)
    assert compacted["model_calls"] == 1
    assert compacted["compaction"]["total_tokens"] == 13


def test_agent_memory_compacts_old_turns() -> None:
    from langchain_core.messages import AIMessage

    from app.application import agent_memory
    from app.entities.agents import AgentRun

    history = [
        AgentRun(
            id=f"run-{index}",
            workspace_id="ws-1",
            agent_id="agent-1",
            requested_by_user_id="user-1",
            conversation_id="conversation-1",
            goal=f"question-{index}",
            result="x" * 3000,
            status="succeeded",
        )
        for index in range(8)
    ]
    current = AgentRun(
        id="run-current",
        workspace_id="ws-1",
        agent_id="agent-1",
        requested_by_user_id="user-1",
        conversation_id="conversation-1",
        goal="current question",
        status="running",
    )
    saved: list[tuple[str, str]] = []
    requested_limits: list[int] = []

    class FakeDatabase:
        async def flush(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class FakeModel:
        profile = {"max_input_tokens": 4096}

        async def ainvoke(self, _messages):
            return AIMessage(
                content="Stable summary",
                usage_metadata={
                    "input_tokens": 20,
                    "output_tokens": 4,
                    "total_tokens": 24,
                },
            )

    async def list_runs(_db, _run, *, limit):
        requested_limits.append(limit)
        return None, history

    async def save_summary(_db, run, summary):
        saved.append((run.id, summary))
        return True

    original_list = agent_memory.agent_repository.list_conversation_memory_runs
    original_save = agent_memory.agent_repository.save_conversation_summary
    agent_memory.agent_repository.list_conversation_memory_runs = list_runs
    agent_memory.agent_repository.save_conversation_summary = save_summary
    try:
        prepared = asyncio.run(
            agent_memory.prepare_conversation_memory(
                FakeDatabase(),  # type: ignore[arg-type]
                current,
                SimpleNamespace(meta={}),
                FakeModel(),
                [
                    {"role": "system", "content": "rules"},
                    {"role": "user", "content": "current question"},
                ],
                [],
            )
        )
    finally:
        agent_memory.agent_repository.list_conversation_memory_runs = original_list
        agent_memory.agent_repository.save_conversation_summary = original_save

    assert saved == [("run-0", "Stable summary")]
    assert requested_limits == [agent_memory.MAX_MEMORY_RUNS]
    assert prepared.messages[0]["content"].endswith("Stable summary")
    assert prepared.model_usage["compaction"]["total_tokens"] == 24

    tight = agent_memory._fit_memory("s" * 1000, history[-1:], 128)
    assert [message["role"] for message in tight] == ["user", "assistant"]
    assert agent_memory._approx_tokens(tight) <= 128
    assert agent_memory._memory_budget(
        [{"role": "user", "content": "x" * 5000}],
        [],
        SimpleNamespace(meta={}),
        FakeModel(),
    ) == 0


def test_agent_memory_query_is_bounded_and_projected() -> None:
    from app.entities.agents import AgentRun
    from app.infrastructure.repositories import agent as agent_repository
    from sqlalchemy.dialects import postgresql

    statements = []

    class EmptyScalars:
        def all(self):
            return []

    class FakeDatabase:
        async def scalar(self, statement):
            statements.append(statement)
            return None

        async def scalars(self, statement):
            statements.append(statement)
            return EmptyScalars()

    asyncio.run(
        agent_repository.list_conversation_memory_runs(
            FakeDatabase(),  # type: ignore[arg-type]
            AgentRun(
                workspace_id="ws-1",
                agent_id="agent-1",
                requested_by_user_id="user-1",
                conversation_id="conversation-1",
            ),
            limit=7,
        )
    )
    compiled = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in statements
    ]
    assert "LIMIT 7" in compiled[-1]
    for sql in compiled:
        assert "agent_runs.goal" in sql
        assert "agent_runs.result" in sql
        assert "agent_runs.context_summary" in sql
        assert "agent_runs.events" not in sql
        assert "agent_runs.plan" not in sql
        assert "agent_runs.checkpoint" not in sql


# ---------------------------------------------------------------- DTO mappings


def test_mcp_server_to_response() -> None:
    from app.entities.tools import McpServer, McpToolPolicy
    from app.shareddomain.tools.services import (
        effective_mcp_tool_policy_mode,
        mcp_server_to_response,
        mcp_tool_definition_hash,
    )
    from mcp.types import Tool as McpTool

    server = McpServer(
        id="mcp-1",
        workspace_id="ws-1",
        name="docs",
        url="https://tools.example.com/mcp",
        bearer_token_ciphertext="cipher",
        bearer_token_hint="abcd",
        tools=[
            {
                "name": "search",
                "description": "Search public records.",
                "input_schema": {"type": "object"},
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                },
            },
            {
                "name": "unknown",
                "description": "Unclassified operation.",
                "input_schema": {"type": "object"},
            },
        ],
        status="active",
        last_error=None,
        created_by_user_id="user-1",
    )
    stale_policy = McpToolPolicy(
        workspace_id="ws-1",
        mcp_server_id="mcp-1",
        tool_name="search",
        definition_hash="stale",
        mode="read_only",
    )
    response = mcp_server_to_response(server, [stale_policy])
    assert response.id == "mcp-1"
    assert response.workspace_id == "ws-1"
    assert response.url == "https://tools.example.com/mcp"
    assert response.has_bearer_token is True
    assert response.bearer_token_hint == "abcd"
    assert response.tools[0].policy_mode == "approval_required"
    assert response.tools[1].policy_mode == "approval_required"

    response = mcp_server_to_response(server)
    assert response.tools[0].policy_mode == "approval_required"
    assert response.tools[1].policy_mode == "approval_required"
    assert (
        effective_mcp_tool_policy_mode(
            McpTool(
                name="delete",
                input_schema={"type": "object"},
                annotations={"readOnlyHint": True, "destructiveHint": True},
            ),
            None,
        )
        == "approval_required"
    )
    read_only_policy = McpToolPolicy(
        workspace_id="ws-1",
        mcp_server_id="mcp-1",
        tool_name="search",
        definition_hash=response.tools[0].definition_hash,
        mode="read_only",
    )
    response = mcp_server_to_response(server, [read_only_policy])
    assert response.tools[0].policy_mode == "read_only"
    assert response.tools[0].definition_hash == mcp_tool_definition_hash(
        McpTool(
            name="search",
            description="Search public records.",
            input_schema={"type": "object"},
            annotations={"readOnlyHint": True, "destructiveHint": False},
        )
    )


def test_celery_worker_pool_is_fork_safe_without_prefork() -> None:
    from app.infrastructure.celery import worker_pool_for_platform

    assert worker_pool_for_platform("darwin") == "solo"
    assert worker_pool_for_platform("win32") == "solo"
    assert worker_pool_for_platform("linux") == "prefork"


def test_worker_database_rejects_in_memory_sqlite() -> None:
    from app.infrastructure.session import configure_database
    from tests.support import settings

    try:
        configure_database(settings(), worker_process=True)
    except ValueError as exc:
        assert "in-memory SQLite" in str(exc)
        return
    raise AssertionError("expected in-memory SQLite worker database to be rejected")


def test_windows_event_loop_policy_is_selector_based() -> None:
    import asyncio
    import sys

    from app.infrastructure.event_loop import configure_windows_event_loop_policy

    original_policy = asyncio.get_event_loop_policy()
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            configure_windows_event_loop_policy()
            policy = asyncio.get_event_loop_policy()
            assert isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy)
        else:
            configure_windows_event_loop_policy()
            assert asyncio.get_event_loop_policy() is original_policy
    finally:
        asyncio.set_event_loop_policy(original_policy)


def test_agent_live_stream_round_trip() -> None:
    from app.infrastructure import agent_live_stream
    from tests.support import settings

    class FakeRedis:
        def __init__(self) -> None:
            self.entries: list[tuple[str, dict[str, str]]] = []
            self.expirations: list[tuple[str, int]] = []
            self.read_blocks: list[int] = []

        async def xadd(self, name, fields, **kwargs):
            entry_id = f"1700000000000-{len(self.entries)}"
            self.entries.append((entry_id, fields))
            assert name == agent_live_stream.live_stream_key("run-1")
            assert kwargs["maxlen"] == agent_live_stream.LIVE_STREAM_MAXLEN
            return entry_id

        async def expire(self, name, seconds):
            self.expirations.append((name, seconds))
            return True

        def pipeline(self, transaction=False):
            assert transaction is False
            redis = self

            class FakePipeline:
                def __init__(self) -> None:
                    self.commands = []

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, traceback):
                    return False

                def xadd(self, *args, **kwargs):
                    self.commands.append(("xadd", args, kwargs))

                def expire(self, *args, **kwargs):
                    self.commands.append(("expire", args, kwargs))

                async def execute(self):
                    results = []
                    for name, args, kwargs in self.commands:
                        results.append(await getattr(redis, name)(*args, **kwargs))
                    return results

            return FakePipeline()

        async def xread(self, streams, **kwargs):
            self.read_blocks.append(kwargs["block"])
            name, cursor = next(iter(streams.items()))
            return [
                (
                    name,
                    [entry for entry in self.entries if entry[0] > cursor],
                )
            ]

        async def aclose(self):
            return None

    async def assert_round_trip() -> None:
        fake = FakeRedis()
        original_client = agent_live_stream._redis_client
        agent_live_stream._redis_client = lambda _settings: fake
        try:
            publisher = agent_live_stream.AgentLiveStreamPublisher(
                settings(),
                "run-1",
            )
            await publisher.publish({"type": "process", "event": {}})
            await publisher.publish(
                {
                    "type": "answer_delta",
                    "delta": "hello",
                    "stream_epoch": "worker-1",
                }
            )
            await publisher.publish(
                {
                    "type": "reasoning_delta",
                    "delta": "thinking",
                    "stream_epoch": "worker-1",
                }
            )
            reader = agent_live_stream.AgentLiveStreamReader(settings(), "run-1")
            events = await reader.read(
                "0-0",
                agent_live_stream.LIVE_STREAM_MAX_BLOCK_MS + 1000,
            )
            await publisher.close()
            await reader.close()
        finally:
            agent_live_stream._redis_client = original_client
        assert events == [
            (
                "1700000000000-0",
                {
                    "type": "answer_delta",
                    "delta": "hello",
                    "stream_epoch": "worker-1",
                },
            ),
            (
                "1700000000000-1",
                {
                    "type": "reasoning_delta",
                    "delta": "thinking",
                    "stream_epoch": "worker-1",
                },
            ),
        ]
        assert fake.expirations == [
            (
                agent_live_stream.live_stream_key("run-1"),
                agent_live_stream.LIVE_STREAM_TTL_SECONDS,
            ),
            (
                agent_live_stream.live_stream_key("run-1"),
                agent_live_stream.LIVE_STREAM_TTL_SECONDS,
            ),
        ]
        assert fake.read_blocks == [agent_live_stream.LIVE_STREAM_MAX_BLOCK_MS]

    asyncio.run(assert_round_trip())


def test_team_to_response() -> None:
    from app.entities.team import Team
    from app.shareddomain.teams.services import team_to_response

    team = Team(
        id="team-1",
        workspace_id="ws-1",
        name="Research",
        description="desc",
        status="active",
        is_default=True,
    )
    response = team_to_response(team)
    assert response.name == "Research"
    assert response.status == "active"
    assert response.is_default is True


def test_knowledge_document_and_attachment_response_mapping() -> None:
    from app.entities.knowledge import KnowledgeAttachment, KnowledgeDocument
    from app.shareddomain.knowledge.services import (
        attachment_to_response,
        document_to_response,
    )

    document = KnowledgeDocument(
        id="doc-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        filename="guide.txt",
        content_type="text/plain",
        size_bytes=42,
        meta={"security_level": "PUBLIC"},
        status="indexed",
        is_active=True,
        created_by_user_id="user-1",
    )
    response = document_to_response(document, chunk_count=7)
    assert response.filename == "guide.txt"
    assert response.meta["security_level"] == "PUBLIC"
    assert response.chunk_count == 7
    assert response.is_active is True

    attachment = KnowledgeAttachment(
        id="att-1",
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        filename="raw.txt",
        content_type="text/plain",
        size_bytes=10,
        object_key="ws-1/kb-1/attachments/att-1/raw.txt",
        status="available",
        created_by_user_id="user-1",
    )
    attachment_response = attachment_to_response(attachment)
    assert attachment_response.filename == "raw.txt"
    assert attachment_response.status == "available"


def test_knowledge_base_to_response() -> None:
    from app.entities.knowledge import KnowledgeBase
    from app.shareddomain.knowledge.services import knowledge_base_to_response

    knowledge_base = KnowledgeBase(
        id="kb-1",
        workspace_id="ws-1",
        name="Docs",
        description="desc",
        status="active",
        embedding_model_id="emb-1",
        reranker_model_id="rerank-1",
        created_by_user_id="user-1",
    )
    response = knowledge_base_to_response(knowledge_base, "edit")
    assert response.name == "Docs"
    assert response.embedding_model_id == "emb-1"
    assert response.permission == "edit"


# ---------------------------------------------------------------- mcp url


def test_normalize_mcp_url() -> None:
    from app.ports.mcp import McpClientError, normalize_mcp_url

    assert normalize_mcp_url("  https://tools.example.com/mcp/  ") == (
        "https://tools.example.com/mcp"
    )
    assert normalize_mcp_url("http://tools.example.com/sse") == (
        "http://tools.example.com/sse"
    )
    for invalid in (
        "file:///tmp/mcp.sock",
        "https://tools.example.com/mcp?token=secret",
        "https://tools.example.com/mcp#frag",
        "https://user:pass@tools.example.com/mcp",
        "ftp://tools.example.com/mcp",
    ):
        try:
            normalize_mcp_url(invalid)
        except McpClientError:
            continue
        raise AssertionError(f"Invalid MCP URL accepted: {invalid}")


def test_mcp_private_network_policy() -> None:
    from app.capabilities.mcp.client import (
        McpClientError,
        validate_mcp_destination,
    )

    asyncio.run(validate_mcp_destination("http://8.8.8.8/mcp", False))
    asyncio.run(validate_mcp_destination("http://127.0.0.1:8081/sse", True))
    try:
        asyncio.run(validate_mcp_destination("http://127.0.0.1:8081/sse", False))
    except McpClientError as exc:
        assert str(exc) == "Private MCP server addresses are not allowed."
    else:
        raise AssertionError("Private MCP address was accepted without opt-in")


def test_mcp_stdio_configuration() -> None:
    import os
    import sys

    from app.infrastructure.mcp_stdio import (
        McpStdioConfigError,
        parse_mcp_stdio_config,
        serialize_mcp_stdio_config,
        validate_mcp_stdio_config_runtime,
    )

    config = parse_mcp_stdio_config(
        {
            "command": sys.executable,
            "args": ["-m", "tests.unit"],
            "cwd": os.getcwd(),
            "env": {"NEXAFLOW_TEST_SECRET": "configured-in-form"},
        }
    )
    assert config.args == ("-m", "tests.unit")
    assert dict(config.env) == {"NEXAFLOW_TEST_SECRET": "configured-in-form"}
    assert parse_mcp_stdio_config(serialize_mcp_stdio_config(config)) == config
    validate_mcp_stdio_config_runtime(config)

    for invalid in (
        {"command": "relative-command"},
        {"command": sys.executable, "shell": True},
        {"command": sys.executable, "env": {"BAD=NAME": "value"}},
        {"command": sys.executable, "env": {"KEY": "bad\0value"}},
    ):
        try:
            parse_mcp_stdio_config(invalid)
        except McpStdioConfigError:
            continue
        raise AssertionError(f"Invalid stdio configuration accepted: {invalid}")


def test_mcp_server_create_request_transport_matrix() -> None:
    from pydantic import ValidationError

    from app.schemas.mcp import McpServerCreateRequest

    compatible = McpServerCreateRequest(
        name="Existing client",
        url="https://tools.example.com/mcp",
    )
    assert compatible.transport == "streamable_http"
    assert compatible.stdio_config is None

    sse = McpServerCreateRequest(
        name="Legacy SSE",
        transport="sse",
        url="https://tools.example.com/sse/",
        bearer_token="token",
    )
    assert sse.url == "https://tools.example.com/sse/"

    stdio = McpServerCreateRequest(
        name="Local",
        transport="stdio",
        stdio_config={"command": "/usr/bin/python3"},
    )
    assert stdio.url is None
    assert stdio.stdio_config is not None

    invalid_payloads = (
        {"name": "Missing URL", "transport": "sse"},
        {
            "name": "Remote profile",
            "url": "https://tools.example.com/mcp",
            "stdio_config": {"command": "/usr/bin/python3"},
        },
        {
            "name": "stdio URL",
            "transport": "stdio",
            "stdio_config": {"command": "/usr/bin/python3"},
            "url": "https://tools.example.com/mcp",
        },
        {
            "name": "stdio command",
            "transport": "stdio",
            "stdio_config": {"command": "/usr/bin/python3"},
            "command": "/bin/sh",
        },
        {
            "name": "legacy stdio profile",
            "transport": "stdio",
            "stdio_profile": "local-test",
        },
    )
    for payload in invalid_payloads:
        try:
            McpServerCreateRequest.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError(f"Invalid MCP server payload accepted: {payload}")


def main() -> None:
    test_effective_permission_matrix()
    test_validate_permission_rejects_unknown()
    test_knowledge_writes_recheck_locked_owner()
    test_clean_upload_filename_sanitizes_path_and_classification()
    test_parse_task_options_validates_boundaries()
    test_markdown_tables_split_only_between_rows_and_repeat_headers()
    test_markdown_table_keeps_single_overlong_row_intact()
    test_markdown_table_rules_apply_to_parent_and_child_chunks()
    test_docx_images_without_alt_text_do_not_add_placeholder_content()
    test_docx_image_mime_cannot_shape_asset_paths()
    test_archive_limits_run_before_document_conversion()
    test_supported_document_formats_are_accepted()
    test_pdf_documents_use_pymupdf_markdown_with_ocr()
    test_image_documents_use_pymupdf_ocr()
    test_webp_documents_are_normalized_for_pymupdf_ocr()
    test_reciprocal_rank_fusion_merges_and_ranks()
    test_reciprocal_rank_fusion_reports_named_rankings_deterministically()
    test_keyword_repository_uses_scoped_bm25_query()
    test_detailed_knowledge_query_contract_defaults()
    test_retrieval_evaluation_metrics_are_deterministic()
    test_evaluation_mutations_lock_before_validation_and_require_lease()
    test_evaluation_case_service_and_repository_edges()
    test_evaluation_result_upsert_recovers_concurrent_insert()
    test_evaluation_routes_delegate_to_application()
    test_qa_import_is_explicit_validated_and_bounded()
    test_explicit_reference_extraction_is_bounded_and_internal()
    test_reference_rebuild_reuses_resolution_context()
    test_parent_context_windows_around_child_offsets()
    test_model_type_normalization()
    test_status_validation()
    test_url_credential_validation()
    test_masked_secret_detection()
    test_provider_credentials_aws_pairing_rule()
    test_run_knowledge_model_test_uses_injected_providers()
    test_safe_agent_error_classification()
    test_agent_process_events_update_in_place()
    test_agent_event_replay_reads_every_page()
    test_stale_mcp_policy_requires_approval()
    test_external_mcp_policy_public_reconciles_like_console()
    test_external_mcp_policy_drift_requires_public_approval_but_blocks_api()
    test_external_stream_epoch_is_stable_and_sanitized()
    test_external_progress_events_carry_mcp_tool_details()
    test_external_progress_events_bound_tool_inputs_and_pass_output()
    test_mcp_policy_concurrent_first_write_reloads_existing()
    test_mcp_function_name_is_stable_and_sanitized()
    test_run_to_response_maps_run_fields()
    test_agent_usage_normalizes_provider_metadata()
    test_agent_memory_compacts_old_turns()
    test_agent_memory_query_is_bounded_and_projected()
    test_mcp_server_to_response()
    test_celery_worker_pool_is_fork_safe_without_prefork()
    test_worker_database_rejects_in_memory_sqlite()
    test_windows_event_loop_policy_is_selector_based()
    test_agent_live_stream_round_trip()
    test_team_to_response()
    test_knowledge_document_and_attachment_response_mapping()
    test_knowledge_base_to_response()
    test_normalize_mcp_url()
    test_mcp_private_network_policy()
    test_mcp_stdio_configuration()
    test_mcp_server_create_request_transport_matrix()
    print("UNIT_SUITE_OK")


if __name__ == "__main__":
    main()
