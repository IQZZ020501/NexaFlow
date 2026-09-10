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
import json
from types import SimpleNamespace

import tests.support  # noqa: F401  (sets required env before app imports)

from fastapi import HTTPException
from app.application.models.registry import (
    is_masked_secret,
    normalize_model_type,
    normalize_provider_credentials,
    normalize_url_credential,
    validate_status,
)
from app.domain.knowledge.retrieval import (
    MAX_PARENT_CONTEXT_CHARS,
    RankedHit,
    bounded_text_chunks,
    parent_evidence,
    parent_context,
    reciprocal_rank_fusion,
)
from app.adapters.rag.vector_store import VectorHit
from app.entities.agents import Agent
from app.entities.knowledge import KnowledgeBase
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.entities.identity.user import User
from app.schemas.knowledge.graph import (
    KnowledgeGraphImportRecord,
    KnowledgeGraphReviewDecisionRequest,
)
from app.domain.agents.access.permissions import (
    effective_agent_permission,
    validate_agent_permission,
)
from app.domain.knowledge.tasks.orchestration import (
    normalized_document_artifact,
    parse_task_options,
)
from app.domain.knowledge.service import (
    clean_upload_filename,
    effective_permission,
    validate_permission,
)
from app.domain.knowledge.graph.schema import (
    GraphSchemaDefinition,
    default_graph_schema,
    graph_schema_hash,
    normalize_graph_name,
)
from app.domain.knowledge.graph.extraction import (
    EntityLexiconEntry,
    ExtractedEntity,
    ExtractionChunk,
    GraphExtractionBatch,
    build_entity_lexicon,
    deduplicate_extracted_entities,
    extract_graph_batch,
    validate_extraction_batch,
)
from app.domain.knowledge.graph.resolution import (
    claim_fingerprint,
    choose_automatic_entity_match,
    initial_claim_status,
)
from app.domain.knowledge.graph.extraction import (
    ExtractedClaim,
    _entity_type,
)
from app.domain.knowledge.graph import traversal as graph_traversal
from app.domain.knowledge.graph.traversal import (
    GraphEvidenceView,
    _collect_result_items,
    _load_path_records,
    assemble_path,
)
from app.infra.db.repositories.knowledge import graph as graph_repository
from unittest.mock import AsyncMock, patch
from app.application.knowledge.graph.build import (
    _EntityResolutionContext,
    _parse_datetime,
    _unique_surface_span,
    finalize_abandoned_graph_reservations,
)
from app.application.knowledge.graph.maintenance import _revision_source_versions
from app.application.resource_folders.service import descendant_folder_ids
from app.entities.resource_folders.models import ResourceFolder



from app.domain.knowledge.documents.parsing import (
    KnowledgePipelineError,
)
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

