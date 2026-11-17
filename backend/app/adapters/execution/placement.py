"""Placement selects one adapter; lifecycle and unknown-outcome rules stay there."""

from contextlib import asynccontextmanager

from app.adapters.execution.capacity import CapacityScope
from app.adapters.execution.opensandbox import OpenSandboxExecution
from app.infra.config.execution_hosts import host_settings
from app.infra.db.repositories.execution.placements import capacity_record
from app.infra.execution.placement import PlacementStore
from app.ports.execution import ExecutionBusy, ExecutionNotStarted, execution_scope


class PlacedExecution:
    def __init__(self, settings):
        self.settings = settings
        self.store = PlacementStore()

    async def _reserve(self, settings, placement, records):
        capacity = OpenSandboxExecution(settings).capacity
        await capacity.restore(records)
        await capacity.acquire(
            max(1, (placement.expires_at - placement.created_at).total_seconds()),
            CapacityScope(
                workspace_key=placement.workspace_id,
                consumer_key=placement.consumer_key,
                reservation=capacity_record(placement).capacity_reservation,
            ),
        )

    async def _adapter(self):
        scope = execution_scope.get()
        if scope is None or not scope.run_id:
            raise ExecutionNotStarted(
                "A Run scope is required for persistent host placement."
            )
        selected = await self.store.select(self.settings, scope, self._reserve)
        # Remove obsolete waiting entries on other hosts after a grant, so an
        # already placed Run cannot hold another host's fair queue head.
        from app.infra.execution.placement import placement_id

        for host in host_settings(self.settings):
            capacity = OpenSandboxExecution(host).capacity
            async with capacity._redis() as redis:
                await redis.hdel(
                    f"{capacity.key}:waiting",
                    placement_id(scope.workspace_id, scope.run_id),
                )
        return OpenSandboxExecution(selected)

    async def execute(self, request, *, timeout_seconds, max_output_bytes):
        scope = execution_scope.get()
        if scope and scope.run_id:
            adapter = await self._adapter()
            request = {**request, "execution_session": "agent_run"}
            return await adapter.execute(
                request,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
        # Ephemeral jobs have no reusable guest. A confirmed pre-dispatch Busy
        # may try another host; any other failure retains its outcome semantics.
        busy = None
        for host in host_settings(self.settings):
            try:
                return await OpenSandboxExecution(host).execute(
                    request,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                )
            except ExecutionBusy as exc:
                busy = exc
        raise busy or ExecutionBusy(
            "No execution host has capacity.", reason="host_capacity"
        )

    @asynccontextmanager
    async def mcp_host(self, config, domains, owner_key):
        adapter = await self._adapter()
        async with adapter.mcp_host(config, domains, owner_key) as bridge:
            yield bridge

    async def read_session_file(self, workspace_id, run_id, path, max_bytes):
        selected = await self.store.existing(self.settings, workspace_id, run_id)
        if selected is None:
            raise ExecutionNotStarted("Run sandbox no longer exists.")
        return await OpenSandboxExecution(selected).read_session_file(
            workspace_id, run_id, path, max_bytes
        )

    async def _release_due(self):
        for placement in await self.store.release_due():
            selected = next(
                (
                    host
                    for host in host_settings(self.settings)
                    if host.opensandbox_host_id == placement.host_id
                ),
                None,
            )
            if selected is None:
                continue
            from app.infra.execution.placement import require_host

            require_host(selected, placement)
            capacity = OpenSandboxExecution(selected).capacity
            await capacity.release_reservation(
                placement.id,
                CapacityScope(
                    workspace_key=placement.workspace_id,
                    consumer_key=placement.consumer_key,
                ),
            )

    async def close_session(self, workspace_id, run_id):
        from app.infra.execution.placement import placement_id

        for host in host_settings(self.settings):
            await OpenSandboxExecution(host).capacity.discard_waiter(
                placement_id(workspace_id, run_id)
            )
        selected = await self.store.existing(self.settings, workspace_id, run_id)
        if selected is not None:
            await OpenSandboxExecution(selected).close_session(workspace_id, run_id)
        await self._release_due()

    async def reclaim_sessions(self):
        import logging

        for host in host_settings(self.settings):
            try:
                await OpenSandboxExecution(host).reclaim_sessions()
            except Exception:
                logging.getLogger(__name__).warning(
                    "Execution host cleanup deferred; placement is retained."
                )
        await self._release_due()
