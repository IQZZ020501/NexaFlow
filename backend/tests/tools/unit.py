"""Pure unit tests for the tools feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.tools.unit
"""
import tests.support  # noqa: F401  (sets required env before app imports)

"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
import base64
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.entities.identity.user import User
from app.entities.workspaces.resource_permissions import ResourcePermission


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError("expected HTTPException")

def payload_with(**fields):
    return SimpleNamespace(model_dump=lambda: fields)

def test_builtin_tool_summary_accepts_system_owner() -> None:
    from app.schemas.tools.contracts import ToolSummaryResponse

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
            "created_at": "2026-08-17T00:00:00+00:00",
            "updated_at": "2026-08-18T00:00:00+00:00",
            "permission": None,
            "can_view": True,
            "can_use": True,
            "can_manage": False,
        }
    )

    assert summary.created_by_user_id is None
    assert summary.updated_at > summary.created_at


def test_tool_summary_projects_effective_public_access_and_mcp_policy() -> None:
    from app.application.tools.management.service import _summary_response
    from app.domain.tools.access.permissions import ToolAccess
    from app.domain.tools.catalog.service import (
        ToolCatalogItem,
        build_image_generation_tool,
    )
    from app.entities.tools import ToolSource

    tool, version, policy = build_image_generation_tool("workspace-1")
    policy.allowed_access_sources = ["console"]
    summary = _summary_response(
        ToolCatalogItem(
            tool=tool,
            source=ToolSource(
                id=tool.source_id,
                workspace_id=tool.workspace_id,
                kind="builtin",
                name="Built-in",
            ),
            version=version,
            draft=None,
            policy=policy,
            access=ToolAccess(can_view=True, can_use=True, can_manage=False),
            permission=None,
        )
    )

    assert summary.allowed_access_sources == ["console", "public"]
    assert summary.policy_mode is None


def test_image_generation_is_a_bounded_approval_backed_builtin() -> None:
    from app.domain.tools.catalog.service import build_image_generation_tool
    from app.domain.tools.runtime import build_tool_snapshot, validate_tool_arguments
    from app.entities.tools import ToolSource

    tool, version, policy = build_image_generation_tool("workspace-1")
    assert tool.function_name == "generate_image"
    assert version.execution_spec == {"builtin": "image_generation"}
    assert policy.approval == "each_call"
    assert policy.effect == "external_write"
    assert policy.workflow_callable is False
    snapshot = build_tool_snapshot(
        tool,
        ToolSource(id=tool.source_id, workspace_id=tool.workspace_id, kind="builtin"),
        version,
        policy,
        "user-1",
    )
    validate_tool_arguments(
        snapshot, {"prompt": "A watercolor mountain", "size": "square"}
    )
    for arguments in ({"prompt": ""}, {"prompt": "hello", "size": "gigantic"}):
        try:
            validate_tool_arguments(snapshot, arguments)
        except ValueError:
            continue
        raise AssertionError("Invalid image arguments were accepted.")


def test_image_tool_queue_freezes_its_model_configuration() -> None:
    from app.application.tools.runtime.adapters import image_generation
    from app.application.tools.runtime.contracts import ToolInvocationContext
    from app.application.tools.runtime.service import queue_tool_invocation
    from app.domain.tools.catalog.service import build_image_generation_tool
    from app.domain.tools.runtime import build_tool_snapshot
    from app.entities.tools import ToolSource
    from app.infra.db.repositories.tools import repository as tool_repository

    tool, version, policy = build_image_generation_tool("workspace-1")
    snapshot = build_tool_snapshot(
        tool,
        ToolSource(id=tool.source_id, workspace_id=tool.workspace_id, kind="builtin"),
        version,
        policy,
        "user-1",
    )
    context = ToolInvocationContext(
        workspace_id="workspace-1",
        origin="agent",
        root_run_id="run-1",
        run_id="run-1",
        invocation_id="call-1",
        execution_user_id="user-1",
        access_source="console",
        deadline_at=datetime.now(UTC),
        idempotency_key="image-key",
    )
    preapproved_context = replace(
        context,
        invocation_id="call-2",
        idempotency_key="image-key-preapproved",
        approval_required=False,
    )
    db = SimpleNamespace()
    resource_snapshot = {
        "image_model": {
            "schema_version": 1,
            "model_id": "image-model-1",
            "fingerprint": "a" * 64,
        }
    }

    async def keep_candidate(_db, candidate):
        return candidate

    with (
        patch.object(
            image_generation,
            "build_image_model_resource_snapshot",
            new=AsyncMock(return_value=resource_snapshot),
        ) as freeze_model,
        patch.object(
            tool_repository,
            "create_or_get_tool_invocation",
            new=AsyncMock(side_effect=keep_candidate),
        ),
        patch.object(
            tool_repository,
            "refresh_tool_invocation_deadline",
            new=AsyncMock(return_value=None),
        ),
    ):
        invocation = asyncio.run(
            queue_tool_invocation(
                db,
                snapshot,
                {"prompt": "A mountain"},
                context,
            )
        )
        preapproved = asyncio.run(
            queue_tool_invocation(
                db,
                snapshot,
                {"prompt": "A mountain"},
                preapproved_context,
            )
        )

    assert freeze_model.await_count == 2
    assert invocation.policy_snapshot["resource_snapshot"] == resource_snapshot
    assert invocation.policy_snapshot["approval_required"] is True
    assert invocation.status == "awaiting_approval"
    assert preapproved.policy_snapshot["approval_required"] is False
    assert preapproved.status == "queued"