def test_default_graph_schema_is_stable() -> None:
    schema = default_graph_schema()
    assert "Entity" in {item.name for item in schema.entity_types}
    assert "Entity" in schema.relation("related_to").source_types
    assert "Entity" in schema.relation("related_to").target_types
    assert schema.relation("supersedes").traversable is True
    assert schema.relation("conflicts_with").review_required is True
    assert normalize_graph_name("  信息\u3000科技部 ") == "信息 科技部"
    assert graph_schema_hash(schema) == graph_schema_hash(schema)

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
                    "evidence_span": [
                        content.index(quote),
                        content.index(quote) + len(quote),
                    ],
                }
            ],
        }
    )
    claim = validate_extraction_batch(valid, chunks).claims[0]
    assert claim.predicate == "uses_phone"
    assert content[claim.start_offset : claim.end_offset] == quote
    claim_schema = GraphExtractionBatch.model_json_schema()["$defs"]["ExtractedClaim"]
    assert "evidence_span" in claim_schema["properties"]
    assert "quote" not in claim_schema["properties"]

    account_schema = GraphSchemaDefinition.model_validate(
        {
            "entity_types": [{"name": "Account"}, {"name": "Phone"}],
            "relations": [
                {
                    "name": "uses_phone",
                    "source_types": ["Account"],
                    "target_types": ["Phone"],
                }
            ],
        }
    )
    reversed_claim = valid.model_copy(deep=True)
    reversed_claim.claims[0].subject_temp_id = "p"
    reversed_claim.claims[0].object_temp_id = "a"
    normalized = validate_extraction_batch(reversed_claim, chunks, account_schema)
    assert normalized.claims[0].subject_temp_id == "a"
    assert normalized.claims[0].object_temp_id == "p"

    inverse_claim = GraphExtractionBatch.model_validate(
        {
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
                    "subject_temp_id": "term",
                    "predicate": "defined_by",
                    "object_temp_id": "policy",
                    "evidence_chunk_id": "chunk-2",
                    "evidence_span": [0, 9],
                }
            ],
        }
    )
    normalized_inverse = validate_extraction_batch(
        inverse_claim,
        [ExtractionChunk("chunk-2", "doc-2", "术语 A 由制度 A 定义。")],
        default_graph_schema(),
    ).claims[0]
    assert normalized_inverse.predicate == "defines"
    assert normalized_inverse.subject_temp_id == "policy"
    assert normalized_inverse.object_temp_id == "term"

    implicit_regulation = GraphExtractionBatch.model_validate(
        {
            "entities": [
                {
                    "temp_id": "regulation",
                    "entity_type": "Regulation",
                    "canonical_name": "校外培训管理规定",
                },
                {
                    "temp_id": "role",
                    "entity_type": "Role",
                    "canonical_name": "学生",
                },
            ],
            "claims": [
                {
                    "subject_temp_id": "regulation",
                    "predicate": "applies_to",
                    "object_temp_id": "role",
                    "evidence_chunk_id": "chunk-2",
                    "evidence_span": [0, 9],
                }
            ],
        }
    )
    assert validate_extraction_batch(
        implicit_regulation,
        [ExtractionChunk("chunk-2", "doc-2", "本规定适用于学生。")],
        default_graph_schema(),
    ).claims[0].predicate == "applies_to"

    invalid = valid.model_copy(deep=True)
    invalid.claims[0].evidence_span = (0, len(content) + 1)
    try:
        validate_extraction_batch(invalid, chunks)
    except ValueError as exc:
        assert "span" in str(exc).lower()
    else:
        raise AssertionError("unsupported graph evidence must fail")

def test_graph_entity_batch_normalization_deduplicates_exact_identity() -> None:
    entities = [
        ExtractedEntity(
            temp_id="a",
            entity_type="Organization",
            canonical_name=" 人力资源部 ",
            aliases=["HR", "hr"],
            properties={"source": "a"},
        ),
        ExtractedEntity(
            temp_id="b",
            entity_type="Organization",
            canonical_name="人力资源部",
            aliases=["Human Resources"],
            properties={"owner": "alice"},
        ),
    ]
    deduplicated, representative_ids = deduplicate_extracted_entities(entities)
    assert len(deduplicated) == 1
    assert representative_ids == {"a": "a", "b": "a"}
    assert deduplicated[0].aliases == ["HR", "Human Resources"]
    assert deduplicated[0].properties == {"source": "a", "owner": "alice"}

def test_graph_rule_extractor_builds_typed_claims_with_exact_evidence() -> None:
    content = "制度 A 定义术语 A。人力资源部负责员工入职流程。"
    result = extract_graph_batch(
        default_graph_schema(),
        [ExtractionChunk("chunk-1", "doc-1", content)],
    )
    entities = {item.canonical_name: item for item in result.batch.entities}
    assert {item.predicate for item in result.batch.claims} == {
        "defines",
        "responsible_for",
    }
    assert entities["制度 A"].entity_type == "Regulation"
    assert entities["术语 A"].entity_type == "Concept"
    assert entities["人力资源部"].entity_type == "Department"
    assert entities["员工入职流程"].entity_type == "Process"
    for claim in result.batch.claims:
        evidence = content[claim.start_offset : claim.end_offset]
        assert evidence in {"制度 A 定义术语 A", "人力资源部负责员工入职流程"}
    assert len(result.prompt_hash) == 64

def test_graph_rule_extractor_uses_human_lexicon_and_skips_unknown_text() -> None:
    schema = default_graph_schema()
    result = extract_graph_batch(
        schema,
        [ExtractionChunk("chunk-1", "doc-1", "HR负责员工入职流程。")],
        build_entity_lexicon(
            [
                EntityLexiconEntry(
                    entity_type="Department",
                    canonical_name="人力资源部",
                    aliases=("HR",),
                ),
            ]
        ),
    )
    subject = next(
        item for item in result.batch.entities if item.canonical_name == "人力资源部"
    )
    assert subject.aliases == ["HR"]
    assert result.batch.claims[0].predicate == "responsible_for"

    empty = extract_graph_batch(
        schema,
        [ExtractionChunk("chunk-2", "doc-1", "这是一段没有显式关系的普通说明。")],
    )
    assert empty.batch == GraphExtractionBatch()

