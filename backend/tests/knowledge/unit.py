"""Pure unit tests for the knowledge feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.knowledge.unit
"""
import tests.support  # noqa: F401  (sets required env before app imports)

"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.adapters.rag.vector_store import VectorHit
from app.domain.knowledge.documents.parsing import (
    KnowledgePipelineError,
)
from app.domain.knowledge.retrieval import (
    MAX_PARENT_CONTEXT_CHARS,
    RankedHit,
    bounded_text_chunks,
    parent_context,
    parent_evidence,
    reciprocal_rank_fusion,
)
from app.domain.knowledge.service import (
    clean_upload_filename,
    effective_permission,
    validate_permission,
)
from app.domain.knowledge.tasks.orchestration import (
    normalized_document_artifact,
    parse_task_options,
)
from app.entities.identity.user import User
from app.entities.knowledge import KnowledgeBase


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError("expected HTTPException")

def payload_with(**fields):
    return SimpleNamespace(model_dump=lambda: fields)

def test_effective_permission_matrix() -> None:
    knowledge_base = KnowledgeBase(
        id="kb-1",
        workspace_id="ws-1",
        created_by_user_id="owner-1",
    )
    owner = User(id="owner-1", username="owner")
    other = User(id="other-1", username="other")
    global_admin = User(id="super-1", username="super", is_global_admin=True)

    # the owner always gets edit
    assert effective_permission(knowledge_base, owner) == "edit"
    # roles never widen resource access, not even for system admins
    assert effective_permission(knowledge_base, other) == "none"
    assert effective_permission(knowledge_base, global_admin) == "none"
    # explicit grants are the only sharing path
    grant = SimpleNamespace(permission="view")
    assert effective_permission(knowledge_base, other, grant=grant) == "view"
    assert effective_permission(knowledge_base, global_admin, grant=grant) == "view"

def test_validate_permission_rejects_unknown() -> None:
    expect_http_error(lambda: validate_permission("delete"), 422)


def test_normalized_document_artifact_is_content_addressed() -> None:
    artifact = normalized_document_artifact(
        workspace_id="ws-1",
        knowledge_base_id="kb-1",
        document_id="doc-1",
        text="# 制度 A\n\n离职审批由人力资源部负责。",
    )
    assert artifact.object_key.startswith("ws-1/kb-1/normalized/doc-1/")
    assert artifact.object_key.endswith(".md")
    assert len(artifact.content_hash) == 64
    assert artifact.content == "# 制度 A\n\n离职审批由人力资源部负责。"


def test_knowledge_writes_recheck_locked_owner() -> None:
    from app.domain.knowledge.bases import service as knowledge_kb
    from app.schemas.knowledge import KnowledgeBaseUpdateRequest

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

def test_parse_task_options_validates_boundaries() -> None:
    assert parse_task_options() == {
        "strategy": "hierarchical",
        "chunk_size": 1200,
        "chunk_overlap": 150,
        "split_separator": "\n\n",
        "cleaning_rules": ["trim_lines", "remove_empty_lines"],
        "auto_index": True,
    }
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
    from app.domain.knowledge.documents.parsing import split_text

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
    from app.domain.knowledge.documents.parsing import split_text

    long_cell = "word " * 30
    row = f"| 1 | {long_cell.strip()} |"
    table = f"| ID | Notes |\n| --- | --- |\n{row}"

    chunks = split_text(table, chunk_size=40, overlap=0)

    assert len(chunks) == 1
    assert row in chunks[0]