def test_image_provider_decodes_only_embedded_png() -> None:
    from app.adapters.llm import image as image_adapter
    from app.ports.llm import ModelProviderError

    png = image_adapter.PNG_SIGNATURE + b"test-image"
    model = SimpleNamespace(provider="model_openai_provider", model_name="gpt-image-1")
    settings = SimpleNamespace(model_request_timeout_seconds=60)
    generated = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(png).decode())]
    )
    images = SimpleNamespace(generate=AsyncMock(return_value=generated))

    class FakeClient:
        def __init__(self, **options):
            assert options == {
                "api_key": "test-key",
                "base_url": "https://api.openai.com/v1",
                "timeout": 300,
                "max_retries": 0,
            }
            self.images = images

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    with (
        patch.object(
            image_adapter,
            "_registered_model_credentials",
            return_value={
                "api_key": "test-key",
                "api_base": "https://api.openai.com/v1",
            },
        ),
        patch.object(image_adapter, "AsyncOpenAI", FakeClient),
    ):
        assert (
            asyncio.run(
                image_adapter.generate_registered_image(
                    model, settings, "A mountain", "landscape"
                )
            )
            == png
        )
        images.generate.assert_awaited_once_with(
            model="gpt-image-1",
            prompt="A mountain",
            size="1536x1024",
            output_format="png",
            n=1,
        )
        images.generate.return_value = SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"not an image").decode())]
        )
        try:
            asyncio.run(
                image_adapter.generate_registered_image(
                    model, settings, "A mountain", "square"
                )
            )
        except ModelProviderError:
            pass
        else:
            raise AssertionError("Non-PNG provider output was accepted.")


def test_image_tool_scopes_model_and_stores_one_artifact() -> None:
    from app.application.agents.runs.snapshots import build_model_runtime_snapshot
    from app.application.tools.runtime.adapters import image_generation
    from app.application.tools.runtime.contracts import ToolInvocationContext

    model = SimpleNamespace(
        id="image-model-1",
        workspace_id="workspace-1",
        provider="model_openai_provider",
        provider_type="openai_compatible",
        model_type="IMAGE",
        model_name="gpt-image-1",
        api_base="https://api.openai.com/v1",
        credential_config={"api_base": "https://api.openai.com/v1"},
        api_key_updated_at=None,
        status="active",
        meta={},
    )
    context = ToolInvocationContext(
        workspace_id="workspace-1",
        origin="agent",
        root_run_id="run-1",
        run_id="run-1",
        invocation_id="call-1",
        execution_user_id="user-1",
        access_source="console",
        deadline_at=datetime.now(UTC),
        idempotency_key="image-key",
        resource_snapshot={"image_model": build_model_runtime_snapshot(model)},
    )
    db = SimpleNamespace(commit=AsyncMock())

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return None

    link = SimpleNamespace(
        artifact_id="file-1",
        format="png",
        filename="generated-image.png",
        media_type="image/png",
        download_url="/api/v1/artifacts/signed",
        expires_at=datetime.now(UTC),
        size_bytes=12,
    )
    with (
        patch.object(image_generation, "get_session_factory", return_value=Session),
        patch.object(
            image_generation.model_repository,
            "list_active_image_models",
            new=AsyncMock(return_value=[model]),
        ) as lookup,
        patch.object(
            image_generation.model_repository,
            "get_registered_model_by_id",
            new=AsyncMock(return_value=model),
        ) as get_model,
        patch.object(
            image_generation, "generate_image", new=AsyncMock(return_value=b"valid png")
        ) as provider,
        patch.object(
            image_generation,
            "create_generated_artifact",
            new=AsyncMock(return_value=link),
        ) as store,
    ):
        result = asyncio.run(
            image_generation.generate_image_artifact(
                SimpleNamespace(), {"prompt": "  A mountain  "}, context
            )
        )
        get_model.assert_awaited_once_with(db, "image-model-1")
        provider.assert_awaited_once_with(
            SimpleNamespace(), model, "A mountain", "square"
        )
        assert store.await_args.kwargs["workspace_id"] == "workspace-1"
        assert store.await_args.kwargs["idempotency_key"] == "image-key"
        assert store.await_args.kwargs["filename"] == "generated-image.png"
        assert result.data["preview_url"] == "/api/v1/artifacts/signed/preview"
        assert result.ok is True

        model.model_name = "gpt-image-2"
        try:
            asyncio.run(
                image_generation.generate_image_artifact(
                    SimpleNamespace(), {"prompt": "A mountain"}, context
                )
            )
        except ValueError as exc:
            assert "changed after this call was queued" in str(exc)
        else:
            raise AssertionError("A drifted image model was accepted.")

        lookup.return_value = []
        try:
            asyncio.run(
                image_generation.build_image_model_resource_snapshot(db, "workspace-1")
            )
        except ValueError as exc:
            assert "Configure an active" in str(exc)
        else:
            raise AssertionError("Missing image model was accepted.")
        lookup.return_value = [model, model]
        try:
            asyncio.run(
                image_generation.build_image_model_resource_snapshot(db, "workspace-1")
            )
        except ValueError as exc:
            assert "exactly one" in str(exc)
        else:
            raise AssertionError("Ambiguous image models were accepted.")
        provider.assert_awaited_once()