def test_graph_rule_extractor_rejects_oversized_input() -> None:
    try:
        extract_graph_batch(
            default_graph_schema(),
            [ExtractionChunk("large", "doc-1", "x" * 25_000)],
        )
    except ValueError as exc:
        assert str(exc) == "Graph extraction input exceeds the per-call limit."
    else:
        raise AssertionError("oversized extraction input must be rejected")

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

def test_graph_extracted_claim_requires_exactly_one_object_and_bounded_span() -> None:
    base = {
        "subject_temp_id": "a",
        "predicate": "owns",
        "evidence_chunk_id": "chunk-1",
    }
    for object_kwargs in ({}, {"object_temp_id": "b", "object_value": "v"}):
        try:
            ExtractedClaim(evidence_span=(0, 4), **base, **object_kwargs)
        except ValueError as exc:
            assert "Exactly one claim object" in str(exc)
        else:
            raise AssertionError("claim object cardinality must be enforced")
    for span in ((4, 4), (5, 3), (0, 4_001)):
        try:
            ExtractedClaim(
                object_temp_id="b",
                evidence_span=span,
                **base,
            )
        except ValueError as exc:
            assert "Evidence offsets are invalid." in str(exc)
        else:
            raise AssertionError("evidence span bounds must be enforced")

def test_graph_entity_dedup_merges_aliases_and_filters_invalid_ones() -> None:
    first = ExtractedEntity(
        temp_id="a",
        entity_type="Organization",
        canonical_name="人力资源部",
        aliases=["HR", "!!"],
        properties={"src": 1},
    )
    second = ExtractedEntity(
        temp_id="b",
        entity_type="Organization",
        canonical_name="人力资源部",
        aliases=["HR", " ", "人事部"],
        properties={"owner": "bob"},
    )
    deduplicated, representative_ids = deduplicate_extracted_entities([first, second])
    assert representative_ids == {"a": "a", "b": "a"}
    merged = deduplicated[0]
    assert merged.temp_id == "a"
    assert merged.aliases == ["HR", "!!", "人事部"]
    assert merged.properties == {"src": 1, "owner": "bob"}

def test_graph_rule_extractor_dedupes_entities_within_a_call() -> None:
    content = "制度 A 定义术语 A。制度 A 定义术语 B。"
    result = extract_graph_batch(
        default_graph_schema(),
        [ExtractionChunk("chunk-1", "doc-1", content)],
    )
    regulations = [
        item for item in result.batch.entities if item.canonical_name == "制度 A"
    ]
    assert len(regulations) == 1
    assert len(result.batch.claims) == 2

def test_graph_batch_validation_rejects_broken_references() -> None:
    chunks = [ExtractionChunk("chunk-1", "doc-1", "账户 A 共用手机号 P。")]
    account_schema = GraphSchemaDefinition.model_validate(
        {
            "entity_types": [{"name": "Account"}, {"name": "Phone"}],
            "relations": [
                {
                    "name": "uses_phone",
                    "source_types": ["Account"],
                    "target_types": ["Phone"],
                }
            ],
        }
    )
    entities = [
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
    ]
    claim = {
        "subject_temp_id": "a",
        "predicate": "uses_phone",
        "object_temp_id": "p",
        "evidence_chunk_id": "chunk-1",
        "evidence_span": (0, 4),
    }

    def expect_value_error(batch, message_part: str, schema=None) -> None:
        try:
            validate_extraction_batch(batch, chunks, schema)
        except ValueError as exc:
            assert message_part.lower() in str(exc).lower(), str(exc)
        else:
            raise AssertionError(f"expected failure: {message_part}")

    expect_value_error(
        GraphExtractionBatch.model_validate(
            {"entities": [*entities, dict(entities[0])], "claims": [claim]}
        ),
        "unique",
    )
    ghost_type = GraphExtractionBatch.model_validate(
        {
            "entities": [{**entities[0], "entity_type": "Ghost"}, entities[1]],
            "claims": [claim],
        }
    )
    expect_value_error(ghost_type, "not allowed by the graph schema", account_schema)
    unknown_subject = GraphExtractionBatch.model_validate(
        {
            "entities": entities,
            "claims": [{**claim, "subject_temp_id": "zz"}],
        }
    )
    expect_value_error(unknown_subject, "unknown entity")
    unknown_chunk = GraphExtractionBatch.model_validate(
        {
            "entities": entities,
            "claims": [{**claim, "evidence_chunk_id": "chunk-x"}],
        }
    )
    expect_value_error(unknown_chunk, "unknown evidence chunk")
    bad_predicate = GraphExtractionBatch.model_validate(
        {
            "entities": entities,
            "claims": [{**claim, "predicate": "hates"}],
        }
    )
    try:
        validate_extraction_batch(bad_predicate, chunks, account_schema)
    except ValueError as exc:
        assert "not allowed by the graph schema" in str(exc)
    else:
        raise AssertionError("unsupported predicate must fail")
    inverse_without_entity = GraphExtractionBatch.model_validate(
        {
            "entities": [
                {
                    "temp_id": "term",
                    "entity_type": "Concept",
                    "canonical_name": "术语 A",
                }
            ],
            "claims": [
                {
                    "subject_temp_id": "term",
                    "predicate": "defined_by",
                    "object_temp_id": None,
                    "object_value": "制度文本",
                    "evidence_chunk_id": "chunk-2",
                    "evidence_span": (0, 4),
                }
            ],
        }
    )
    try:
        validate_extraction_batch(
            inverse_without_entity,
            [ExtractionChunk("chunk-2", "doc-2", "术语 A 由制度 A 定义。")],
            default_graph_schema(),
        )
    except ValueError as exc:
        assert "requires an entity object" in str(exc)
    else:
        raise AssertionError("inverse predicate without entity object must fail")

