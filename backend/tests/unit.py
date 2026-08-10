"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
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
    parent_context,
    reciprocal_rank_fusion,
)
from app.capabilities.rag.vector_store import VectorHit
from app.entities.knowledge import KnowledgeBase
from app.entities.user import User
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

    async def get_user_grant(db, knowledge_base, user_id, resource_type):
        return None

    original_lock = knowledge_kb.knowledge_base_repository.lock_knowledge_base
    original_grant = knowledge_kb.knowledge_base_repository.get_user_grant
    knowledge_kb.knowledge_base_repository.lock_knowledge_base = lock_knowledge_base
    knowledge_kb.knowledge_base_repository.get_user_grant = get_user_grant

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
        knowledge_kb.knowledge_base_repository.get_user_grant = original_grant


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


def test_celery_worker_pool_is_fork_safe_on_macos() -> None:
    from app.infrastructure.celery import worker_pool_for_platform

    assert worker_pool_for_platform("darwin") == "solo"
    assert worker_pool_for_platform("linux") == "prefork"


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
    test_docx_images_without_alt_text_do_not_add_placeholder_content()
    test_supported_document_formats_are_accepted()
    test_pdf_documents_use_pymupdf_markdown_with_ocr()
    test_image_documents_use_pymupdf_ocr()
    test_webp_documents_are_normalized_for_pymupdf_ocr()
    test_reciprocal_rank_fusion_merges_and_ranks()
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
    test_mcp_policy_concurrent_first_write_reloads_existing()
    test_mcp_function_name_is_stable_and_sanitized()
    test_run_to_response_maps_run_fields()
    test_agent_usage_normalizes_provider_metadata()
    test_agent_memory_compacts_old_turns()
    test_agent_memory_query_is_bounded_and_projected()
    test_mcp_server_to_response()
    test_celery_worker_pool_is_fork_safe_on_macos()
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
