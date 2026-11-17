"""Freeze host choice before guest creation; do not migrate uncertain execution."""

import hashlib
from datetime import timedelta

from app.entities.defaults import utc_now
from app.entities.execution import ExecutionPlacement
from app.infra.config.execution_hosts import host_settings
from app.infra.db.repositories.execution import placements, sessions
from app.infra.db.session import get_session_factory
from app.infra.execution.profile import require_execution_profile
from app.ports.execution import ExecutionBusy, ExecutionNotStarted


def host_fingerprint(settings):
    return hashlib.sha256(settings.opensandbox_url.rstrip("/").encode()).hexdigest()


def placement_id(workspace_id, run_id):
    return hashlib.sha256(f"{workspace_id}:{run_id}".encode()).hexdigest()[:32]


def require_host(settings, record):
    if (
        record.host_id != settings.opensandbox_host_id
        or (
            record.host_fingerprint
            and record.host_fingerprint != host_fingerprint(settings)
        )
        or (not record.host_fingerprint and settings.opensandbox_hosts)
    ):
        raise ExecutionNotStarted(
            "The execution host binding changed; automatic migration is disabled."
        )


class PlacementStore:
    async def select(self, settings, scope, reserve):
        async with get_session_factory()() as db:
            await sessions.lock_capacity(db, "nexaflow:execution-placement")
            info = await sessions.run_for_execution(
                db, scope.workspace_id, scope.run_id
            )
            if not info or info[0].deadline_at <= utc_now():
                raise ExecutionNotStarted("Run execution has ended or expired.")
            run, profile = info
            if (
                scope.worker_task_id is not None
                and run.worker_task_id != scope.worker_task_id
            ):
                raise ExecutionBusy("Run execution lease was lost.")
            require_execution_profile(settings, profile)
            identity = placement_id(scope.workspace_id, scope.run_id)
            placement = await placements.get(db, identity)
            hosts = list(host_settings(settings))
            if placement:
                selected = next(
                    (
                        host
                        for host in hosts
                        if host.opensandbox_host_id == placement.host_id
                    ),
                    None,
                )
                if not selected or placement.released:
                    raise ExecutionNotStarted(
                        "The Run's execution host is unavailable."
                    )
                require_host(selected, placement)
                await db.commit()
                return selected
            profiles = list(run.reservation_profiles or (run.resource_profile,))
            records = await sessions.capacity_records(db, utc_now())
            # Prefer the least reserved host. Redis performs final atomic
            # resource and cross-host tenant admission, including fair queues.
            loads = {}
            for record in records:
                tokens = record.capacity_reservation.get("profiles", ["heavy"])
                loads.setdefault(record.host_id, set()).update(
                    f"{record.capacity_reservation.get('id', record.id)}:{i}"
                    for i in range(len(tokens))
                )
            hosts.sort(
                key=lambda host: (
                    len(loads.get(host.opensandbox_host_id, ()))
                    / host.opensandbox_max_sandboxes,
                    hashlib.sha256(
                        f"{identity}:{host.opensandbox_host_id}".encode()
                    ).hexdigest(),
                )
            )
            consumer = (
                hashlib.sha256(
                    f"{scope.workspace_id}:{run.access_source}:{run.consumer_id}".encode()
                ).hexdigest()
                if run.access_source in {"public", "api"}
                else None
            )
            expires = run.deadline_at + timedelta(seconds=60)
            busy = None
            for selected in hosts:
                placement = ExecutionPlacement(
                    id=identity,
                    workspace_id=scope.workspace_id,
                    run_id=scope.run_id,
                    host_id=selected.opensandbox_host_id,
                    host_fingerprint=host_fingerprint(selected),
                    profile_fingerprint=profile["fingerprint"],
                    profiles=profiles,
                    consumer_key=consumer,
                    expires_at=expires,
                )
                try:
                    await reserve(selected, placement, records)
                except ExecutionBusy as exc:
                    busy = exc
                    continue
                await placements.create(db, placement)
                await db.commit()
                return selected
            raise busy or ExecutionBusy(
                "No execution host has capacity.", reason="host_capacity"
            )

    async def existing(self, settings, workspace_id, run_id):
        async with get_session_factory()() as db:
            placement = await placements.get(db, placement_id(workspace_id, run_id))
        if placement is None:
            return None
        selected = next(
            (
                host
                for host in host_settings(settings)
                if host.opensandbox_host_id == placement.host_id
            ),
            None,
        )
        if selected is None:
            raise ExecutionNotStarted("The Run's execution host is unavailable.")
        require_host(selected, placement)
        return selected

    async def release_due(self, host_id=None):
        async with get_session_factory()() as db:
            due = await placements.releasable(db, utc_now(), host_id)
            for placement in due:
                await placements.release(db, placement.id)
            await placements.prune_ephemeral(db, utc_now() - timedelta(days=1))
            await db.commit()
            return due