def test_graph_entity_type_inference_and_fallback() -> None:
    known = {
        "Department",
        "Process",
        "Regulation",
        "Concept",
        "Organization",
        "System",
        "Form",
        "Event",
    }
    expectations = {
        "人力资源部": "Department",
        "员工入职流程": "Process",
        "校外培训管理规定": "Regulation",
        "基本概念": "Concept",
        "示例公司": "Organization",
        "审批系统": "System",
        "入库表单": "Form",
        "评审会议": "Event",
    }
    allowed = sorted(known)
    for surface, expected in expectations.items():
        assert _entity_type(surface, "X", allowed, known) == expected
    assert _entity_type("普通名词", "Ghost", ["Ghost"], known) == "Ghost"

def test_graph_rule_extractor_guards_skip_noise_clauses() -> None:
    content = (
        "制度 A 不定义术语 A。　。定义术语 A。"
        "制度 C 定义"
        + "长" * 501
        + "。制度 B 定义术语 B。"
    )
    result = extract_graph_batch(
        default_graph_schema(),
        [ExtractionChunk("chunk-1", "doc-1", content)],
    )
    predicates = {claim.predicate for claim in result.batch.claims}
    assert predicates == {"defines"}
    names = {item.canonical_name for item in result.batch.entities}
    assert names == {"制度 B", "术语 B"}
    claim = result.batch.claims[0]
    assert content[claim.start_offset : claim.end_offset] == "制度 B 定义术语 B"

def test_graph_rule_extractor_caps_entities_and_claims() -> None:
    from app.domain.knowledge.graph import extraction as extraction_module

    with patch.object(extraction_module, "MAX_EXTRACTED_CLAIMS", 1):
        result = extraction_module.extract_graph_batch(
            default_graph_schema(),
            [
                ExtractionChunk(
                    "chunk-1",
                    "doc-1",
                    "制度 A 定义术语 A。制度 B 定义术语 B。",
                )
            ],
        )
    assert len(result.batch.claims) <= 1

def test_graph_surface_span_requires_unique_occurrence() -> None:
    entity = ExtractedEntity(
        temp_id="a",
        entity_type="Account",
        canonical_name="账户 A",
    )
    assert _unique_surface_span(entity, "账户 A 与他人共用。") == (0, 4, "账户 A")
    assert _unique_surface_span(entity, "账户 A 与账户 A 共用。") is None
    aliased = entity.model_copy(update={"aliases": ["甲"]})
    assert _unique_surface_span(aliased, "他称甲。") == (2, 3, "甲")

def test_graph_resolution_context_skips_non_human_aliases() -> None:
    entity = SimpleNamespace(
        id="e1",
        entity_type="Account",
        external_key=None,
        normalized_name="账户 a",
    )
    generated_only = _EntityResolutionContext.build(
        {"e1": entity},
        [
            SimpleNamespace(
                entity_id="e1",
                source="generated",
                normalized_alias="账户 a",
            ),
            SimpleNamespace(
                entity_id="ghost",
                source="human",
                normalized_alias="幽灵",
            ),
        ],
    )
    assert generated_only.human_alias_ids == {}
    human = _EntityResolutionContext.build(
        {"e1": entity},
        [
            SimpleNamespace(
                entity_id="e1",
                source="human",
                normalized_alias="账户 a",
            )
        ],
    )
    assert human.human_alias_ids == {("Account", "账户 a"): {"e1"}}