def test_markdown_table_rules_apply_to_parent_and_child_chunks() -> None:
    from app.domain.knowledge.documents.parsing import (
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

def test_plain_legal_headings_keep_chapters_in_separate_parents() -> None:
    from app.domain.knowledge.documents.parsing import split_parent_chunks

    text = (
        "第一章 总则\n第一条 说明。\n"
        "第二章 校外培训处罚\n第十五条 处罚十五。\n第十六条 处罚十六。\n"
        "第三章 法律责任\n第十七条 责任。"
    )
    parents = split_parent_chunks(text, max_size=5000)

    assert [parent.title for parent in parents] == [
        "第一章 总则",
        "第二章 校外培训处罚",
        "第三章 法律责任",
    ]
    chapter_two = parents[1].content
    assert "第十六条" in chapter_two
    assert "第三章" not in chapter_two
    numbered = split_parent_chunks(
        "第二章 总则\n（一）适用范围。\n1、说明。\n第二节 细则\n第二条 内容。",
        max_size=5000,
    )
    assert len(numbered) == 2
    assert numbered[0].section_path == ["第二章 总则"]
    assert numbered[1].section_path == ["第二章 总则", "第二节 细则"]

def test_evidence_windows_mark_truncation_and_preserve_article_boundary() -> None:
    from types import SimpleNamespace

    content = (
        "第一章\n"
        + "第十五条 "
        + "x" * 60
        + "\n"
        + "第十六条 "
        + "y" * 60
        + "\n第三章\n"
    )
    chunk = SimpleNamespace(
        start_offset=content.index("第十六条"),
        end_offset=content.index("第十六条") + len("第十六条"),
    )
    window = parent_evidence(
        SimpleNamespace(content=content),
        chunk,
        max_chars=100,
    )
    assert window.truncated is True
    assert "第十六条" in window.content
    assert "[… evidence truncated …]" in window.content

    cjk_content = "甲" * 1_000
    cjk_chunk = SimpleNamespace(start_offset=900, end_offset=950)
    cjk_window = parent_evidence(
        SimpleNamespace(content=cjk_content),
        cjk_chunk,
        max_chars=100,
    )
    assert cjk_window.start_offset <= cjk_chunk.start_offset
    assert cjk_chunk.end_offset <= cjk_window.end_offset
    assert len(cjk_window.content) <= 100

    joined, truncated, ids = bounded_text_chunks(
        [("chunk-1", "a" * 60), ("chunk-2", "b" * 60)],
        max_chars=100,
    )
    assert truncated is True
    assert ids == ["chunk-1"]
    assert joined.endswith("[… evidence truncated …]")


def test_docx_images_without_alt_text_do_not_add_placeholder_content() -> None:
    from io import BytesIO
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from app.domain.knowledge.documents import parsing as pipeline

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
            patch(
                "markitdown.converters._docx_converter.pre_process_docx",
                lambda stream: stream,
            ),
            patch.object(pipeline.mammoth.images, "img_element", lambda callback: callback),
            patch.object(pipeline.mammoth, "convert_to_html", fake_convert_to_html),
            patch(
                "markitdown.converters._html_converter.HtmlConverter.convert_string",
                fake_convert_string,
            ),
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

    from app.domain.knowledge.documents import parsing as pipeline

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
            patch(
                "markitdown.converters._docx_converter.pre_process_docx",
                lambda stream: stream,
            ),
            patch.object(pipeline.mammoth.images, "img_element", lambda callback: callback),
            patch.object(pipeline.mammoth, "convert_to_html", fake_convert_to_html),
            patch(
                "markitdown.converters._html_converter.HtmlConverter.convert_string",
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
    from zipfile import ZIP_DEFLATED, ZipFile

    from app.domain.knowledge.documents import parsing as pipeline

    with TemporaryDirectory() as directory:
        path = Path(directory) / "expanded.zip"
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("large.txt", b"x" * 9)

        with patch.object(
            pipeline,
            "MAX_ARCHIVE_UNCOMPRESSED_BYTES",
            8,
            create=True,
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

    from app.domain.knowledge.documents import parsing as pipeline

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
        ".zip",
    }
    assert expected_extensions == pipeline.SUPPORTED_DOCUMENT_EXTENSIONS

    def fake_convert_local(*_args, **_kwargs):
        return SimpleNamespace(text_content="converted")

    with TemporaryDirectory() as directory:
        for extension in expected_extensions - {
            ".docx",
            ".pdf",
            ".md",
            ".markdown",
            ".txt",
            ".json",
            ".xml",
        }:
            path = Path(directory) / f"document{extension}"
            path.write_bytes(b"content")
            with patch.object(
                pipeline,
                "markitdown_converter",
                return_value=SimpleNamespace(convert_local=fake_convert_local),
            ):
                text, assets = pipeline.extract_document(
                    path.name,
                    "application/octet-stream",
                    path,
                )
            assert text == "converted"
            assert assets == []

        source_samples = {
            ".md": ("# Existing\n\nBody", "# Existing\n\nBody"),
            ".markdown": ("**Body**", "**Body**"),
            ".txt": ("plain body", "plain body"),
            ".json": (
                '{"value": "```"}',
                '# document\n\n````json\n{"value": "```"}\n````',
            ),
            ".xml": (
                "<root><value>1</value></root>",
                "# document\n\n```xml\n<root><value>1</value></root>\n```",
            ),
        }
        for extension, (source, expected) in source_samples.items():
            path = Path(directory) / f"document{extension}"
            path.write_text(source, encoding="utf-8")
            text, assets = pipeline.extract_document(
                path.name,
                "application/octet-stream",
                path,
            )
            assert text == expected
            assert assets == []

        for extension in {".py", ".ipynb", ".epub", ".png"}:
            path = Path(directory) / f"unsupported{extension}"
            path.write_bytes(b"content")
            try:
                pipeline.extract_document(
                    path.name,
                    "application/octet-stream",
                    path,
                )
            except pipeline.KnowledgePipelineError as exc:
                assert str(exc) == "Document format is not supported."
            else:
                raise AssertionError(f"Unsupported format accepted: {extension}")

def test_pdf_documents_extract_only_the_text_layer() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from app.domain.knowledge.documents import parsing as pipeline

    with TemporaryDirectory() as directory:
        path = Path(directory) / "通知.pdf"
        path.write_bytes(b"pdf")
        page = SimpleNamespace(
            extract_text=lambda: "提 高 思想 认识， 压 实 防 灾 责 任。"
        )
        with patch(
            "pypdf.PdfReader",
            return_value=SimpleNamespace(pages=[page]),
        ) as reader:
            text, assets = pipeline.extract_document(
                path.name,
                "application/pdf",
                path,
            )

        assert text == "# 通知\n\n提高思想认识，压实防灾责任。"
        assert assets == []
        reader.assert_called_once_with(path)

        empty_page = SimpleNamespace(extract_text=lambda: None)
        with patch(
            "pypdf.PdfReader",
            return_value=SimpleNamespace(pages=[empty_page]),
        ):
            try:
                pipeline.extract_document(path.name, "application/pdf", path)
            except pipeline.KnowledgePipelineError as exc:
                assert "no extractable text" in str(exc)
            else:
                raise AssertionError("Scanned PDF without a text layer was accepted")

def test_image_documents_use_the_configured_vision_extractor() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from app.domain.knowledge.documents import parsing as pipeline

    with TemporaryDirectory() as directory:
        path = Path(directory) / "通知.png"
        path.write_bytes(b"png")
        calls: list[tuple[str, bytes]] = []

        def extract_image(media_type: str, content: bytes) -> str:
            calls.append((media_type, content))
            return "识 别 文 本"

        text, assets = pipeline.extract_document(
            path.name,
            "image/png",
            path,
            image_text_extractor=extract_image,
            supported_extensions=pipeline.EXTRACTABLE_DOCUMENT_EXTENSIONS,
        )

        assert text == "# 通知\n\n识别文本"
        assert assets == []
        assert calls == [("image/png", b"png")]

        try:
            pipeline.extract_document(
                path.name,
                "image/png",
                path,
                supported_extensions=pipeline.EXTRACTABLE_DOCUMENT_EXTENSIONS,
            )
        except pipeline.KnowledgePipelineError as exc:
            assert str(exc) == "Vision model is not configured for this workspace."
        else:
            raise AssertionError("Image parsing without a vision model was accepted")

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
        [VectorHit(chunk_id="a", distance=0.2), VectorHit(chunk_id="b", distance=0.3)],
        ["b", "c"],
    )
    assert [hit.chunk_id for hit in ranked] == ["b", "a", "c"]
    assert ranked[0] == RankedHit(
        chunk_id="b", distance=0.3, rrf_score=1 / 62 + 1 / 61,
        vector_rank=2, keyword_rank=1, sources=("vector", "keywords"),
    )
    try:
        ranked[0].rrf_score = 0  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("Ranked hits must be immutable.")


def test_keyword_repository_uses_scoped_bm25_query() -> None:
    from app.infra.db.repositories.knowledge import repository as knowledge_repository

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
        "section_path": [],
        "chunk_index": 0,
        "content": "answer",
        "content_truncated": False,
        "evidence_start_offset": None,
        "evidence_end_offset": None,
        "contributing_chunk_ids": [],
        "distance": None,
        "similarity": None,
        "kind": "document",
        "question": None,
        "source": None,
        "sources": [],
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
        fused_candidates=2,
        rerank_status="not_configured",
        returned_hits=1,
        duration_ms=1.25,
        stage_duration_ms={"retrieve": 0.5, "assemble": 0.75},
    )
    dumped_trace = trace.model_dump()
    assert "query" not in dumped_trace
    assert all("hash" not in field for field in dumped_trace)
    assert not any(field.startswith("graph") for field in dumped_trace)
    inspect = KnowledgeQueryInspectResponse(hits=[hit], trace=trace)
    assert inspect.trace is trace
    assert "graph" not in inspect.model_dump()

