from dataclasses import fields
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.platform.models import ResourcePermission as ResourcePermissionOrm
from app.domain.platform.models import User as UserOrm
from app.domain.platform.models import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.entities.tools import (
    ApplicationToolBinding,
    Tool,
    ToolDraft,
    ToolInvocation,
    ToolPolicy,
    ToolRef,
    ToolSource,
    ToolVersion,
)
from app.entities.identity.user import User
from app.infra.db.mapping import save, to_entity
from app.domain.tools.models import (
    ApplicationToolBinding as ApplicationToolBindingOrm,
)
from app.domain.tools.models import Tool as ToolOrm
from app.domain.tools.models import ToolDraft as ToolDraftOrm
from app.domain.tools.models import ToolInvocation as ToolInvocationOrm
from app.domain.tools.models import ToolPolicy as ToolPolicyOrm
from app.domain.tools.models import ToolSource as ToolSourceOrm
from app.domain.tools.models import ToolVersion as ToolVersionOrm
from app.domain.tools.runtime import (
    TOOL_INVOCATION_APPROVED,
    TOOL_INVOCATION_AWAITING_APPROVAL,
    TOOL_INVOCATION_CLAIMABLE_STATUSES,
    TOOL_INVOCATION_QUEUED,
    TOOL_INVOCATION_RUNNING,
    TOOL_INVOCATION_TERMINAL_STATUSES,
    TOOL_INVOCATION_UNCERTAIN,
    exhausted_tool_invocation_terminal_state,
)

ToolCatalogRow = tuple[
    Tool,
    ToolSource,
    ToolVersion | None,
    ToolDraft | None,
    ResourcePermission | None,
]
ToolCatalogDetailRow = tuple[
    Tool,
    ToolSource,
    ToolVersion | None,
    ToolDraft | None,
    ToolPolicy | None,
    ResourcePermission | None,
]
McpCatalogRow = tuple[ToolSource, Tool, ToolVersion, ToolPolicy | None]
ApplicationToolSnapshotRow = tuple[
    str,
    ApplicationToolBinding,
    Tool | None,
    ToolSource | None,
    ToolVersion | None,
    ToolPolicy | None,
    User | None,
    str | None,
    ResourcePermission | None,
]



from app.infra.db.repositories.tools.invocations import _tool_invocation_effect
from app.infra.db.repositories.tools.invocations import get_tool_invocation
from app.infra.db.repositories.tools.invocations import get_tool_invocation_by_id
from app.infra.db.repositories.tools.invocations import get_tool_invocation_by_idempotency_key
from app.infra.db.repositories.tools.invocations import create_or_get_tool_invocation
from app.infra.db.repositories.tools.invocations import refresh_tool_invocation_deadline
from app.infra.db.repositories.tools.invocations import resolve_tool_invocation_approval
from app.infra.db.repositories.tools.invocations import claim_tool_invocation
from app.infra.db.repositories.tools.invocations import finalize_tool_invocation
from app.infra.db.repositories.tools.invocations import fail_pending_tool_invocation
from app.infra.db.repositories.tools.invocations import requeue_tool_invocation
from app.infra.db.repositories.tools.invocations import list_tool_invocations
from app.infra.db.repositories.tools.invocations import settle_exhausted_agent_tool_invocations
from app.infra.db.repositories.tools.invocations import settle_cancelled_agent_tool_invocations
from app.infra.db.repositories.tools.invocations import has_unsettled_agent_tool_invocations
from app.infra.db.repositories.tools.invocations import list_recoverable_tool_test_invocation_ids
from app.infra.db.repositories.tools.invocations import save_tool_invocation
from app.infra.db.repositories.tools.catalog import get_tool_source
from app.infra.db.repositories.tools.catalog import lock_tool_source
from app.infra.db.repositories.tools.catalog import list_tool_sources
from app.infra.db.repositories.tools.catalog import list_mcp_tool_sources
from app.infra.db.repositories.tools.catalog import list_mcp_catalog_rows
from app.infra.db.repositories.tools.catalog import save_tool_source
from app.infra.db.repositories.tools.catalog import get_tool
from app.infra.db.repositories.tools.catalog import get_tool_by_function_name
from app.infra.db.repositories.tools.catalog import get_tool_by_source_key
from app.infra.db.repositories.tools.catalog import lock_tool
from app.infra.db.repositories.tools.catalog import list_tools
from app.infra.db.repositories.tools.catalog import list_tool_catalog_rows
from app.infra.db.repositories.tools.catalog import get_tool_catalog_detail_row
from app.infra.db.repositories.tools.catalog import list_tools_by_source
from app.infra.db.repositories.tools.catalog import save_tool
from app.infra.db.repositories.tools.catalog import get_tool_version
from app.infra.db.repositories.tools.catalog import get_tool_version_by_hash
from app.infra.db.repositories.tools.catalog import list_tool_versions
from app.infra.db.repositories.tools.catalog import save_tool_version
from app.infra.db.repositories.tools.catalog import get_tool_policy
from app.infra.db.repositories.tools.catalog import list_tool_policies
from app.infra.db.repositories.tools.catalog import save_tool_policy
from app.infra.db.repositories.tools.catalog import update_tool_policy_if_revision
from app.infra.db.repositories.tools.catalog import list_application_tool_snapshot_rows
from app.infra.db.repositories.tools.catalog import has_retained_user_audit_references
from app.infra.db.repositories.tools.drafts import get_tool_draft
from app.infra.db.repositories.tools.drafts import list_tool_drafts
from app.infra.db.repositories.tools.drafts import save_tool_draft
from app.infra.db.repositories.tools.bindings import get_application_tool_binding
from app.infra.db.repositories.tools.bindings import list_application_tool_bindings
from app.infra.db.repositories.tools.bindings import list_application_tool_reference_map
from app.infra.db.repositories.tools.bindings import list_application_mcp_reference_map
from app.infra.db.repositories.tools.bindings import save_application_tool_binding
from app.infra.db.repositories.tools.bindings import replace_application_tool_bindings
from app.infra.db.repositories.tools.bindings import sync_application_tool_bindings