def test_graph_build_pure_helpers_are_bounded() -> None:
    merged = finalize_abandoned_graph_reservations(
        {
            "reserved_tokens": 500,
            "charged_tokens": 100,
            "estimated_tokens": 50,
            "unreported_model_calls": 1,
        }
    )
    assert merged["reserved_tokens"] == 0
    assert merged["charged_tokens"] == 600
    assert merged["estimated_tokens"] == 550
    assert merged["unreported_model_calls"] == 2
    unchanged = finalize_abandoned_graph_reservations({"reserved_tokens": 0})
    assert unchanged == {"reserved_tokens": 0}
    assert finalize_abandoned_graph_reservations(None) == {}

    parsed = _parse_datetime("2024-01-02T03:04:05Z")
    assert parsed is not None and parsed.year == 2024
    assert _parse_datetime(None) is None
    try:
        _parse_datetime("not-a-date")
    except ValueError as exc:
        assert "timestamp is invalid" in str(exc)
    else:
        raise AssertionError("invalid graph timestamp must fail")

    assert _revision_source_versions(None) is None
    assert (
        _revision_source_versions(SimpleNamespace(stats_json={})) is None
    )
    broken = _revision_source_versions(
        SimpleNamespace(stats_json={"source_versions": ["bad"]})
    )
    assert broken is None
    versions = _revision_source_versions(
        SimpleNamespace(stats_json={"source_versions": {"d1": 3}})
    )
    assert versions == {"d1": "3"}

def test_graph_assemble_path_rejects_inconsistent_paths() -> None:
    def node(entity_id: str, name: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=entity_id,
            entity_type="Account",
            canonical_name=name,
            properties_json={"k": "v"},
        )

    entities = {"a": node("a", "账户 A"), "b": node("b", "账户 B")}
    claims = {
        "c1": SimpleNamespace(
            id="c1",
            predicate="uses_phone",
            subject_entity_id="a",
            object_entity_id="b",
            quality_score=0.9,
            support_count=1,
        ),
        "c-self": SimpleNamespace(
            id="c-self",
            predicate="uses_phone",
            subject_entity_id="a",
            object_entity_id="a",
            quality_score=0.9,
            support_count=1,
        ),
    }
    assert assemble_path(["a", "b"], [], entities, claims, {}) is None
    assert assemble_path(["a", "zz"], ["c1"], entities, claims, {}) is None
    assert assemble_path(["a", "b"], ["c-self"], entities, claims, {}) is None
    forward = assemble_path(["a", "b"], ["c1"], entities, claims, {})
    assert forward is not None
    assert forward.steps[0].semantic_direction == "forward"
    reverse = assemble_path(["b", "a"], ["c1"], entities, claims, {})
    assert reverse is not None
    assert reverse.steps[0].semantic_direction == "reverse"

def test_graph_traversal_timeout_and_empty_source_branches() -> None:
    async def scenario() -> None:
        knowledge_base = KnowledgeBase(id="trav-kb", workspace_id="trav-ws")
        revision = SimpleNamespace(id="trav-rev")
        endpoints = [
            SimpleNamespace(
                id="a",
                entity_type="Account",
                canonical_name="账户 A",
                properties_json={},
            ),
            SimpleNamespace(
                id="b",
                entity_type="Account",
                canonical_name="账户 B",
                properties_json={},
            ),
        ]
        try:
            await graph_traversal.shortest_path(
                None,
                knowledge_base,
                revision,
                "a",
                "b",
                max_hops=0,
            )
        except ValueError as exc:
            assert "between 1 and 8" in str(exc)
        else:
            raise AssertionError("path max_hops bounds must be enforced")
        with patch.object(
            graph_repository,
            "list_active_entities_by_ids",
            new=AsyncMock(return_value=endpoints),
        ):
            with patch.object(
                graph_repository,
                "query_shortest_path_rows",
                new=AsyncMock(return_value=([], 7, True)),
            ):
                timed_out = await graph_traversal.shortest_path(
                    None,
                    knowledge_base,
                    revision,
                    "a",
                    "b",
                    max_hops=2,
                )
        assert timed_out.truncated is True
        assert timed_out.limit_reason == "timeout"
        assert timed_out.visited_nodes == 7
        assert timed_out.paths == ()
        with patch.object(
            graph_repository,
            "list_active_entities_by_ids",
            new=AsyncMock(return_value=[]),
        ):
            missing = await graph_traversal.neighborhood(
                None,
                knowledge_base,
                revision,
                "ghost",
                max_hops=1,
            )
        assert missing.resolved_entities == ()
        assert missing.visited_nodes == 0
        try:
            await graph_traversal.neighborhood(
                None,
                knowledge_base,
                revision,
                "a",
                max_hops=4,
            )
        except ValueError as exc:
            assert "between 1 and 3" in str(exc)
        else:
            raise AssertionError("neighborhood max_hops bounds must be enforced")
        with patch.object(
            graph_repository,
            "list_active_entities_by_ids",
            new=AsyncMock(return_value=[endpoints[0]]),
        ):
            with patch.object(
                graph_repository,
                "query_neighborhood_rows",
                new=AsyncMock(return_value=([], 0, True)),
            ):
                neighborhood_timeout = await graph_traversal.neighborhood(
                    None,
                    knowledge_base,
                    revision,
                    "a",
                    max_hops=1,
                )
        assert neighborhood_timeout.limit_reason == "timeout"

    asyncio.run(scenario())