def test_retrieval_evaluation_metrics_are_deterministic() -> None:
    from app.domain.knowledge.evaluation.metrics import (
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
    from app.application.knowledge.evaluation import runner as evaluation_application
    from app.domain.knowledge.evaluation import service as evaluation_service
    from app.entities.knowledge import KnowledgeTask
    from app.schemas.knowledge import KnowledgeEvaluationRunRequest

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
    from app.domain.knowledge.evaluation import service as evaluation_service
    from app.entities.knowledge import (
        KnowledgeEvaluationCase,
        KnowledgeEvaluationExpectation,
        KnowledgeTask,
    )
    from app.infra.db.repositories.knowledge import (
        evaluation as evaluation_repository,
    )
    from app.schemas.knowledge import KnowledgeEvaluationCaseCreateRequest

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

    from app.domain.knowledge.models import (
        KnowledgeEvaluationResult as KnowledgeEvaluationResultORM,
    )
    from app.entities.knowledge import KnowledgeEvaluationResult
    from app.infra.db.repositories.knowledge import (
        evaluation as evaluation_repository,
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
    from app.api.v1.knowledge import evaluation as evaluation_api
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

    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference

    from app.domain.knowledge.documents.parsing import KnowledgePipelineError
    from app.domain.knowledge.documents.qa_import import (
        QaRow,
        extract_qa_rows,
        qa_rows_to_markdown,
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
        assert qa_rows_to_markdown(csv_path.name, expected) == (
            "# qa\n\n"
            "## Question 1\n\n"
            "如何回滚？\n\n"
            "**Answer**\n\n"
            "需要管理员批准。\n\n"
            "**Source**\n\n"
            "运维手册 3.2"
        )
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
            "app.domain.knowledge.documents.qa_import.load_workbook",
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

def test_knowledge_document_and_attachment_response_mapping() -> None:
    from app.domain.knowledge.service import (
        attachment_to_response,
        document_to_response,
    )
    from app.entities.knowledge import KnowledgeAttachment, KnowledgeDocument

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
    from app.domain.knowledge.service import knowledge_base_to_response
    from app.entities.knowledge import KnowledgeBase

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


def main() -> None:
    test_effective_permission_matrix()
    test_validate_permission_rejects_unknown()
    test_normalized_document_artifact_is_content_addressed()
    test_knowledge_writes_recheck_locked_owner()
    test_clean_upload_filename_sanitizes_path_and_classification()
    test_parse_task_options_validates_boundaries()
    test_markdown_tables_split_only_between_rows_and_repeat_headers()
    test_markdown_table_keeps_single_overlong_row_intact()
    test_markdown_table_rules_apply_to_parent_and_child_chunks()
    test_plain_legal_headings_keep_chapters_in_separate_parents()
    test_evidence_windows_mark_truncation_and_preserve_article_boundary()
    test_docx_images_without_alt_text_do_not_add_placeholder_content()
    test_docx_image_mime_cannot_shape_asset_paths()
    test_archive_limits_run_before_document_conversion()
    test_supported_document_formats_are_accepted()
    test_pdf_documents_extract_only_the_text_layer()
    test_image_documents_use_the_configured_vision_extractor()
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
    test_parent_context_windows_around_child_offsets()
    test_knowledge_document_and_attachment_response_mapping()
    test_knowledge_base_to_response()
    print("KNOWLEDGE_UNIT_OK")


if __name__ == "__main__":
    main()
