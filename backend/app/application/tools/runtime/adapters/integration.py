import asyncio

from app.domain.tools.integrations.feishu_catalog import FEISHU_CATALOG_REVISION
from app.domain.tools.integrations.service import credentials, require_reauthorization
from app.domain.tools.results import prepare_mcp_result
from app.entities.defaults import utc_now
from app.infra.db.session import get_session_factory
from app.ports.integrations import IntegrationProviderError, call_integration
from app.ports.tools import ToolRuntimeResult


class IntegrationToolAdapter:
    kind = "integration"

    def __init__(self, settings):
        self.settings = settings

    async def invoke(self, snapshot, arguments, context):
        spec = snapshot.execution_spec
        dispatched = False
        try:
            if (
                spec["provider"] == "feishu"
                and spec.get("catalog_revision") != FEISHU_CATALOG_REVISION
            ):
                raise IntegrationProviderError(
                    "Integration tool definition changed. Update tools and select this integration again."
                )
            async with get_session_factory()() as db:
                grant = await credentials(
                    db,
                    spec["connection_id"],
                    context.workspace_id,
                    context.execution_user_id,
                    spec["generation"],
                    self.settings,
                )
            if context.ownership_lost and context.ownership_lost.is_set():
                raise IntegrationProviderError("Tool execution ownership was lost.")
            remaining = (context.deadline_at - utc_now()).total_seconds()
            if remaining <= 0:
                raise IntegrationProviderError("Integration operation timed out.")
            async with asyncio.timeout(remaining):
                dispatched = True
                payload = await call_integration(
                    spec["provider"],
                    spec["operation"],
                    arguments,
                    grant,
                    context.idempotency_key,
                )
            data, full_result = prepare_mcp_result(
                {"structuredContent": payload}, context.idempotency_key
            )
            return ToolRuntimeResult(
                ok=True,
                data=data,
                summary="Integration operation completed.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
                full_result=full_result,
            )
        except (IntegrationProviderError, TimeoutError) as exc:
            if isinstance(exc, IntegrationProviderError) and exc.unauthorized:
                async with get_session_factory()() as db:
                    await require_reauthorization(
                        db, spec["connection_id"], spec["generation"]
                    )
            message = (
                str(exc)
                if isinstance(exc, IntegrationProviderError)
                else "Integration operation timed out."
            )
            uncertain = dispatched and (
                exc.uncertain
                if isinstance(exc, IntegrationProviderError)
                else snapshot.effect == "external_write"
            )
            return ToolRuntimeResult(
                ok=False,
                data=None,
                summary=message,
                error_code="integration_failed",
                error_message=message,
                outcome="uncertain" if uncertain else "confirmed",
                usage={},
            )