def test_graph_evidence_views_are_capped_per_claim() -> None:
    async def scenario() -> None:
        knowledge_base = KnowledgeBase(id="ev-kb", workspace_id="ev-ws")
        rows = [(["a", "b"], ["c1"]), (["b", "c"], ["c2"])]
        entities = [
            SimpleNamespace(
                id=entity_id,
                entity_type="Account",
                canonical_name=name,
                properties_json={},
            )
            for entity_id, name in (("a", "A"), ("b", "B"), ("c", "C"))
        ]
        claims = [
            SimpleNamespace(
                id="c1",
                predicate="uses_phone",
                subject_entity_id="a",
                object_entity_id="b",
                quality_score=1.0,
                support_count=1,
            ),
            SimpleNamespace(
                id="c2",
                predicate="uses_phone",
                subject_entity_id="b",
                object_entity_id="c",
                quality_score=1.0,
                support_count=1,
            ),
        ]
        evidence_rows = [
            (
                SimpleNamespace(
                    id=f"ev-{index}",
                    claim_id="c1" if index < 6 else "c2",
                    document_id="d1",
                    document_filename="d1.md",
                    chunk_id=f"ch-{index}",
                    quote="q",
                    start_offset=0,
                    end_offset=1,
                    source_kind="explicit_text",
                ),
                "d1.md",
                "explicit_text",
                1.0,
                None,
            )
            for index in range(7)
        ]
        with (
            patch.object(
                graph_repository,
                "list_active_entities_by_ids",
                new=AsyncMock(return_value=entities),
            ),
            patch.object(
                graph_repository,
                "list_active_claims_by_ids",
                new=AsyncMock(return_value=claims),
            ),
            patch.object(
                graph_repository,
                "list_ranked_evidence_for_claim_ids",
                new=AsyncMock(return_value=evidence_rows),
            ),
        ):
            loaded_entities, loaded_claims, evidence = (
                await _load_path_records(None, knowledge_base, rows)
            )
        assert set(loaded_entities) == {"a", "b", "c"}
        assert set(loaded_claims) == {"c1", "c2"}
        assert len(evidence["c1"]) == 5
        paths = [
            path
            for entity_ids, claim_ids in rows
            if (path := assemble_path(entity_ids, claim_ids, loaded_entities, loaded_claims, evidence))
            is not None
        ]
        nodes, step_views, evidence_views = _collect_result_items(paths)
        assert {item.id for item in nodes} == {"a", "b", "c"}
        assert {item.claim_id for item in step_views} == {"c1", "c2"}
        assert len(evidence_views) == 6

    asyncio.run(scenario())

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

def test_knowledge_writes_recheck_locked_owner() -> None:
    from app.schemas.knowledge import KnowledgeBaseUpdateRequest
    from app.domain.knowledge.bases import service as knowledge_kb

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

    import json

    from app.application.agents.tools.builder import bounded_knowledge_context

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