def test_tool_ref_schema_requires_canonical_ids() -> None:
    from pydantic import ValidationError

    from app.schemas.tools.contracts import ToolRefSchema

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

def test_effective_tool_access_matrix() -> None:
    from app.entities.tools import ToolAccess, effective_tool_access

    full_access = ToolAccess(can_view=True, can_use=True, can_manage=True)
    assert effective_tool_access(is_owner=True, is_workspace_admin=False, grant=None) == full_access
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

def test_tool_authorization_applies_builtin_and_grant_rules() -> None:
    from app.application.tools import evaluate_tool_authorization
    from app.entities.tools import Tool, ToolAccess

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
    system_python = Tool(id="time-1", kind="python")
    system_python_authorization = evaluate_tool_authorization(
        system_python,
        member,
        "member",
        None,
    )
    assert system_python_authorization.access == ToolAccess(
        can_view=True,
        can_use=True,
        can_manage=False,
    )
    assert system_python_authorization.permission == "use"

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
    # Workspace roles no longer widen tool access: only the owner or a grant.
    assert admin_authorization.access == ToolAccess(
        can_view=False,
        can_use=False,
        can_manage=False,
    )
    assert admin_authorization.permission is None

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

def test_artifact_tool_accepts_sandbox_sized_content() -> None:
    from app.domain.tools.catalog.service import build_artifact_tool

    _tool, version, _policy = build_artifact_tool("workspace-1")
    assert version.input_schema["properties"]["content"]["maxLength"] == 262144

def test_documents_skill_formal_legal_contract_is_versioned() -> None:
    from app.domain.tools.catalog.service import build_skill_artifact_tool

    tool, version, _policy = build_skill_artifact_tool("workspace-1", "documents")
    rebuilt = build_skill_artifact_tool("workspace-1", "documents")[1]
    assert version.input_schema["properties"]["style"]["type"] == "string"
    assert version.input_schema["properties"]["style"]["enum"] == [
        "report",
        "formal_legal",
    ]
    assert "default" not in version.input_schema["properties"]["style"]
    assert "formal_legal" in version.description
    assert "`> `" in version.description
    assert "`---`" in version.description
    assert tool.current_version_id == version.id == rebuilt.id
    assert version.definition_hash == rebuilt.definition_hash


def test_documents_skill_reference_input_uses_bounded_large_payload_limit() -> None:
    from types import SimpleNamespace

    from app.domain.tools.runtime import (
        MAX_DOCUMENT_TOOL_INPUT_BYTES,
        MAX_TOOL_INPUT_BYTES,
        tool_input_size_limit,
        validate_tool_arguments,
    )

    snapshot = SimpleNamespace(
        function_name="documents_skill",
        input_schema={
            "type": "object",
            "properties": {"reference_docx_base64": {"type": "string"}},
        },
    )
    assert tool_input_size_limit(snapshot) == MAX_DOCUMENT_TOOL_INPUT_BYTES
    validate_tool_arguments(
        snapshot,
        {"reference_docx_base64": "x" * (MAX_TOOL_INPUT_BYTES + 1)},
    )

    ordinary_snapshot = SimpleNamespace(
        function_name="custom_tool",
        input_schema={"type": "object", "properties": {}},
    )
    assert tool_input_size_limit(ordinary_snapshot) == MAX_TOOL_INPUT_BYTES


