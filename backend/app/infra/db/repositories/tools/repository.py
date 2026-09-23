# ruff: noqa: F401
from dataclasses import fields
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.platform.models import ResourcePermission as ResourcePermissionOrm
from app.domain.platform.models import User as UserOrm
from app.domain.platform.models import WorkspaceMembership as WorkspaceMembershipOrm
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
from app.entities.identity.user import User
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
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.infra.db.mapping import save, to_entity

ToolCatalogRow = tuple[
    Tool,
    ToolSource,
    ToolVersion | None,
    ToolDraft | None,
    ToolPolicy | None,
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




from app.infra.db.repositories.tools.bindings import (
    delete_application_tool_bindings_bound_by_user,
    get_application_tool_binding,
    list_application_mcp_reference_map,
    list_application_tool_bindings,
    list_application_tool_reference_map,
    replace_application_tool_bindings,
    save_application_tool_binding,
    sync_application_tool_bindings,
)
from app.infra.db.repositories.tools.catalog import (
    get_tool,
    get_tool_by_function_name,
    get_tool_by_source_key,
    get_tool_catalog_detail_row,
    get_tool_policy,
    get_tool_source,
    get_tool_version,
    get_tool_version_by_hash,
    list_application_tool_snapshot_rows,
    list_mcp_catalog_rows,
    list_mcp_tool_sources,
    list_tool_catalog_rows,
    list_tool_policies,
    list_tool_sources,
    list_tool_versions,
    list_tools,
    list_tools_by_source,
    lock_tool,
    lock_tool_source,
    save_tool,
    save_tool_policy,
    save_tool_source,
    save_tool_version,
    update_tool_policy_if_revision,
)
from app.infra.db.repositories.tools.drafts import (
    get_tool_draft,
    list_tool_drafts,
    save_tool_draft,
)
from app.infra.db.repositories.tools.invocations import (
    _tool_invocation_effect,
    claim_tool_invocation,
    create_or_get_tool_invocation,
    fail_pending_tool_invocation,
    finalize_tool_invocation,
    get_tool_invocation,
    get_tool_invocation_by_id,
    get_tool_invocation_by_idempotency_key,
    has_unsettled_agent_tool_invocations,
    list_recoverable_tool_test_invocation_ids,
    list_tool_invocations,
    refresh_tool_invocation_deadline,
    requeue_tool_invocation,
    resolve_tool_invocation_approval,
    save_tool_invocation,
    settle_cancelled_agent_tool_invocations,
    settle_exhausted_agent_tool_invocations,
)