def test_inline_grounding_manifest_validation_fails_closed() -> None:
    from app.domain.agents.runtime.grounding import (
        validate_inline_grounding_manifest,
    )

    packets = [
        {
            "chunk_id": "chunk-16",
            "section_path": ["第二章"],
            "content": "第二章\n第十六条。",
        }
    ]
    grounded = validate_inline_grounding_manifest(
        '{"status":"grounded","evidence_ids":["chunk-16"],'
        '"reason_codes":["article_boundary_checked"]}',
        packets,
        "required",
    )
    assert grounded.status == "grounded"
    assert grounded.meta["evidence_ids"] == ["chunk-16"]
    assert grounded.meta["evidence_packet_count"] == 1
    assert grounded.meta["evidence_truncated"] is False
    assert grounded.meta["mode"] == "inline"

    unknown = validate_inline_grounding_manifest(
        '{"status":"grounded","evidence_ids":["unknown"],'
        '"reason_codes":[]}',
        packets,
        "required",
    )
    assert unknown.status == "unavailable"
    assert unknown.meta["error"] == "invalid_evidence_ids"

    required_skip = validate_inline_grounding_manifest(
        '{"status":"skipped","evidence_ids":[],"reason_codes":[]}',
        packets,
        "required",
    )
    assert required_skip.status == "unavailable"
    assert required_skip.meta["error"] == "invalid_skip"

    agentic_skip = validate_inline_grounding_manifest(
        '{"status":"skipped","evidence_ids":[],"reason_codes":[]}',
        [],
        "agentic",
    )
    assert agentic_skip.status == "skipped"


def test_inline_grounding_stream_filter_bounds_and_preserves_output() -> None:
    from app.domain.agents.runtime.grounding import (
        GROUNDING_FALLBACK_ANSWER,
        INLINE_GROUNDING_OPEN,
        MAX_INLINE_GROUNDING_CHARS,
        InlineGroundingStreamFilter,
    )

    packets = [{"chunk_id": "chunk-16", "content": "第十六条。"}]
    required_missing = InlineGroundingStreamFilter(packets, "required")
    assert required_missing.push("# 不应泄露的回答\n") == ""
    assert required_missing.finish() == GROUNDING_FALLBACK_ANSWER
    assert required_missing.visible_content == GROUNDING_FALLBACK_ANSWER
    assert required_missing.outcome is not None
    assert required_missing.outcome.status == "unavailable"
    assert required_missing.outcome.meta["error"] == "missing_manifest"

    agentic_without_evidence = InlineGroundingStreamFilter([], "agentic")
    markdown = "# 标题\n\n- 条目\n"
    assert agentic_without_evidence.push(markdown) == ""
    assert agentic_without_evidence.finish() == markdown
    assert agentic_without_evidence.visible_content == markdown
    assert agentic_without_evidence.outcome is not None
    assert agentic_without_evidence.outcome.status == "skipped"

    preserves_leading_markdown_space = InlineGroundingStreamFilter(packets, "required")
    framed = (
        '<nexaflow-grounding>{"status":"grounded",'
        '"evidence_ids":["chunk-16"],"reason_codes":[]}'
        "</nexaflow-grounding>\n\n# 标题\n\n- 条目\n"
    )
    assert preserves_leading_markdown_space.push(framed) == "\n# 标题\n\n- 条目\n"
    assert preserves_leading_markdown_space.finish() == ""
    assert preserves_leading_markdown_space.visible_content == "\n# 标题\n\n- 条目\n"

    oversized = InlineGroundingStreamFilter(packets, "required")
    oversized.push(INLINE_GROUNDING_OPEN + "x" * MAX_INLINE_GROUNDING_CHARS)
    assert oversized.finish() == GROUNDING_FALLBACK_ANSWER
    assert oversized.outcome is not None
    assert oversized.outcome.meta["error"] == "manifest_too_large"

def test_docx_images_without_alt_text_do_not_add_placeholder_content() -> None:
    from io import BytesIO
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

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
    from unittest.mock import patch

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
    from unittest.mock import patch
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
    from unittest.mock import patch

    from app.domain.knowledge.documents import parsing as pipeline

    expected_extensions = {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".docx",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".md",
        ".markdown",
        ".pdf",
        ".php",
        ".properties",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
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
        ".yaml",
        ".yml",
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
            *pipeline.PLAIN_TEXT_DOCUMENT_EXTENSIONS,
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

        for extension in pipeline.PLAIN_TEXT_DOCUMENT_EXTENSIONS:
            path = Path(directory) / f"source{extension}"
            path.write_text("print('source')", encoding="utf-8")
            text, assets = pipeline.extract_document(
                path.name,
                "application/octet-stream",
                path,
            )
            assert text == "print('source')"
            assert assets == []

def test_pdf_documents_extract_only_the_text_layer() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

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
        )

        assert text == "# 通知\n\n识别文本"
        assert assets == []
        assert calls == [("image/png", b"png")]

        try:
            pipeline.extract_document(path.name, "image/png", path)
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