def test_pptx_skill_exposes_pptd_design_animation_and_media_contract() -> None:
    import asyncio
    from types import SimpleNamespace

    from app.domain.agents.runtime import AgentToolResult, create_agent_tool
    from app.domain.tools.catalog.service import build_skill_artifact_tool
    from app.domain.tools.runtime import (
        MAX_PPTX_TOOL_INPUT_BYTES,
        normalize_tool_arguments,
        tool_input_size_limit,
        validate_tool_arguments,
    )

    _tool, version, _policy = build_skill_artifact_tool("workspace-1", "pptx")
    presentation = version.input_schema["properties"]["presentation"]
    properties = presentation["properties"]
    assert len(properties["design_system"]["enum"]) == 30
    assert (
        len(
            properties["slides"]["items"]["properties"]["animations"]["items"][
                "properties"
            ]["effect"]["enum"]
        )
        == 22
    )
    assert "open-kimi-ppt" in version.description
    snapshot = SimpleNamespace(
        function_name="pptx_skill", input_schema=version.input_schema
    )
    assert tool_input_size_limit(snapshot) == MAX_PPTX_TOOL_INPUT_BYTES

    arguments = normalize_tool_arguments(
        "pptx_skill",
        version.input_schema,
        {
            "filename": "modern.pptx",
            "scenario": "tech-engineering",
            "design_system": "blue-flame-brand",
            "slides": [
                {
                    "page_type": "cover",
                    "elements": [
                        {
                            "elementId": "title",
                            "elementType": "text",
                            "bounds": [80, 180, 800, 100],
                            "content": {"style": "$title", "text": "PPTD"},
                        }
                    ],
                    "animations": [
                        {
                            "elementId": "title",
                            "effect": "zoom-in",
                            "trigger": "onClick",
                        }
                    ],
                }
            ],
            "title": "Modern deck",
        },
    )
    validate_tool_arguments(snapshot, arguments)
    assert arguments["presentation"]["scenario"] == "tech-engineering"
    assert "scenario" not in arguments

    legacy_arguments = normalize_tool_arguments(
        "pptx_skill",
        version.input_schema,
        {
            "filename": "legal-reading.pptx",
            "presentation": {
                "title": "读懂法律条文",
                "cover_title_size": 46,
                "design_system": "deep-blue-atlas",
                "scenario": "education-training",
                "page_transition": "fade",
                "slides": [
                    {
                        "page_type": "final",
                        "layout": "quote",
                        "title": "结语",
                        "quote": "定位最小单位 · 核对适用条件 · 写清规范依据",
                    }
                ],
            },
        },
    )
    validate_tool_arguments(snapshot, legacy_arguments)
    normalized_presentation = legacy_arguments["presentation"]
    assert normalized_presentation["theme"]["cover_title_size"] == 46
    assert "cover_title_size" not in normalized_presentation
    assert "scenario" not in normalized_presentation
    assert "design_system" not in normalized_presentation
    assert "page_transition" not in normalized_presentation
    assert "page_type" not in normalized_presentation["slides"][0]

    async def execute(_arguments: str) -> AgentToolResult:
        raise AssertionError("invalid PPTX arguments must not execute")

    invalid_arguments = {
        "filename": "invalid.pptx",
        "presentation": {
            "title": "Invalid",
            "slides": [{"layout": "quote", "quote": "Missing title"}],
        },
    }
    try:
        validate_tool_arguments(snapshot, invalid_arguments)
    except ValueError as exc:
        assert "'title' is a required property" in str(exc)
    else:
        raise AssertionError("invalid durable PPTX arguments were accepted")

    tool = create_agent_tool(
        name="pptx_skill",
        description="PPTX",
        parameters=version.input_schema,
        execute=execute,
    )
    invalid = asyncio.run(tool.ainvoke(invalid_arguments))
    assert invalid.is_error is True
    assert "'title' is a required property" in invalid.content


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


def main() -> None:
    test_builtin_tool_summary_accepts_system_owner()
    test_tool_summary_projects_effective_public_access_and_mcp_policy()
    test_image_generation_is_a_bounded_approval_backed_builtin()
    test_image_tool_queue_freezes_its_model_configuration()
    test_image_provider_decodes_only_embedded_png()
    test_image_tool_scopes_model_and_stores_one_artifact()
    test_tool_ref_schema_requires_canonical_ids()
    test_effective_tool_access_matrix()
    test_tool_authorization_applies_builtin_and_grant_rules()
    test_python_tool_schema_validation_closes_objects()
    test_python_tool_schema_validation_enforces_limits()
    test_python_tool_schema_rejects_defs_depth_bypass()
    test_python_tool_schema_rejects_legacy_definitions_property_bypass()
    test_python_tool_code_is_limited_to_eight_kibibytes()
    test_artifact_tool_accepts_sandbox_sized_content()
    test_documents_skill_formal_legal_contract_is_versioned()
    test_pptx_skill_exposes_pptd_design_animation_and_media_contract()
    test_normalize_mcp_url()
    print("TOOLS_UNIT_OK")


if __name__ == "__main__":
    main()
