"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace

import tests.support  # noqa: F401  (sets required env before app imports)

from fastapi import HTTPException

from app.application.knowledge_graph_build import (
    charged_graph_tokens,
    estimate_graph_call_tokens,
)
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
    bounded_text_chunks,
    parent_evidence,
    parent_context,
    reciprocal_rank_fusion,
)
from app.capabilities.rag.vector_store import VectorHit
from app.entities.agents import Agent
from app.entities.knowledge import KnowledgeBase
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User
from app.schemas.knowledge_graph import (
    KnowledgeGraphImportRecord,
    KnowledgeGraphReviewDecisionRequest,
)
from app.shareddomain.agents.permissions import (
    effective_agent_permission,
    validate_agent_permission,
)
from app.shareddomain.knowledge.orchestration import (
    normalized_document_artifact,
    parse_task_options,
)
from app.shareddomain.knowledge.services import (
    clean_upload_filename,
    effective_permission,
    validate_permission,
)
from app.shareddomain.knowledge_graph.schema import (
    GraphSchemaDefinition,
    default_policy_graph_schema,
    graph_schema_hash,
    normalize_graph_name,
)
from app.shareddomain.knowledge_graph.extraction import (
    ExtractionChunk,
    GraphExtractionBatch,
    extract_graph_batch,
    validate_extraction_batch,
)
from app.shareddomain.knowledge_graph.resolution import (
    claim_fingerprint,
    choose_automatic_entity_match,
    initial_claim_status,
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


def test_graph_schema_rejects_unknown_relation_endpoint() -> None:
    try:
        GraphSchemaDefinition.model_validate(
            {
                "entity_types": [{"name": "Document", "properties": []}],
                "relations": [
                    {
                        "name": "defines",
                        "source_types": ["Missing"],
                        "target_types": ["Document"],
                        "traversable": True,
                    }
                ],
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unknown endpoint type must fail")


def test_default_policy_graph_schema_is_stable() -> None:
    schema = default_policy_graph_schema()
    assert schema.relation("supersedes").traversable is True
    assert schema.relation("conflicts_with").review_required is True
    assert normalize_graph_name("  信息\u3000科技部 ") == "信息 科技部"
    assert graph_schema_hash(schema) == graph_schema_hash(schema)


def test_graph_token_charge_uses_reported_or_conservative_estimate() -> None:
    assert charged_graph_tokens({"total_tokens": 120}, 500) == (120, False)
    assert charged_graph_tokens({"total_tokens": 0}, 500) == (500, True)
    assert estimate_graph_call_tokens(
        [{"role": "user", "content": "制度" * 1000}]
    ) >= 1000


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


def test_graph_extraction_requires_exact_chunk_evidence() -> None:
    content = "账户 A 与账户 B 共用手机号 P。"
    quote = "账户 A 与账户 B 共用手机号 P"
    chunks = [
        ExtractionChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            content=content,
        )
    ]
    valid = GraphExtractionBatch.model_validate(
        {
            "entities": [
                {
                    "temp_id": "a",
                    "entity_type": "Account",
                    "canonical_name": "账户 A",
                    "aliases": [],
                },
                {
                    "temp_id": "p",
                    "entity_type": "Phone",
                    "canonical_name": "手机号 P",
                    "aliases": [],
                },
            ],
            "claims": [
                {
                    "subject_temp_id": "a",
                    "predicate": "uses_phone",
                    "object_temp_id": "p",
                    "object_value": None,
                    "evidence_chunk_id": "chunk-1",
                    "quote": quote,
                    "start_offset": content.index(quote),
                    "end_offset": content.index(quote) + len(quote),
                }
            ],
        }
    )
    assert validate_extraction_batch(valid, chunks).claims[0].predicate == "uses_phone"

    invalid = valid.model_copy(deep=True)
    invalid.claims[0].quote = "账户 A 登录设备 D"
    try:
        validate_extraction_batch(invalid, chunks)
    except ValueError as exc:
        assert "quote" in str(exc).lower()
    else:
        raise AssertionError("unsupported graph evidence must fail")


def test_graph_extractor_parses_bounded_json_only_response() -> None:
    content = "账户 A 使用手机号 P。"
    quote = "账户 A 使用手机号 P"
    payload = {
        "entities": [
            {
                "temp_id": "a",
                "entity_type": "Account",
                "canonical_name": "账户 A",
            },
            {
                "temp_id": "p",
                "entity_type": "Phone",
                "canonical_name": "手机号 P",
            },
        ],
        "claims": [
            {
                "subject_temp_id": "a",
                "predicate": "uses_phone",
                "object_temp_id": "p",
                "evidence_chunk_id": "chunk-1",
                "quote": quote,
                "start_offset": 0,
                "end_offset": len(quote),
            }
        ],
    }

    class Provider:
        prompt = None

        async def ainvoke(self, messages, **kwargs):
            self.prompt = messages
            assert kwargs == {"max_tokens": 4096}
            return SimpleNamespace(
                text=f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```",
                usage_metadata={"input_tokens": 12, "output_tokens": 8},
            )

    provider = Provider()
    schema = GraphSchemaDefinition.model_validate(
        {
            "entity_types": [
                {"name": "Account"},
                {"name": "Phone"},
            ],
            "relations": [
                {
                    "name": "uses_phone",
                    "source_types": ["Account"],
                    "target_types": ["Phone"],
                }
            ],
        }
    )
    result = asyncio.run(
        extract_graph_batch(
            provider,
            schema,
            [
                ExtractionChunk(f"chunk-{index}", "doc-1", content)
                for index in range(1, 6)
            ],
        )
    )
    assert result.batch.claims[0].predicate == "uses_phone"
    assert len(result.prompt_hash) == 64
    assert result.model_usage["total_tokens"] == 20
    assert provider.prompt is not None
    assert "chunk-5" not in provider.prompt[1]["content"]
    assert len(json.loads(provider.prompt[1]["content"])) == 1


def test_graph_extractor_rejects_oversized_input_without_truncating_json() -> None:
    class Provider:
        called = False

        async def ainvoke(self, messages, **kwargs):
            self.called = True
            return SimpleNamespace(text='{"entities": [], "claims": []}')

    provider = Provider()
    schema = default_policy_graph_schema()
    try:
        asyncio.run(
            extract_graph_batch(
                provider,
                schema,
                [ExtractionChunk("large", "doc-1", "x" * 25_000)],
            )
        )
    except ValueError as exc:
        assert str(exc) == "Graph extraction input exceeds the per-call limit."
    else:
        raise AssertionError("oversized extraction input must be rejected")
    assert provider.called is False


def test_graph_extractor_retries_invalid_model_output_once() -> None:
    quote = "制度 A 定义术语 A。"
    valid = {
        "entities": [
            {
                "temp_id": "policy",
                "entity_type": "Document",
                "canonical_name": "制度 A",
            },
            {
                "temp_id": "term",
                "entity_type": "Concept",
                "canonical_name": "术语 A",
            },
        ],
        "claims": [
            {
                "subject_temp_id": "policy",
                "predicate": "defines",
                "object_temp_id": "term",
                "evidence_chunk_id": "chunk-1",
                "quote": quote,
                "start_offset": 0,
                "end_offset": len(quote),
            }
        ],
    }

    class Provider:
        calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            assert kwargs == {"max_tokens": 4096}
            if self.calls == 1:
                return SimpleNamespace(text="not json")
            assert "failed server validation" in messages[-1]["content"]
            return SimpleNamespace(text=json.dumps(valid, ensure_ascii=False))

    provider = Provider()
    result = asyncio.run(
        extract_graph_batch(
            provider,
            default_policy_graph_schema(),
            [ExtractionChunk("chunk-1", "doc-1", quote)],
        )
    )
    assert provider.calls == 2
    assert result.batch.claims[0].predicate == "defines"


def test_graph_extractor_does_not_retry_provider_failure() -> None:
    from app.ports.llm import ModelProviderStatusError

    class Provider:
        calls = 0

        async def ainvoke(self, _messages, **_kwargs):
            self.calls += 1
            raise ModelProviderStatusError(402, "Insufficient Balance")

    provider = Provider()
    try:
        asyncio.run(
            extract_graph_batch(
                provider,
                default_policy_graph_schema(),
                [ExtractionChunk("chunk-1", "doc-1", "制度 A 定义术语 A。")],
            )
        )
    except ModelProviderStatusError as exc:
        assert exc.status_code == 402
    else:
        raise AssertionError("provider failures must stop graph extraction")
    assert provider.calls == 1


def test_graph_entity_auto_match_requires_deterministic_identity() -> None:
    candidates = [
        SimpleNamespace(id="e1", external_key=None, normalized_name="张三"),
        SimpleNamespace(id="e2", external_key=None, normalized_name="张三"),
    ]
    assert choose_automatic_entity_match(None, "张三", candidates) is None
    match = choose_automatic_entity_match(
        "acct-1",
        "账户 A",
        [
            SimpleNamespace(
                id="e3",
                external_key="acct-1",
                normalized_name="账户 a",
            )
        ],
    )
    assert match is not None
    assert match.id == "e3"
    assert (
        choose_automatic_entity_match(
            "missing-key",
            "账户 A",
            [
                SimpleNamespace(
                    id="e4",
                    external_key=None,
                    normalized_name="账户 a",
                )
            ],
        )
        is None
    )
    alias_match = choose_automatic_entity_match(
        None,
        "HR",
        [
            SimpleNamespace(
                id="name-match",
                external_key=None,
                normalized_name="hr",
            ),
            SimpleNamespace(
                id="human-alias-match",
                external_key=None,
                normalized_name="人力资源部",
            ),
        ],
        {"human-alias-match"},
    )
    assert alias_match is not None
    assert alias_match.id == "human-alias-match"


def test_graph_claim_fingerprint_and_initial_status_are_deterministic() -> None:
    forward = claim_fingerprint("a", "owns", "b", None, None, None)
    reverse = claim_fingerprint("b", "owns", "a", None, None, None)
    assert forward != reverse
    assert initial_claim_status(
        source_kind="explicit_text",
        relation_review_required=False,
        subject_resolved=True,
        object_resolved=True,
        evidence_verified=True,
    ) == ("active", None)
    assert initial_claim_status(
        source_kind="explicit_text",
        relation_review_required=False,
        subject_resolved=False,
        object_resolved=True,
        evidence_verified=True,
    ) == ("candidate", "ambiguous_entity")


def test_graph_review_decision_request_is_bounded() -> None:
    request = KnowledgeGraphReviewDecisionRequest.model_validate(
        {"action": "merge_entities", "target_entity_id": "entity-1"}
    )
    assert request.mention_ids == []
    try:
        KnowledgeGraphReviewDecisionRequest.model_validate(
            {"action": "split_entity", "mention_ids": ["mention"] * 501}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("oversized graph review decision must fail")
    try:
        KnowledgeGraphReviewDecisionRequest.model_validate(
            {
                "action": "split_entity",
                "canonical_name": " ",
                "entity_type": "Document",
                "mention_ids": ["mention"],
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("blank split names must fail")


def test_graph_import_record_requires_one_object_kind() -> None:
    record = KnowledgeGraphImportRecord.model_validate(
        {
            "subject": {
                "entity_type": "Document",
                "canonical_name": "制度 A",
            },
            "predicate": "defines",
            "value": "术语 A",
        }
    )
    assert record.object is None
    for payload in (
        {
            "subject": {"entity_type": "Document", "canonical_name": "制度 A"},
            "predicate": "defines",
        },
        {
            "subject": {"entity_type": "Document", "canonical_name": "制度 A"},
            "predicate": "defines",
            "object": {"entity_type": "Concept", "canonical_name": "术语 A"},
            "value": "duplicate",
        },
    ):
        try:
            KnowledgeGraphImportRecord.model_validate(payload)
        except ValueError:
            continue
        raise AssertionError("structured graph object XOR must be enforced")


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


def test_tool_ref_requires_stable_ids() -> None:
    from app.entities.tools import ToolRef

    reference = ToolRef(tool_id="tool-1", version_id="version-1")
    assert reference.tool_id == "tool-1"
    assert reference.version_id == "version-1"

    for fields in (
        {"tool_id": "", "version_id": "version-1"},
        {"tool_id": "tool-1", "version_id": "   "},
        {"tool_id": None, "version_id": "version-1"},
        {"tool_id": "tool-1", "version_id": 1},
    ):
        try:
            ToolRef(**fields)
        except ValueError:
            continue
        raise AssertionError(f"Invalid ToolRef accepted: {fields}")

    try:
        reference.version_id = "version-2"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("ToolRef must be immutable.")


def test_agent_publication_snapshot_is_canonical_and_tool_versioned() -> None:
    from app.entities.agents import AgentPublicationVersion, AgentRun
    from app.entities.tools import ToolSnapshot
    from app.shareddomain.agents.services import agent_publication_from_version
    from app.shareddomain.agents.publications import (
        agent_publication_hash,
        build_agent_configuration_snapshot,
        build_agent_resource_snapshot,
        publication_from_snapshots,
    )

    agent = Agent(
        id="agent-1",
        workspace_id="ws-1",
        name="Research",
        description="Searches releases.",
        interaction_config={"prologue": "Hello"},
        instructions="Use tools when needed.",
        model_id="model-1",
        knowledge_query_mode="required",
    )
    first = ToolSnapshot(
        schema_version=1,
        tool_id="tool-b",
        version_id="version-b",
        source_id="source-1",
        kind="python",
        function_name="second",
        display_name="Second",
        description="",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-b",
        policy_id="policy-b",
        policy_revision=2,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = {}"},
    )
    second = ToolSnapshot(
        **{
            **first.__dict__,
            "tool_id": "tool-a",
            "version_id": "version-a",
            "function_name": "first",
            "definition_hash": "hash-a",
            "policy_id": "policy-a",
        }
    )

    configuration = build_agent_configuration_snapshot(agent)
    resources = build_agent_resource_snapshot(
        ["kb-b", "kb-a"],
        [first, second],
    )
    reordered = build_agent_resource_snapshot(
        ["kb-a", "kb-b"],
        [second, first],
    )
    assert resources == reordered
    assert [item["tool_id"] for item in resources["tools"]] == ["tool-a", "tool-b"]
    assert agent_publication_hash(configuration, resources) == agent_publication_hash(
        configuration,
        reordered,
    )

    publication = publication_from_snapshots(configuration, resources)
    assert publication.name == "Research"
    assert publication.knowledge_base_ids == ["kb-a", "kb-b"]
    assert [item.tool_id for item in publication.tools] == ["tool-a", "tool-b"]

    version = AgentPublicationVersion(
        workspace_id="ws-1",
        agent_id="agent-1",
        version_number=1,
        schema_version=1,
        configuration_snapshot=configuration,
        resource_snapshot=resources,
        configuration_hash=agent_publication_hash(configuration, resources),
        published_by_user_id="user-1",
    )
    run = AgentRun(
        workspace_id="ws-1",
        agent_id="agent-1",
        configuration_source="published",
        agent_publication_version_id=version.id,
        snapshot_schema_version=version.schema_version,
        application_snapshot={
            "configuration": configuration,
            "resources": resources,
        },
        application_snapshot_hash=version.configuration_hash,
        tool_snapshots=resources["tools"],
    )
    assert run.agent_publication_version_id == version.id
    assert run.configuration_source == "published"
    assert agent_publication_from_version(version).name == agent.name
    version.configuration_hash = "0" * 64
    try:
        agent_publication_from_version(version)
    except ValueError:
        pass
    else:
        raise AssertionError("A drifted Agent publication version was accepted.")


def test_agent_tool_binding_requires_current_available_policy() -> None:
    from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion
    from app.shareddomain.tools.bindings import build_bindable_tool_snapshot

    source = ToolSource(id="source-1", workspace_id="ws-1", kind="python")
    tool = Tool(
        id="tool-1",
        workspace_id="ws-1",
        source_id=source.id,
        kind="python",
        function_name="lookup",
        current_version_id="version-1",
    )
    version = ToolVersion(
        id="version-1",
        workspace_id="ws-1",
        tool_id=tool.id,
        display_name="Lookup",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        execution_spec={"code": "result = {}"},
        definition_hash="hash-1",
    )
    policy = ToolPolicy(
        id="policy-1",
        workspace_id="ws-1",
        tool_id=tool.id,
        tool_version_id=version.id,
        definition_hash=version.definition_hash,
        approval="auto",
        effect="pure",
        allowed_access_sources=["console", "public", "api"],
        workflow_callable=True,
    )
    assert (
        build_bindable_tool_snapshot(tool, source, version, policy, "user-1").tool_id
        == tool.id
    )

    tool.current_version_id = "version-2"
    expect_http_error(
        lambda: build_bindable_tool_snapshot(
            tool, source, version, policy, "user-1"
        ),
        422,
    )
    tool.current_version_id = version.id
    policy.definition_hash = "drifted"
    expect_http_error(
        lambda: build_bindable_tool_snapshot(
            tool, source, version, policy, "user-1"
        ),
        422,
    )


def test_tool_snapshot_is_an_immutable_internal_contract() -> None:
    from app.entities.tools import ToolSnapshot

    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="python",
        function_name="lookup_order",
        display_name="Lookup order",
        description="Returns one order.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=3,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console", "workflow"),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = inputs"},
    )

    assert snapshot.kind == "python"
    assert snapshot.execution_spec == {"code": "result = inputs"}
    try:
        snapshot.definition_hash = "hash-2"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("ToolSnapshot must be immutable.")


def test_tool_contracts_deep_freeze_nested_json() -> None:
    import json
    from copy import copy, deepcopy
    from operator import setitem

    from app.entities.tools import ToolSnapshot, validate_tool_json_schema
    from app.ports.tool_runtime import ToolRuntimeResult

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "maxLength": 64,
                "examples": ["one"],
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "maxItems": 2,
                "items": {"type": "integer"},
            }
        },
        "additionalProperties": False,
    }
    execution_spec = {
        "provider": {"name": "python", "limits": [{"cpu": 1}]}
    }
    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="python",
        function_name="lookup_order",
        display_name="Lookup order",
        description="Returns one order.",
        input_schema=input_schema,
        output_schema=output_schema,
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=3,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec=execution_spec,
    )
    usage = {"tokens": {"input": 1}, "providers": ["sandbox"]}
    result = ToolRuntimeResult(
        ok=True,
        data={"items": [{"id": 1}]},
        summary="Done.",
        error_code=None,
        error_message=None,
        outcome="confirmed",
        usage=usage,
    )
    assert snapshot.output_schema is not None

    mutations = (
        (snapshot.input_schema, "type", "string"),
        (snapshot.input_schema["properties"], "extra", {}),
        (snapshot.input_schema["properties"]["query"], "maxLength", 1),
        (snapshot.input_schema["properties"]["query"]["examples"], 0, "two"),
        (snapshot.input_schema["required"], 0, "other"),
        (snapshot.output_schema, "type", "array"),
        (snapshot.output_schema["properties"]["items"], "maxItems", 3),
        (snapshot.execution_spec, "provider", {}),
        (snapshot.execution_spec["provider"], "name", "mcp"),
        (snapshot.execution_spec["provider"]["limits"], 0, {}),
        (result.data, "items", []),
        (result.data["items"], 0, {}),
        (result.data["items"][0], "id", 2),
        (result.usage, "tokens", {}),
        (result.usage["tokens"], "input", 2),
        (result.usage["providers"], 0, "remote"),
    )
    for target, key, value in mutations:
        try:
            setitem(target, key, value)
        except TypeError:
            continue
        raise AssertionError(f"Nested Tool JSON remained mutable: {target}")

    input_schema["required"][0] = "changed"
    execution_spec["provider"]["limits"][0]["cpu"] = 99
    usage["tokens"]["input"] = 99
    assert isinstance(snapshot.input_schema["required"], list)
    assert snapshot.input_schema["required"] == ["query"]
    assert snapshot.execution_spec["provider"]["limits"][0]["cpu"] == 1
    assert result.usage["tokens"]["input"] == 1

    for value in (
        snapshot.input_schema,
        snapshot.output_schema,
        snapshot.execution_spec,
        result.data,
        result.usage,
    ):
        json.loads(json.dumps(value))

    for value in (
        snapshot.input_schema,
        snapshot.input_schema["required"],
    ):
        assert copy(value) is value
        assert deepcopy(value) is value
    assert validate_tool_json_schema(snapshot.input_schema) == snapshot.input_schema


def test_freeze_json_rejects_non_json_values() -> None:
    from app.entities.tools import freeze_json

    source = {
        "values": (None, False, "text", 1, 1.5),
        "nested": [{"ok": True}],
    }
    frozen = freeze_json(source)
    assert frozen == {
        "values": [None, False, "text", 1, 1.5],
        "nested": [{"ok": True}],
    }
    assert frozen is not source
    assert frozen["nested"] is not source["nested"]

    for invalid in (
        {1: "non-string key"},
        {"value": {1, 2}},
        {"value": b"bytes"},
        {"value": object()},
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        try:
            freeze_json(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Non-JSON Tool value was accepted: {invalid!r}")


def test_tool_adapter_contract_is_provider_neutral() -> None:
    from datetime import datetime, timezone

    from app.entities.tools import ToolSnapshot
    from app.ports.tool_runtime import (
        ToolAdapter,
        ToolInvocationContext,
        ToolRuntimeResult,
    )

    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="builtin",
        function_name="current_time",
        display_name="Current time",
        description="Returns the current time.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=3,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=True,
        execution_spec={"builtin": "current_time"},
    )
    context = ToolInvocationContext(
        workspace_id="workspace-1",
        origin="agent",
        root_run_id="root-1",
        run_id="run-1",
        invocation_id="invocation-1",
        execution_user_id="user-1",
        access_source="console",
        deadline_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        idempotency_key="key-1",
    )

    class FakeAdapter:
        kind = "builtin"

        async def invoke(self, snapshot, arguments, context):
            assert snapshot.kind == self.kind
            assert arguments == {}
            assert context.workspace_id == "workspace-1"
            return ToolRuntimeResult(
                ok=True,
                data={"time": "2026-08-16T00:00:00Z"},
                summary="Current time returned.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )

    adapter = FakeAdapter()
    assert isinstance(adapter, ToolAdapter)
    result = asyncio.run(adapter.invoke(snapshot, {}, context))
    assert result.ok is True
    assert result.outcome == "confirmed"


def test_agent_tool_definition_comes_from_unified_snapshot() -> None:
    from app.application.agent_tools import build_unified_agent_tool
    from app.entities.tools import ToolSnapshot

    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="python",
        function_name="calculate_tax",
        display_name="Calculate tax",
        description="Calculate one tax amount.",
        input_schema={
            "type": "object",
            "properties": {"amount": {"type": "number"}},
            "required": ["amount"],
            "additionalProperties": False,
        },
        output_schema=None,
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=1,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = {'tax': inputs['amount'] * 0.1}"},
    )

    tool = build_unified_agent_tool(snapshot)

    assert tool.name == "calculate_tax"
    assert tool.description == "Calculate one tax amount."
    assert tool.args_schema == snapshot.input_schema
    assert tool.metadata == {
        "display_name": "Calculate tax",
        "kind": "python",
        "server_name": "",
        "parallel_safe": False,
        "policy_mode": "",
        "server_id": "",
        "definition_hash": "hash-1",
        "source_tool_name": "",
    }


def test_agent_tool_runtime_uses_stable_invocation_identity_and_envelope() -> None:
    import hashlib

    from app.application.agent_tool_runtime import (
        agent_tool_invocation_identity,
        tool_runtime_result_to_agent_result,
    )
    from app.ports.tool_runtime import ToolRuntimeResult

    invocation_id, idempotency_key = agent_tool_invocation_identity(
        "run-1",
        3,
        "call-7",
    )
    assert invocation_id == "3:call-7"
    assert idempotency_key == hashlib.sha256(
        b"agent:run-1:3:call-7"
    ).hexdigest()

    succeeded = tool_runtime_result_to_agent_result(
        ToolRuntimeResult(
            ok=True,
            data={"total": 12},
            summary="Calculated.",
            error_code=None,
            error_message=None,
            outcome="confirmed",
            usage={},
        )
    )
    assert succeeded.content == '{"total": 12}'
    assert succeeded.output == {"total": 12}
    assert succeeded.is_error is False

    uncertain = tool_runtime_result_to_agent_result(
        ToolRuntimeResult(
            ok=False,
            data=None,
            summary="Request state is unknown.",
            error_code="tool_outcome_uncertain",
            error_message="Request state is unknown.",
            outcome="uncertain",
            usage={},
        )
    )
    assert uncertain.content == "Request state is unknown."
    assert uncertain.is_error is True
    assert uncertain.outcome_uncertain is True


def test_agent_tool_call_migration_preserves_approval_gate() -> None:
    import importlib.util
    from datetime import UTC, datetime
    from pathlib import Path

    path = (
        Path(__file__).parents[1]
        / "alembic/versions/202608160005_agent_publication_versions.py"
    )
    spec = importlib.util.spec_from_file_location("agent_publication_versions", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration._migrated_tool_call_status("pending", "auto") == "queued"
    assert (
        migration._migrated_tool_call_status("pending", "each_call")
        == "awaiting_approval"
    )
    assert migration._migrated_tool_call_status("approved", "each_call") == "approved"

    assert migration._permission_backfill_action(None) == "insert"
    assert migration._permission_backfill_action("view") == "keep"
    assert migration._permission_backfill_action("use") == "keep"
    assert (
        migration._membership_history_revokes_fallback_grant(
            "workspace.member.remove", {"role": "member"}
        )
        is True
    )
    assert (
        migration._membership_history_revokes_fallback_grant(
            "workspace.member.update",
            {"previous_role": "admin", "role": "member"},
        )
        is True
    )
    assert (
        migration._membership_history_revokes_fallback_grant(
            "workspace.member.update",
            {"previous_role": "member", "role": "admin"},
        )
        is False
    )
    assert migration._agent_run_requires_drain("queued", "agent") is True
    assert migration._agent_run_requires_drain("running", "agent") is True
    assert migration._agent_run_requires_drain("succeeded", "agent") is False
    assert migration._agent_run_requires_drain("queued", "workflow") is False

    now = datetime(2026, 8, 17, tzinfo=UTC)
    assert migration._json_datetime(None) is None
    assert migration._json_datetime("not-a-date") is None
    assert migration._json_datetime(now.isoformat()) == now
    assert migration._json_datetime(now) == now

    configuration = {
        "name": "Published Agent",
        "description": "Frozen description",
        "instructions": "Frozen instructions",
        "model_id": "model-1",
        "knowledge_query_mode": "required",
        "interaction_config": {"prologue": "Hello"},
    }
    resources = {
        "knowledge_base_ids": ["kb-1"],
        "tools": [
            {
                "kind": "mcp",
                "execution_spec": {
                    "server_id": "server-1",
                    "tool_name": "lookup",
                },
            }
        ],
    }
    assert migration._legacy_publication_snapshot(configuration, resources) == {
        **configuration,
        "knowledge_base_ids": ["kb-1"],
        "mcp_tools": [{"server_id": "server-1", "tool_name": "lookup"}],
    }

    call = {
        "status": "pending",
        "approved_by_user_id": None,
        "approved_at": None,
        "result_output": None,
        "result_content": "",
        "result_summary": "",
        "result_is_error": False,
        "last_error": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now,
        "updated_at": now,
    }
    expected_state = migration._migrated_invocation_state(call, now, "each_call")
    assert migration._migrated_invocation_state_matches(
        expected_state,
        {**expected_state},
    )
    assert not migration._migrated_invocation_state_matches(
        expected_state,
        {**expected_state, "status": "succeeded"},
    )


def test_unified_agent_runs_use_a_worker_generation_fence() -> None:
    from app.shareddomain.agents.models import (
        AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
        AGENT_RUN_UNIFIED_QUEUED_STATUS,
        AGENT_RUN_UNIFIED_RUNNING_STATUS,
        agent_run_display_status,
        is_unified_agent_run_status,
    )

    assert AGENT_RUN_UNIFIED_QUEUED_STATUS == "queued_v2"
    assert AGENT_RUN_UNIFIED_RUNNING_STATUS == "running_v2"
    assert AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS == "awaiting_approval_v2"
    assert is_unified_agent_run_status("queued") is False
    assert is_unified_agent_run_status(AGENT_RUN_UNIFIED_QUEUED_STATUS) is True
    assert agent_run_display_status(AGENT_RUN_UNIFIED_QUEUED_STATUS) == "queued"
    assert agent_run_display_status(AGENT_RUN_UNIFIED_RUNNING_STATUS) == "running"
    assert (
        agent_run_display_status(AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS)
        == "awaiting_approval"
    )


def test_tool_invocation_identity_ignores_refreshable_deadline() -> None:
    from app.application.tool_runtime import _same_invocation
    from app.entities.tools import ToolInvocation
    from app.shareddomain.tools.runtime import exhausted_tool_invocation_terminal_state

    fields = {
        "workspace_id": "workspace-1",
        "origin": "agent",
        "root_run_id": "run-1",
        "run_id": "run-1",
        "invocation_id": "2:call-1",
        "execution_user_id": "user-1",
        "access_source": "console",
        "tool_id": "tool-1",
        "tool_version_id": "version-1",
        "arguments_hash": "a" * 64,
        "idempotency_key": "agent:run-1:2:call-1",
    }
    original = ToolInvocation(
        **fields,
        policy_snapshot={
            "tool_snapshot": {"tool_id": "tool-1"},
            "deadline_at": "2026-08-17T00:00:00+00:00",
        },
    )
    resumed = ToolInvocation(
        **fields,
        policy_snapshot={
            "tool_snapshot": {"tool_id": "tool-1"},
            "deadline_at": "2026-08-17T01:00:00+00:00",
        },
    )
    changed = ToolInvocation(
        **fields,
        policy_snapshot={
            "tool_snapshot": {"tool_id": "tool-2"},
            "deadline_at": "2026-08-17T01:00:00+00:00",
        },
    )

    assert _same_invocation(original, resumed) is True
    assert _same_invocation(original, changed) is False
    assert exhausted_tool_invocation_terminal_state(
        "running",
        "external_write",
    )[:2] == ("uncertain", "uncertain")
    assert exhausted_tool_invocation_terminal_state(
        "running",
        "external_read",
    )[:2] == ("failed", "confirmed")
    assert exhausted_tool_invocation_terminal_state(
        "queued",
        "external_write",
    )[:2] == ("failed", "confirmed")


def test_public_tool_responses_exclude_execution_details() -> None:
    from app.schemas.tool import ToolDetailResponse, ToolSummaryResponse

    internal_payload = {
        "id": "tool-1",
        "workspace_id": "workspace-1",
        "kind": "mcp",
        "function_name": "lookup_order",
        "display_name": "Lookup order",
        "description": "Returns one order.",
        "current_version_id": "version-1",
        "status": "active",
        "availability": "available",
        "source": {
            "id": "source-1",
            "name": "Orders",
            "kind": "mcp",
            "transport": "streamable_http",
            "connection": {"url": "https://private.example.com/mcp"},
        },
        "created_by_user_id": "owner-1",
        "permission": "use",
        "can_view": True,
        "can_use": True,
        "can_manage": False,
        "python_code": "result = inputs",
        "mcp_connection": {"bearer_token": "secret"},
        "execution_spec": {"server_id": "server-1", "tool_name": "lookup"},
    }

    summary = ToolSummaryResponse.model_validate(internal_payload).model_dump()
    detail = ToolDetailResponse.model_validate(
        {
            **internal_payload,
            "version_id": "version-1",
            "revision": 1,
            "input_schema": {"type": "object", "additionalProperties": False},
            "output_schema": {"type": "object", "additionalProperties": False},
            "approval": "each_call",
            "effect": "unknown",
            "workflow_callable": True,
            "parallel_safe": False,
        }
    ).model_dump()

    sensitive_fields = {"python_code", "mcp_connection", "execution_spec"}
    assert sensitive_fields.isdisjoint(summary)
    assert sensitive_fields.isdisjoint(detail)
    assert "connection" not in summary["source"]
    assert "connection" not in detail["source"]


def test_builtin_tool_summary_accepts_system_owner() -> None:
    from app.schemas.tool import ToolSummaryResponse

    summary = ToolSummaryResponse.model_validate(
        {
            "id": "tool-current-time",
            "workspace_id": "workspace-1",
            "kind": "builtin",
            "function_name": "current_time",
            "display_name": "Current time",
            "description": "Returns the current time.",
            "current_version_id": "version-1",
            "status": "active",
            "availability": "available",
            "source": {
                "id": "source-builtin",
                "name": "Builtins",
                "kind": "builtin",
            },
            "created_by_user_id": None,
            "permission": None,
            "can_view": True,
            "can_use": True,
            "can_manage": False,
        }
    )

    assert summary.created_by_user_id is None


def test_tool_ref_schema_requires_canonical_ids() -> None:
    from pydantic import ValidationError

    from app.schemas.tool import ToolRefSchema

    reference = ToolRefSchema(tool_id=" tool-1 ", version_id=" version-1 ")
    assert reference.model_dump() == {
        "tool_id": "tool-1",
        "version_id": "version-1",
    }

    for payload in (
        {"tool_id": "", "version_id": "version-1"},
        {"tool_id": "tool-1", "version_id": "   "},
        {"tool_id": "tool-1", "version_id": "version-1", "server_id": "old"},
    ):
        try:
            ToolRefSchema.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError(f"Invalid HTTP ToolRef accepted: {payload}")


def test_workflow_uses_canonical_tool_refs_and_inline_python_builtin() -> None:
    from app.schemas.workflow import LlmNodeConfig, ToolNodeConfig
    from app.shareddomain.tools.catalog import build_inline_python_tool

    reference = {"tool_id": "tool-1", "version_id": "version-1"}
    node = ToolNodeConfig.model_validate(
        {"tool": reference, "arguments": {"value": "{{start.question}}"}}
    )
    llm = LlmNodeConfig.model_validate(
        {"prompt": "Use a tool", "tools": [reference]}
    )
    assert node.tool.model_dump() == reference
    assert [item.model_dump() for item in llm.tools] == [reference]

    tool, version, policy = build_inline_python_tool("workspace-1")
    assert tool.stable_key == "inline_python"
    assert tool.current_version_id == version.id
    assert version.execution_spec == {
        "builtin": "inline_python",
        "workflow_only": True,
        "direct_only": True,
    }
    assert policy.approval == "auto"
    assert policy.effect == "pure"
    assert policy.workflow_callable is True
    assert policy.parallel_safe is False


def test_workflow_legacy_tools_normalize_to_one_canonical_node_contract() -> None:
    from app.entities.tools import ToolRef
    from app.schemas.workflow import WorkflowGraph
    from app.shareddomain.workflows.resources import (
        canonicalize_workflow_graph,
        workflow_resource_references,
    )

    graph = WorkflowGraph.model_validate(
        {
            "nodes": [
                {
                    "id": "remote",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "mcp",
                        "title": "Remote",
                        "config": {
                            "server_id": "server-1",
                            "tool_name": "lookup",
                            "arguments": {"query": "hello"},
                        },
                    },
                },
                {
                    "id": "python",
                    "type": "workflow",
                    "position": {"x": 0, "y": 100},
                    "data": {
                        "type": "code",
                        "title": "Python",
                        "config": {
                            "code": "result = inputs",
                            "inputs": {"value": 1},
                        },
                    },
                },
                {
                    "id": "model",
                    "type": "workflow",
                    "position": {"x": 0, "y": 200},
                    "data": {
                        "type": "llm",
                        "title": "Model",
                        "config": {
                            "prompt": "answer",
                            "mcp_enable": True,
                            "mcp_servers": [
                                {"server_id": "server-1", "tool_name": "lookup"}
                            ],
                        },
                    },
                },
            ],
            "edges": [],
        }
    )
    remote = ToolRef("tool-remote", "version-remote")
    inline = ToolRef("tool-inline", "version-inline")
    canonical = canonicalize_workflow_graph(
        graph,
        {("server-1", "lookup"): remote},
        inline,
    )

    assert [node.data.type for node in canonical.nodes] == ["tool", "tool", "llm"]
    assert canonical.nodes[0].data.config == {
        "tool": {"tool_id": "tool-remote", "version_id": "version-remote"},
        "arguments": {"query": "hello"},
    }
    assert canonical.nodes[1].data.config == {
        "tool": {"tool_id": "tool-inline", "version_id": "version-inline"},
        "arguments": {"code": "result = inputs", "inputs": {"value": 1}},
    }
    assert canonical.nodes[2].data.config["tools"] == [
        {"tool_id": "tool-remote", "version_id": "version-remote"}
    ]
    assert "mcp_enable" not in canonical.nodes[2].data.config
    assert workflow_resource_references(canonical)[1] == [remote, inline]


def test_workflow_selects_only_exact_bound_tool_versions() -> None:
    from app.entities.tools import ToolRef, ToolSnapshot
    from app.shareddomain.workflows.resources import select_tool_snapshots

    def snapshot(tool_id: str, version_id: str) -> ToolSnapshot:
        return ToolSnapshot(
            schema_version=1,
            tool_id=tool_id,
            version_id=version_id,
            source_id="source-1",
            kind="python",
            function_name=tool_id,
            display_name=tool_id,
            description="",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={"type": "object", "additionalProperties": False},
            definition_hash=f"hash-{version_id}",
            policy_id=f"policy-{tool_id}",
            policy_revision=1,
            bound_by_user_id="binder-1",
            approval="auto",
            effect="pure",
            allowed_access_sources=("console",),
            workflow_callable=True,
            parallel_safe=False,
            execution_spec={"code": "result = {}"},
        )

    selected = select_tool_snapshots(
        [ToolRef("tool-b", "version-b")],
        [snapshot("tool-a", "version-a"), snapshot("tool-b", "version-b")],
    )
    assert [(item.tool_id, item.bound_by_user_id) for item in selected] == [
        ("tool-b", "binder-1")
    ]

    for reference in (
        ToolRef("missing", "version-1"),
        ToolRef("tool-b", "version-other"),
    ):
        try:
            select_tool_snapshots(
                [reference],
                [snapshot("tool-b", "version-b")],
            )
        except ValueError:
            continue
        raise AssertionError("Unbound Workflow Tool version was accepted.")


def test_workflow_resource_snapshot_must_match_the_canonical_graph() -> None:
    from app.entities.tools import ToolRef, ToolSnapshot
    from app.schemas.workflow import WorkflowGraph
    from app.shareddomain.workflows.resources import (
        build_workflow_resource_snapshot,
        load_workflow_resource_snapshot,
        workflow_resource_hash,
    )

    reference = ToolRef("tool-1", "version-1")
    graph = WorkflowGraph.model_validate(
        {
            "nodes": [
                {
                    "id": "tool",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "tool",
                        "title": "Tool",
                        "config": {
                            "tool": {
                                "tool_id": reference.tool_id,
                                "version_id": reference.version_id,
                            },
                            "arguments": {},
                        },
                    },
                }
            ],
            "edges": [],
        }
    )
    tool = ToolSnapshot(
        schema_version=1,
        tool_id=reference.tool_id,
        version_id=reference.version_id,
        source_id="source-1",
        kind="python",
        function_name="tool_1",
        display_name="Tool",
        description="",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=1,
        bound_by_user_id="binder-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = {}"},
    )
    payload = build_workflow_resource_snapshot([], [tool])
    knowledge_ids, tools = load_workflow_resource_snapshot(
        graph,
        payload,
        workflow_resource_hash(payload),
    )
    assert knowledge_ids == []
    assert tools == [tool]

    for invalid in (
        {**payload, "legacy": True},
        {**payload, "tools": []},
    ):
        try:
            load_workflow_resource_snapshot(
                graph,
                invalid,
                workflow_resource_hash(invalid),
            )
        except ValueError:
            continue
        raise AssertionError("Invalid Workflow resource snapshot was accepted.")


def test_workflow_agent_nodes_pin_versions_and_cannot_run_in_parallel() -> None:
    from app.shareddomain.workflows.engine import (
        WorkflowValidationError,
        validate_graph,
    )
    from app.shareddomain.workflows.resources import (
        build_workflow_resource_snapshot,
        load_workflow_agent_snapshots,
        workflow_resource_hash,
    )

    def node(node_id: str, node_type: str, config: dict | None = None) -> dict:
        return {
            "id": node_id,
            "type": "workflow",
            "position": {"x": 0, "y": 0},
            "data": {
                "type": node_type,
                "title": node_id,
                "config": config or {},
            },
        }

    graph = validate_graph(
        {
            "nodes": [
                node("start", "start"),
                node(
                    "agent",
                    "agent",
                    {
                        "agent_id": "agent-1",
                        "agent_version_id": "version-1",
                        "input": "{{start.question}}",
                    },
                ),
                node("end", "end", {"outputs": {"result": "{{agent.result}}"}}),
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "agent"},
                {"id": "e2", "source": "agent", "target": "end"},
            ],
        }
    )
    agent_snapshot = {
        "agent_id": "agent-1",
        "version_id": "version-1",
        "version_number": 1,
        "configuration_hash": "hash-1",
        "configuration_snapshot": {"name": "Helper"},
        "resource_snapshot": {"knowledge_base_ids": [], "tools": []},
        "bound_by_user_id": "binder-1",
    }
    snapshot = build_workflow_resource_snapshot([], [], [agent_snapshot])
    assert load_workflow_agent_snapshots(
        graph,
        snapshot,
        workflow_resource_hash(snapshot),
    ) == [agent_snapshot]

    wrong_agent = build_workflow_resource_snapshot(
        [],
        [],
        [{**agent_snapshot, "agent_id": "agent-2"}],
    )
    try:
        load_workflow_agent_snapshots(
            graph,
            wrong_agent,
            workflow_resource_hash(wrong_agent),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Workflow Agent identity mismatch was accepted.")

    invalid = build_workflow_resource_snapshot([], [], [])
    try:
        load_workflow_agent_snapshots(
            graph,
            invalid,
            workflow_resource_hash(invalid),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Workflow Agent version missing from snapshot was accepted.")

    parallel_graph = {
        "nodes": [
            node("start", "start"),
            node(
                "agent_a",
                "agent",
                {"agent_id": "a1", "agent_version_id": "v1", "input": "a"},
            ),
            node(
                "agent_b",
                "agent",
                {"agent_id": "a2", "agent_version_id": "v2", "input": "b"},
            ),
            node("end", "end", {"outputs": {}}),
        ],
        "edges": [
            {"id": "a1", "source": "start", "target": "agent_a"},
            {"id": "a2", "source": "agent_a", "target": "end"},
            {"id": "b1", "source": "start", "target": "agent_b"},
            {"id": "b2", "source": "agent_b", "target": "end"},
        ],
    }
    try:
        validate_graph(parallel_graph)
    except WorkflowValidationError:
        pass
    else:
        raise AssertionError("Parallel Workflow Agent nodes were accepted.")

    oversized_graph = {
        "nodes": [
            node("start", "start"),
            node(
                "agent",
                "agent",
                {
                    "agent_id": "agent-1",
                    "agent_version_id": "version-1",
                    "input": "x" * (128 * 1024),
                },
            ),
            node("end", "end", {"outputs": {}}),
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "agent"},
            {"id": "e2", "source": "agent", "target": "end"},
        ],
    }
    try:
        validate_graph(oversized_graph)
    except WorkflowValidationError:
        pass
    else:
        raise AssertionError("Oversized Workflow Agent input was accepted.")


def test_workflow_tool_invocation_identity_is_stable_and_bounded() -> None:
    from app.application.workflow_tool_runtime import workflow_tool_invocation_identity
    from app.shareddomain.tools.runtime import tool_arguments_hash

    first = workflow_tool_invocation_identity("run-1", "node-1", "call-1")
    second = workflow_tool_invocation_identity("run-1", "node-1", "call-1")
    assert first == second
    assert first[0] == "node-1:call-1"
    assert len(first[1]) == 64
    assert tool_arguments_hash({"a": 1, "nested": {"b": 2, "c": 3}}) == (
        tool_arguments_hash({"nested": {"c": 3, "b": 2}, "a": 1})
    )

    try:
        workflow_tool_invocation_identity("run-1", "n" * 200, "c" * 100)
    except ValueError:
        pass
    else:
        raise AssertionError("Oversized Workflow Tool identity was accepted.")


def test_workflow_tool_runtime_serializes_unsafe_tools_and_blocks_direct_only_llm() -> None:
    from app.application.workflow_tool_runtime import WorkflowToolRuntime
    from app.entities.tools import ToolSnapshot

    def snapshot(
        tool_id: str,
        *,
        parallel_safe: bool,
        direct_only: bool = False,
    ) -> ToolSnapshot:
        return ToolSnapshot(
            schema_version=1,
            tool_id=tool_id,
            version_id=f"version-{tool_id}",
            source_id="source-1",
            kind="builtin",
            function_name=tool_id,
            display_name=tool_id,
            description="",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            definition_hash=f"hash-{tool_id}",
            policy_id=f"policy-{tool_id}",
            policy_revision=1,
            bound_by_user_id="user-1",
            approval="auto",
            effect="pure",
            allowed_access_sources=("console",),
            workflow_callable=True,
            parallel_safe=parallel_safe,
            execution_spec={"direct_only": direct_only},
        )

    serial = snapshot("serial", parallel_safe=False)
    parallel = snapshot("parallel", parallel_safe=True)
    direct_only = snapshot("direct", parallel_safe=True, direct_only=True)
    runtime = WorkflowToolRuntime(
        SimpleNamespace(),
        SimpleNamespace(),
        [serial, parallel, direct_only],
        "worker-1",
        SimpleNamespace(),
        asyncio.Event(),
    )
    active = 0
    maximum = 0

    async def fake_invoke(_snapshot, _node_id, _call_id, _arguments):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return SimpleNamespace(is_error=False)

    runtime._invoke = fake_invoke  # type: ignore[method-assign]

    async def assert_runtime_contract() -> None:
        nonlocal maximum
        await asyncio.gather(
            runtime.invoke(serial, "node-1", "direct", {}),
            runtime.invoke(serial, "node-2", "direct", {}),
        )
        assert maximum == 1
        maximum = 0
        await asyncio.gather(
            runtime.invoke(parallel, "node-1", "direct", {}),
            runtime.invoke(parallel, "node-2", "direct", {}),
        )
        assert maximum == 2
        try:
            await runtime.invoke(direct_only, "node-3", "llm:1:direct", {})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Direct-only Workflow Tool was exposed to an LLM.")

    asyncio.run(assert_runtime_contract())


def test_workflow_tool_migration_matches_runtime_catalog() -> None:
    import importlib.util
    from datetime import UTC, datetime
    from pathlib import Path

    import sqlalchemy as sa

    from app.shareddomain.tools.catalog import build_inline_python_tool

    path = (
        Path(__file__).parents[1]
        / "alembic/versions/202608170002_workflow_tool_resources.py"
    )
    spec = importlib.util.spec_from_file_location("workflow_tool_resources", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    created_at = datetime(2026, 8, 17, tzinfo=UTC)
    source, migrated_tool, migrated_version, migrated_policy = (
        migration._inline_python_rows("workspace-1", created_at)
    )
    tool, version, policy = build_inline_python_tool("workspace-1", created_at)
    assert source["name"] == "Built-in"
    assert migrated_tool["id"] == tool.id
    assert migrated_tool["function_name"] == tool.function_name
    assert migrated_version["id"] == version.id
    assert migrated_version["definition_hash"] == version.definition_hash
    assert migrated_policy["id"] == policy.id
    assert migrated_policy["tool_version_id"] == policy.tool_version_id

    graph = {
        "nodes": [
            {
                "data": {
                    "type": "knowledge",
                    "config": {"knowledge_base_ids": ["kb-1", "kb-1"]},
                }
            },
            {
                "data": {
                    "type": "mcp",
                    "config": {"server_id": "server-1", "tool_name": "lookup"},
                }
            },
            {"data": {"type": "code", "config": {"code": "result = {}"}}},
            {
                "data": {
                    "type": "llm",
                    "config": {
                        "tools": [
                            {"tool_id": "tool-1", "version_id": "version-1"}
                        ]
                    },
                }
            },
        ]
    }
    assert migration._graph_references(graph) == (
        ["kb-1"],
        [("server-1", "lookup")],
        [("tool-1", "version-1")],
        True,
    )
    assert migration._graph_has_canonical_tool_reference(graph)
    assert migration._graph_has_canonical_tool_reference(
        {"nodes": [{"data": {"type": "tool", "config": {}}}]}
    )

    metadata = sa.MetaData()
    tools = sa.Table(
        "tools",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("stable_key", sa.String, nullable=False),
        sa.Column("current_version_id", sa.String),
    )
    definitions = sa.Table(
        "workflow_definitions",
        metadata,
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("agent_id", sa.String, nullable=False),
        sa.Column("graph", sa.JSON, nullable=False),
        sa.Column("updated_by_user_id", sa.String, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    bindings = sa.Table(
        "application_tool_bindings",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("application_id", sa.String, nullable=False),
        sa.Column("tool_id", sa.String, nullable=False),
        sa.Column("tool_version_id", sa.String, nullable=False),
        sa.Column("bound_by_user_id", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            tools.insert(),
            {
                "id": migrated_tool["id"],
                "workspace_id": "workspace-1",
                "kind": "builtin",
                "stable_key": "inline_python",
                "current_version_id": migrated_version["id"],
            },
        )
        connection.execute(
            definitions.insert(),
            {
                "workspace_id": "workspace-1",
                "agent_id": "workflow-1",
                "graph": {
                    "nodes": [
                        {
                            "data": {
                                "type": "code",
                                "config": {"code": "result = {}"},
                            }
                        }
                    ]
                },
                "updated_by_user_id": "user-1",
                "updated_at": created_at,
            },
        )
        migration._backfill_inline_python_bindings(connection)
        migration._backfill_inline_python_bindings(connection)
        rows = connection.execute(sa.select(bindings)).mappings().all()
        assert len(rows) == 1
        assert rows[0]["application_id"] == "workflow-1"
        assert rows[0]["tool_version_id"] == migrated_version["id"]


def test_coverage_runner_times_out_suites() -> None:
    import importlib.util
    import subprocess
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts/coverage.py"
    spec = importlib.util.spec_from_file_location("coverage_runner", path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    original_run = runner.subprocess.run

    def timeout(*_args, **kwargs):
        assert kwargs["timeout"] == runner.COMMAND_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired("coverage", kwargs["timeout"])

    runner.subprocess.run = timeout
    log_path = None
    try:
        suite, returncode, log_path = runner._run_suite("unit", 20260818)
        assert suite == "unit"
        assert returncode == 124
        assert "timed out" in log_path.read_text()
    finally:
        runner.subprocess.run = original_run
        if log_path is not None:
            log_path.unlink(missing_ok=True)


def test_effective_tool_access_matrix() -> None:
    from app.entities.tools import ToolAccess, effective_tool_access

    full_access = ToolAccess(can_view=True, can_use=True, can_manage=True)
    assert (
        effective_tool_access(
            is_owner=True,
            is_workspace_admin=False,
            grant=None,
        )
        == full_access
    )
    assert (
        effective_tool_access(
            is_owner=False,
            is_workspace_admin=True,
            grant=None,
        )
        == full_access
    )
    assert effective_tool_access(
        is_owner=False,
        is_workspace_admin=False,
        grant="use",
    ) == ToolAccess(can_view=True, can_use=True, can_manage=False)
    assert effective_tool_access(
        is_owner=False,
        is_workspace_admin=False,
        grant="view",
    ) == ToolAccess(can_view=True, can_use=False, can_manage=False)
    assert effective_tool_access(
        is_owner=False,
        is_workspace_admin=False,
        grant=None,
    ) == ToolAccess(can_view=False, can_use=False, can_manage=False)


def test_tool_authorization_applies_builtin_and_global_admin_rules() -> None:
    from app.application.tools import evaluate_tool_authorization
    from app.entities.resource_permission import ResourcePermission
    from app.entities.tools import Tool, ToolAccess
    from app.entities.user import User

    member = User(id="member-1")
    builtin = Tool(id="builtin-1", kind="builtin")
    builtin_authorization = evaluate_tool_authorization(
        builtin,
        member,
        "member",
        None,
    )
    assert builtin_authorization.access == ToolAccess(
        can_view=True,
        can_use=True,
        can_manage=False,
    )
    assert builtin_authorization.permission == "use"
    outside_workspace = evaluate_tool_authorization(
        builtin,
        member,
        None,
        None,
    )
    assert outside_workspace.access == ToolAccess(
        can_view=False,
        can_use=False,
        can_manage=False,
    )
    assert outside_workspace.permission is None

    global_admin = User(id="global-admin-1", is_global_admin=True)
    private_tool = Tool(
        id="private-1",
        kind="python",
        status="disabled",
        availability="unavailable",
        created_by_user_id="owner-1",
    )
    admin_authorization = evaluate_tool_authorization(
        private_tool,
        global_admin,
        "member",
        None,
    )
    assert admin_authorization.access == ToolAccess(
        can_view=True,
        can_use=True,
        can_manage=True,
    )
    assert admin_authorization.permission == "admin"

    former_owner = User(id="owner-1")
    former_owner_authorization = evaluate_tool_authorization(
        private_tool,
        former_owner,
        None,
        None,
    )
    assert former_owner_authorization.access == ToolAccess(False, False, False)
    assert former_owner_authorization.permission is None

    stale_grant_authorization = evaluate_tool_authorization(
        private_tool,
        member,
        None,
        ResourcePermission(permission="use", user_id=member.id),
    )
    assert stale_grant_authorization.access == ToolAccess(False, False, False)
    assert stale_grant_authorization.permission is None

    inactive_owner = User(id="owner-1", is_active=False)
    inactive_authorization = evaluate_tool_authorization(
        private_tool,
        inactive_owner,
        "member",
        None,
    )
    assert inactive_authorization.access == ToolAccess(False, False, False)
    assert inactive_authorization.permission is None


def test_python_tool_schema_validation_closes_objects() -> None:
    from app.entities.tools import validate_tool_json_schema

    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "maxLength": 200},
            "options": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
        "required": ["query"],
    }

    restricted = validate_tool_json_schema(schema)

    assert restricted["additionalProperties"] is False
    assert restricted["properties"]["options"]["additionalProperties"] is False
    assert "additionalProperties" not in schema

    for invalid in (
        {"type": "string", "maxLength": 20},
        {"type": "object", "additionalProperties": True},
    ):
        try:
            validate_tool_json_schema(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Unsafe Python Tool schema accepted: {invalid}")


def test_python_tool_schema_validation_enforces_limits() -> None:
    from app.entities.tools import (
        MAX_TOOL_ARRAY_ITEMS,
        MAX_TOOL_SCHEMA_BYTES,
        MAX_TOOL_SCHEMA_DEPTH,
        MAX_TOOL_SCHEMA_PROPERTIES,
        MAX_TOOL_STRING_LENGTH,
        validate_tool_json_schema,
    )

    nested: dict[str, object] = {"type": "integer"}
    for index in range(MAX_TOOL_SCHEMA_DEPTH):
        nested = {
            "type": "object",
            "properties": {f"level_{index}": nested},
        }

    invalid_schemas = (
        {
            "type": "object",
            "properties": {"remote": {"$ref": "https://example.com/schema"}},
        },
        {
            "type": "object",
            "$defs": {"value": {"type": "integer"}},
            "properties": {"local": {"$ref": "#/$defs/value"}},
        },
        {
            "type": "object",
            "description": "x" * MAX_TOOL_SCHEMA_BYTES,
        },
        {
            "type": "object",
            "properties": {
                f"field_{index}": {"type": "integer"}
                for index in range(MAX_TOOL_SCHEMA_PROPERTIES + 1)
            },
        },
        nested,
        {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "integer"}}
            },
        },
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "maxItems": MAX_TOOL_ARRAY_ITEMS + 1,
                }
            },
        },
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        },
        {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "maxLength": MAX_TOOL_STRING_LENGTH + 1,
                }
            },
        },
        {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "maxLength": 64,
                    "pattern": "^(a+)+$",
                }
            },
        },
    )
    for schema in invalid_schemas:
        try:
            validate_tool_json_schema(schema)
        except ValueError:
            continue
        raise AssertionError(f"Over-broad Python Tool schema accepted: {schema}")


def test_python_tool_schema_rejects_defs_depth_bypass() -> None:
    from app.entities.tools import (
        MAX_TOOL_SCHEMA_DEPTH,
        validate_tool_json_schema,
    )

    hidden_depth: dict[str, object] = {"type": "integer"}
    for index in range(MAX_TOOL_SCHEMA_DEPTH):
        hidden_depth = {
            "type": "object",
            "properties": {f"level_{index}": hidden_depth},
        }
    schema = {"type": "object", "$defs": {"hidden": hidden_depth}}
    try:
        validate_tool_json_schema(schema)
    except ValueError:
        return
    raise AssertionError("$defs bypassed the Tool schema depth limit.")


def test_python_tool_schema_rejects_legacy_definitions_property_bypass() -> None:
    from app.entities.tools import (
        MAX_TOOL_SCHEMA_PROPERTIES,
        validate_tool_json_schema,
    )

    schema = {
        "type": "object",
        "definitions": {
            "hidden": {
                "type": "object",
                "properties": {
                    f"field_{index}": {"type": "integer"}
                    for index in range(MAX_TOOL_SCHEMA_PROPERTIES + 1)
                },
            }
        },
    }
    try:
        validate_tool_json_schema(schema)
    except ValueError:
        return
    raise AssertionError("definitions bypassed the Tool schema property limit.")


def test_python_tool_code_is_limited_to_eight_kibibytes() -> None:
    from app.entities.tools import (
        MAX_PYTHON_TOOL_CODE_BYTES,
        validate_python_tool_code,
    )

    boundary = "x" * MAX_PYTHON_TOOL_CODE_BYTES
    assert validate_python_tool_code(boundary) == boundary

    for code in (boundary + "x", "\u754c" * (MAX_PYTHON_TOOL_CODE_BYTES // 3 + 1)):
        try:
            validate_python_tool_code(code)
        except ValueError:
            continue
        raise AssertionError("Oversized Python Tool code was accepted.")


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


def test_plain_legal_headings_keep_chapters_in_separate_parents() -> None:
    from app.capabilities.embedding.pipeline import split_parent_chunks

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

    import json

    from app.application.agent_tools import bounded_knowledge_context

    context = bounded_knowledge_context(
        {
            "query": "q",
            "hits": [{"chunk_id": "chunk-1", "content": "x" * 500}],
            "evidence_status": "found",
        },
        max_chars=180,
    )
    assert len(context) <= 180
    assert json.loads(context)["context_truncated"] is True


def test_grounding_verifier_revises_and_fails_closed() -> None:
    from langchain_core.messages import AIMessage

    from app.application.agent_grounding import (
        GROUNDING_FALLBACK_ANSWER,
        verify_grounding,
    )

    class FakeModel:
        def __init__(self, content: str) -> None:
            self.content = content
            self.messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return AIMessage(
                content=self.content,
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )

    model = FakeModel(
        '{"status":"revised","answer":"第十六条。",'
        '"evidence_ids":["chunk-16"],"reason_codes":["article_boundary"]}'
    )
    result = asyncio.run(
        verify_grounding(
            model,
            question="第二章有多少条？",
            draft="第二章有十条。",
            evidence_packets=[
                {
                    "chunk_id": "chunk-16",
                    "section_path": ["第二章"],
                    "content": "第二章\n第十六条。",
                }
            ],
            attachment_context="",
            required=True,
        )
    )
    assert result.status == "revised"
    assert result.answer == "第十六条。"
    assert result.meta["evidence_ids"] == ["chunk-16"]
    assert result.model_usage["total_tokens"] == 15
    assert "第二章有多少条？" in model.messages[1]["content"]

    invalid = FakeModel("not-json")
    failed = asyncio.run(
        verify_grounding(
            invalid,
            question="question",
            draft="unsafe draft",
            evidence_packets=[],
            attachment_context="",
            required=True,
        )
    )
    assert failed.status == "unavailable"
    assert failed.answer == GROUNDING_FALLBACK_ANSWER


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

    fused_graph = reciprocal_rank_fusion(
        [VectorHit(chunk_id="shared", distance=0.2)],
        [],
        graph_chunk_ids=["shared", "graph-only"],
    )
    assert [hit.chunk_id for hit in fused_graph] == ["shared", "graph-only"]
    assert fused_graph[0].graph_rank == 1
    assert fused_graph[0].sources == ("vector", "graph")


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
            graph_rank=None,
            sources=("vector", "keywords"),
        ),
        RankedHit(
            chunk_id="c",
            distance=None,
            rrf_score=1 / 62 + 1 / 61,
            vector_rank=None,
            keyword_rank=2,
            reference_rank=1,
            graph_rank=None,
            sources=("keywords", "reference"),
        ),
        RankedHit(
            chunk_id="a",
            distance=0.2,
            rrf_score=1 / 61,
            vector_rank=1,
            keyword_rank=None,
            reference_rank=None,
            graph_rank=None,
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


def test_graph_entity_repository_uses_scoped_bm25_query() -> None:
    from app.infrastructure.repositories import knowledge_graph as graph_repository

    class FakeResult:
        def scalars(self):
            return ["entity-2", "entity-1"]

    class FakeDatabase:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def execute(self, statement, parameters):
            sql = str(statement)
            assert "entity.search_text ||| CAST(:query AS text)" in sql
            assert "pdb.score(entity.id) DESC" in sql
            assert "entity.workspace_id = :workspace_id" in sql
            assert "entity.knowledge_base_id = :knowledge_base_id" in sql
            assert "entity.state = 'active'" in sql
            assert parameters == {
                "workspace_id": "ws-1",
                "knowledge_base_id": "kb-1",
                "query": "离职 账号",
                "candidate_limit": 8,
                "entity_types": ["Document", "Process"],
            }
            return FakeResult()

    result = asyncio.run(
        graph_repository.query_entity_candidate_ids(
            FakeDatabase(),  # type: ignore[arg-type]
            KnowledgeBase(id="kb-1", workspace_id="ws-1"),
            "离职 账号",
            8,
            {"Process", "Document"},
        )
    )
    assert result == ["entity-2", "entity-1"]


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
    assert request.graph_mode == "auto"
    assert request.source_entity is None
    assert request.target_entity is None
    assert request.max_hops == 6
    assert request.relation_filters == []
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
        "reference_hops": 0,
        "graph_claim_ids": [],
        "graph_hops": 0,
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
    assert dumped_trace["graph_mode"] == "auto"
    assert dumped_trace["graph_claim_candidates"] == 0
    inspect = KnowledgeQueryInspectResponse(hits=[hit], trace=trace)
    assert inspect.trace is trace
    assert inspect.graph is None


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


def test_external_progress_events_include_grounding_stage() -> None:
    from app.application.agent_access import external_progress_events

    progress = external_progress_events(
        [
            {
                "type": "thought",
                "turn": 1,
                "status": "running",
                "summary": "agent.grounding_check",
                "call_id": "grounding-1",
            },
            {
                "type": "thought",
                "turn": 1,
                "status": "succeeded",
                "summary": "agent.grounding_revised",
                "call_id": "grounding-1",
            },
        ],
        "succeeded",
    )
    assert len(progress) == 1
    assert progress[0].type == "analysis"
    assert progress[0].status == "succeeded"
    assert progress[0].stage == "completed"


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
    built = build_mcp_agent_tool(tool, SimpleNamespace(), "agent-1")
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
    child = AgentRun(id="child-1", parent_run_id="parent-1", root_run_id="")
    assert child.root_run_id == "parent-1"
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


def test_regenerated_agent_run_starts_from_a_fresh_checkpoint() -> None:
    from app.application.agent_runs import build_regenerated_agent_run
    from app.entities.agents import AgentRun

    source = AgentRun(
        id="run-source",
        workspace_id="ws-1",
        agent_id="agent-1",
        requested_by_user_id="user-1",
        execution_user_id="user-1",
        access_source="console",
        consumer_id="user-1",
        conversation_id="conversation-1",
        goal="Explain the release notes",
        attachment_context="attached context",
        instructions="Answer precisely.",
        knowledge_base_ids=["kb-1"],
        configuration_source="draft",
        model_id="model-1",
        model_name="deepseek-chat",
        status="succeeded",
        checkpoint={"final_answer": "old answer"},
        checkpoint_phase="done",
        result="old answer",
        events=[{"type": "answer"}],
        feedback="positive",
    )

    regenerated = build_regenerated_agent_run(
        source,
        User(id="user-1", username="owner"),
    )

    assert regenerated.id != source.id
    assert regenerated.regenerated_from_run_id == source.id
    assert regenerated.conversation_id == source.conversation_id
    assert regenerated.goal == source.goal
    assert regenerated.attachment_context == source.attachment_context
    assert regenerated.status == "queued_v2"
    assert regenerated.checkpoint == {}
    assert regenerated.checkpoint_phase == "agent"
    assert regenerated.result == ""
    assert regenerated.events == []
    assert regenerated.feedback is None


def test_repeated_run_feedback_write_is_idempotent() -> None:
    from unittest.mock import AsyncMock, patch

    from app.application.agent_runs import update_run_feedback
    from app.entities.agents import AgentRun
    from app.infrastructure.model_utils import utc_now

    feedback_updated_at = utc_now()
    run = AgentRun(
        id="run-1",
        status="succeeded",
        result="answer",
        feedback="positive",
        feedback_updated_at=feedback_updated_at,
    )

    class FakeDatabase:
        def __init__(self) -> None:
            self.commits = 0

        async def commit(self) -> None:
            self.commits += 1

    db = FakeDatabase()
    save_run = AsyncMock(side_effect=lambda _db, current: current)
    with patch(
        "app.application.agent_runs.agent_repository.save_agent_run",
        new=save_run,
    ):
        updated = asyncio.run(
            update_run_feedback(db, run, "positive")  # type: ignore[arg-type]
        )

    assert updated is run
    assert run.feedback_updated_at == feedback_updated_at
    save_run.assert_not_awaited()
    assert db.commits == 0


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
    from app.entities.tools import (
        McpServer,
        McpToolPolicy,
        Tool,
        ToolPolicy,
        ToolSource,
        ToolVersion,
    )
    from app.shareddomain.tools.catalog import McpCatalogLeaf
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
    source = ToolSource(
        id="source-1",
        workspace_id="ws-1",
        mcp_server_id="mcp-1",
        kind="mcp",
        created_by_user_id="user-1",
    )
    search_tool = Tool(
        id="tool-search",
        workspace_id="ws-1",
        source_id=source.id,
        kind="mcp",
        stable_key="search",
        function_name="mcp_search_12345678",
        current_version_id="version-search",
        created_by_user_id="user-1",
    )
    search_definition = McpTool(
        name="search",
        description="Search public records.",
        input_schema={"type": "object"},
        annotations={"readOnlyHint": True, "destructiveHint": False},
    )
    search_hash = mcp_tool_definition_hash(search_definition)
    search_version = ToolVersion(
        id="version-search",
        workspace_id="ws-1",
        tool_id=search_tool.id,
        description="Search public records.",
        input_schema={"type": "object"},
        execution_spec={
            "server_id": "mcp-1",
            "tool_name": "search",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        definition_hash=search_hash,
    )
    stale_policy = ToolPolicy(
        workspace_id="ws-1",
        tool_id=search_tool.id,
        tool_version_id=search_version.id,
        definition_hash="stale",
        approval="auto",
        effect="external_read",
    )
    unknown_tool = Tool(
        id="tool-unknown",
        workspace_id="ws-1",
        source_id=source.id,
        kind="mcp",
        stable_key="unknown",
        function_name="mcp_unknown_12345678",
        current_version_id="version-unknown",
        created_by_user_id="user-1",
    )
    unknown_version = ToolVersion(
        id="version-unknown",
        workspace_id="ws-1",
        tool_id=unknown_tool.id,
        description="Unclassified operation.",
        input_schema={"type": "object"},
        execution_spec={
            "server_id": "mcp-1",
            "tool_name": "unknown",
            "annotations": None,
        },
        definition_hash="u" * 64,
    )
    leaves = [
        McpCatalogLeaf(source, search_tool, search_version, stale_policy),
        McpCatalogLeaf(source, unknown_tool, unknown_version, None),
    ]
    response = mcp_server_to_response(server, leaves)
    assert response.id == "mcp-1"
    assert response.workspace_id == "ws-1"
    assert response.url == "https://tools.example.com/mcp"
    assert response.has_bearer_token is True
    assert response.bearer_token_hint == "abcd"
    assert response.tools[0].policy_mode == "approval_required"
    assert response.tools[1].policy_mode == "approval_required"

    assert mcp_server_to_response(server).tools == []
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
    stale_policy.definition_hash = search_hash
    response = mcp_server_to_response(server, leaves)
    assert response.tools[0].policy_mode == "read_only"
    assert response.tools[0].definition_hash == search_hash


def test_unified_mcp_policy_projection_fails_closed_and_honors_kill_switch() -> None:
    from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion
    from app.shareddomain.tools.catalog import (
        McpCatalogLeaf,
        legacy_mcp_policy_mode,
    )

    source = ToolSource(id="source-1", workspace_id="ws-1", kind="mcp")
    tool = Tool(
        id="tool-1",
        workspace_id="ws-1",
        source_id=source.id,
        kind="mcp",
        current_version_id="version-2",
    )
    version = ToolVersion(
        id="version-2",
        workspace_id="ws-1",
        tool_id=tool.id,
        definition_hash="b" * 64,
    )
    policy = ToolPolicy(
        workspace_id="ws-1",
        tool_id=tool.id,
        tool_version_id=version.id,
        definition_hash=version.definition_hash,
        approval="auto",
        effect="external_read",
    )
    leaf = McpCatalogLeaf(source=source, tool=tool, version=version, policy=policy)
    assert legacy_mcp_policy_mode(leaf) == "read_only"

    policy.definition_hash = "a" * 64
    assert legacy_mcp_policy_mode(leaf) == "approval_required"

    tool.status = "disabled"
    assert legacy_mcp_policy_mode(leaf) == "disabled"


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
    """Run the complete pure-unit test suite and print a success marker when all tests pass."""
    test_effective_permission_matrix()
    test_validate_permission_rejects_unknown()
    test_graph_schema_rejects_unknown_relation_endpoint()
    test_default_policy_graph_schema_is_stable()
    test_graph_token_charge_uses_reported_or_conservative_estimate()
    test_normalized_document_artifact_is_content_addressed()
    test_graph_extraction_requires_exact_chunk_evidence()
    test_graph_extractor_parses_bounded_json_only_response()
    test_graph_extractor_rejects_oversized_input_without_truncating_json()
    test_graph_extractor_retries_invalid_model_output_once()
    test_graph_extractor_does_not_retry_provider_failure()
    test_graph_entity_auto_match_requires_deterministic_identity()
    test_graph_claim_fingerprint_and_initial_status_are_deterministic()
    test_graph_review_decision_request_is_bounded()
    test_graph_import_record_requires_one_object_kind()
    test_tool_ref_requires_stable_ids()
    test_agent_publication_snapshot_is_canonical_and_tool_versioned()
    test_agent_tool_binding_requires_current_available_policy()
    test_tool_snapshot_is_an_immutable_internal_contract()
    test_tool_contracts_deep_freeze_nested_json()
    test_freeze_json_rejects_non_json_values()
    test_tool_adapter_contract_is_provider_neutral()
    test_agent_tool_definition_comes_from_unified_snapshot()
    test_agent_tool_runtime_uses_stable_invocation_identity_and_envelope()
    test_agent_tool_call_migration_preserves_approval_gate()
    test_unified_agent_runs_use_a_worker_generation_fence()
    test_tool_invocation_identity_ignores_refreshable_deadline()
    test_public_tool_responses_exclude_execution_details()
    test_builtin_tool_summary_accepts_system_owner()
    test_tool_ref_schema_requires_canonical_ids()
    test_workflow_uses_canonical_tool_refs_and_inline_python_builtin()
    test_workflow_legacy_tools_normalize_to_one_canonical_node_contract()
    test_workflow_selects_only_exact_bound_tool_versions()
    test_workflow_resource_snapshot_must_match_the_canonical_graph()
    test_workflow_agent_nodes_pin_versions_and_cannot_run_in_parallel()
    test_workflow_tool_invocation_identity_is_stable_and_bounded()
    test_workflow_tool_runtime_serializes_unsafe_tools_and_blocks_direct_only_llm()
    test_workflow_tool_migration_matches_runtime_catalog()
    test_coverage_runner_times_out_suites()
    test_effective_tool_access_matrix()
    test_tool_authorization_applies_builtin_and_global_admin_rules()
    test_python_tool_schema_validation_closes_objects()
    test_python_tool_schema_validation_enforces_limits()
    test_python_tool_schema_rejects_defs_depth_bypass()
    test_python_tool_schema_rejects_legacy_definitions_property_bypass()
    test_python_tool_code_is_limited_to_eight_kibibytes()
    test_knowledge_writes_recheck_locked_owner()
    test_clean_upload_filename_sanitizes_path_and_classification()
    test_parse_task_options_validates_boundaries()
    test_markdown_tables_split_only_between_rows_and_repeat_headers()
    test_markdown_table_keeps_single_overlong_row_intact()
    test_markdown_table_rules_apply_to_parent_and_child_chunks()
    test_plain_legal_headings_keep_chapters_in_separate_parents()
    test_evidence_windows_mark_truncation_and_preserve_article_boundary()
    test_grounding_verifier_revises_and_fails_closed()
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
    test_graph_entity_repository_uses_scoped_bm25_query()
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
    test_external_progress_events_include_grounding_stage()
    test_mcp_policy_concurrent_first_write_reloads_existing()
    test_mcp_function_name_is_stable_and_sanitized()
    test_run_to_response_maps_run_fields()
    test_regenerated_agent_run_starts_from_a_fresh_checkpoint()
    test_repeated_run_feedback_write_is_idempotent()
    test_agent_usage_normalizes_provider_metadata()
    test_agent_memory_compacts_old_turns()
    test_agent_memory_query_is_bounded_and_projected()
    test_mcp_server_to_response()
    test_unified_mcp_policy_projection_fails_closed_and_honors_kill_switch()
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