def test_graph_entity_repository_uses_scoped_bm25_query() -> None:
    from app.infra.db.repositories.knowledge import graph as graph_repository

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
    from app.entities.knowledge import KnowledgeTask
    from app.schemas.knowledge import KnowledgeEvaluationRunRequest
    from app.domain.knowledge.evaluation import service as evaluation_service

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
    from app.infra.db.repositories.knowledge import (
        evaluation as evaluation_repository,
    )
    from app.schemas.knowledge import KnowledgeEvaluationCaseCreateRequest
    from app.domain.knowledge.evaluation import service as evaluation_service

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
    from app.infra.db.repositories.knowledge import (
        evaluation as evaluation_repository,
    )
    from app.domain.knowledge.models import (
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
    from unittest.mock import patch

    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference

    from app.domain.knowledge.documents.parsing import KnowledgePipelineError
    from app.domain.knowledge.documents.qa_import import (
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

def test_explicit_reference_extraction_is_bounded_and_internal() -> None:
    from app.entities.knowledge import (
        KnowledgeDocument,
        KnowledgeDocumentParentChunk,
    )
    from app.domain.knowledge.documents.references import (
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
    from app.domain.knowledge.documents import references as reference_service

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

def test_knowledge_document_and_attachment_response_mapping() -> None:
    from app.entities.knowledge import KnowledgeAttachment, KnowledgeDocument
    from app.domain.knowledge.service import (
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
    from app.domain.knowledge.service import knowledge_base_to_response

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
    test_graph_schema_rejects_unknown_relation_endpoint()
    test_default_graph_schema_is_stable()
    test_normalized_document_artifact_is_content_addressed()
    test_graph_extraction_requires_exact_chunk_evidence()
    test_graph_entity_batch_normalization_deduplicates_exact_identity()
    test_graph_rule_extractor_builds_typed_claims_with_exact_evidence()
    test_graph_rule_extractor_uses_human_lexicon_and_skips_unknown_text()
    test_graph_rule_extractor_rejects_oversized_input()
    test_graph_entity_auto_match_requires_deterministic_identity()
    test_graph_claim_fingerprint_and_initial_status_are_deterministic()
    test_graph_extracted_claim_requires_exactly_one_object_and_bounded_span()
    test_graph_entity_dedup_merges_aliases_and_filters_invalid_ones()
    test_graph_rule_extractor_dedupes_entities_within_a_call()
    test_graph_batch_validation_rejects_broken_references()
    test_graph_entity_type_inference_and_fallback()
    test_graph_rule_extractor_guards_skip_noise_clauses()
    test_graph_rule_extractor_caps_entities_and_claims()
    test_graph_surface_span_requires_unique_occurrence()
    test_graph_resolution_context_skips_non_human_aliases()
    test_graph_build_pure_helpers_are_bounded()
    test_graph_assemble_path_rejects_inconsistent_paths()
    test_graph_traversal_timeout_and_empty_source_branches()
    test_graph_evidence_views_are_capped_per_claim()
    test_graph_review_decision_request_is_bounded()
    test_graph_import_record_requires_one_object_kind()
    test_knowledge_writes_recheck_locked_owner()
    test_clean_upload_filename_sanitizes_path_and_classification()
    test_parse_task_options_validates_boundaries()
    test_markdown_tables_split_only_between_rows_and_repeat_headers()
    test_markdown_table_keeps_single_overlong_row_intact()
    test_markdown_table_rules_apply_to_parent_and_child_chunks()
    test_plain_legal_headings_keep_chapters_in_separate_parents()
    test_evidence_windows_mark_truncation_and_preserve_article_boundary()
    test_inline_grounding_manifest_validation_fails_closed()
    test_inline_grounding_stream_filter_bounds_and_preserves_output()
    test_docx_images_without_alt_text_do_not_add_placeholder_content()
    test_docx_image_mime_cannot_shape_asset_paths()
    test_archive_limits_run_before_document_conversion()
    test_supported_document_formats_are_accepted()
    test_pdf_documents_extract_only_the_text_layer()
    test_image_documents_use_the_configured_vision_extractor()
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
    test_knowledge_document_and_attachment_response_mapping()
    test_knowledge_base_to_response()
    print("KNOWLEDGE_UNIT_OK")


if __name__ == "__main__":
    main()
