"""Short transactions for Run and sandbox fencing; never hold a DB lock during I/O."""

import hashlib
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.entities.defaults import utc_now
from app.entities.execution import ExecutionSession
from app.infra.db.repositories.execution import placements
from app.infra.db.repositories.execution import sessions as repository
from app.infra.db.session import get_session_factory
from app.infra.execution.placement import host_fingerprint, require_host
from app.infra.execution.profile import execution_profile, require_execution_profile
from app.ports.execution import ExecutionBusy, ExecutionNotStarted


class SessionStore:
    async def admit(self, settings, session, scope, reserve, *, intent=None):
        """Serialize admission and persist intent before any external creation."""
        async with get_session_factory()() as db:
            await repository.lock_capacity(
                db,
                "nexaflow:execution-placement"
                if settings.opensandbox_hosts
                else settings.opensandbox_url,
            )
            if session is not None:
                info = await repository.run_for_execution(
                    db, scope.workspace_id, scope.run_id
                )
                if (
                    not info
                    or info[0].deadline_at <= utc_now()
                    or (
                        scope.worker_task_id is not None
                        and info[0].worker_task_id != scope.worker_task_id
                    )
                ):
                    raise ExecutionBusy("Run execution lease was lost.")
            token, reservation = await reserve(
                await repository.capacity_records(db, utc_now())
            )
            if session is not None:
                saved = await repository.update_owned(
                    db,
                    session,
                    session.holder,
                    capacity_token=token,
                    capacity_reservation=reservation,
                    creation_pending=True,
                )
                if not saved:
                    raise ExecutionBusy("Run sandbox lease was lost.")
            elif intent is not None:
                await placements.create(db, intent)
            await db.commit()
        if session is not None:
            session.capacity_token = token
            session.capacity_reservation = reservation
            session.creation_pending = True
        return token

    async def acquire(self, settings, scope, timeout, *, purpose="run", owner_key=""):
        now = utc_now()
        holder = uuid4().hex
        async with get_session_factory()() as db:
            info = await repository.run_for_execution(
                db, scope.workspace_id, scope.run_id
            )
            if info is None or info[0].deadline_at <= now:
                raise ExecutionNotStarted("Run execution has ended or expired.")
            run, profile = info
            if (
                scope.worker_task_id is not None
                and run.worker_task_id != scope.worker_task_id
            ):
                raise ExecutionBusy("Run execution lease was lost.")
            require_execution_profile(settings, profile)
            session = await repository.live_session(
                db, scope.workspace_id, scope.run_id, purpose, owner_key
            )
            stale = bool(
                session
                and session.holder
                and session.holder_expires_at
                and repository.aware(session.holder_expires_at) <= now
            )
            if session and session.state == "closing":
                if session.creation_pending and not session.sandbox_id:
                    raise ExecutionNotStarted(
                        "Previous sandbox creation could not be confirmed. "
                        "Execution is unavailable for this Run; continue with other tools."
                    )
                raise ExecutionBusy(
                    "Previous Run sandbox cleanup is pending.",
                    reason="environment_cleanup",
                )
            reset = bool(
                session is None
                and await repository.previous_session(
                    db, scope.workspace_id, scope.run_id, purpose, owner_key
                )
            )
            if session and (
                session.expires_at is not None
                and repository.aware(session.expires_at) <= now
                or session.profile_fingerprint
                != execution_profile(settings)["fingerprint"]
            ):
                await repository.mark_closing(db, session.id)
                await db.commit()
                raise ExecutionBusy(
                    "Expired Run sandbox cleanup is pending.",
                    reason="environment_cleanup",
                )
            # Covers startup; the command watchdog keeps a much shorter lease.
            until = now + timedelta(seconds=60)
            expires = run.deadline_at + timedelta(seconds=60)
            if session is None:
                session = ExecutionSession(
                    workspace_id=scope.workspace_id,
                    run_id=scope.run_id,
                    host_id=settings.opensandbox_host_id,
                    host_fingerprint=host_fingerprint(settings),
                    purpose=purpose,
                    owner_key=owner_key,
                    image=settings.opensandbox_image,
                    profile_fingerprint=execution_profile(settings)["fingerprint"],
                    holder=holder,
                    holder_expires_at=until,
                    expires_at=expires,
                    consumer_key=hashlib.sha256(
                        f"{scope.workspace_id}:{run.access_source}:{run.consumer_id}".encode()
                    ).hexdigest()
                    if run.access_source in {"public", "api", "automation"}
                    else None,
                )
                if run.reservation_profiles:
                    session.capacity_reservation = {
                        "id": hashlib.sha256(
                            f"{scope.workspace_id}:{scope.run_id}".encode()
                        ).hexdigest()[:32],
                        "profiles": list(run.reservation_profiles),
                        "member": "run" if purpose == "run" else "mcp",
                        "owner": session.id,
                    }
                try:
                    await repository.create(db, session)
                except IntegrityError as exc:
                    await db.rollback()
                    raise ExecutionBusy(
                        "Run sandbox creation is already in progress."
                    ) from exc
            else:
                require_host(settings, session)
                if not await repository.claim(db, session.id, holder, until, now):
                    raise ExecutionBusy("Run sandbox is owned by another command.")
                session.holder = holder
                session.holder_expires_at = until
                session.expires_at = expires
                await repository.update_owned(db, session, holder, expires_at=expires)
            await db.commit()
            return session, run, reset, stale

    async def acquire_existing(
        self, settings, scope, timeout, *, purpose="run", owner_key=""
    ):
        """Claim an existing live session without ever creating one.

        A read must not bring a guest into existence: a missing session means
        the workspace is gone, and creating a fresh guest would only produce
        an empty workspace to fail in.
        """
        now = utc_now()
        holder = uuid4().hex
        async with get_session_factory()() as db:
            info = await repository.run_for_execution(
                db, scope.workspace_id, scope.run_id
            )
            if info is None or info[0].deadline_at <= now:
                raise ExecutionNotStarted("Run execution has ended or expired.")
            run, profile = info
            if (
                scope.worker_task_id is not None
                and run.worker_task_id != scope.worker_task_id
            ):
                raise ExecutionBusy("Run execution lease was lost.")
            require_execution_profile(settings, profile)
            session = await repository.live_session(
                db, scope.workspace_id, scope.run_id, purpose, owner_key
            )
            if session is None:
                raise ExecutionNotStarted("Run sandbox no longer exists.")
            require_host(settings, session)
            if session.state == "closing":
                raise ExecutionBusy("Previous Run sandbox cleanup is pending.")
            if (
                session.expires_at is not None
                and repository.aware(session.expires_at) <= now
            ):
                raise ExecutionNotStarted("Run sandbox expired.")
            if (
                session.profile_fingerprint
                != execution_profile(settings)["fingerprint"]
            ):
                raise ExecutionNotStarted(
                    "Execution image or network profile changed after run creation."
                )
            stale = bool(
                session.holder
                and session.holder_expires_at
                and repository.aware(session.holder_expires_at) <= now
            )
            until = now + timedelta(seconds=60)
            if not await repository.claim(db, session.id, holder, until, now):
                raise ExecutionBusy("Run sandbox is owned by another command.")
            session.holder = holder
            session.holder_expires_at = until
            await repository.update_owned(db, session, holder)
            await db.commit()
            return session, run, False, stale

    async def publish(self, session, *, scope=None, **values):
        reset = values.pop("workspace_reset", False)
        async with get_session_factory()() as db:
            if scope is not None:
                info = await repository.run_for_execution(
                    db, scope.workspace_id, scope.run_id
                )
                if (
                    not info
                    or info[0].deadline_at <= utc_now()
                    or (
                        scope.worker_task_id is not None
                        and info[0].worker_task_id != scope.worker_task_id
                    )
                ):
                    raise ExecutionBusy("Run execution lease was lost.")
            saved = await repository.update_owned(db, session, session.holder, **values)
            if not saved:
                raise ExecutionBusy("Run sandbox lease was lost.")
            if reset:
                await repository.record_workspace_reset(db, session, values["sandbox_id"])
            await db.commit()
        for name, value in values.items():
            setattr(session, name, value)

    async def current(self, session, scope):
        async with get_session_factory()() as db:
            info = await repository.run_for_execution(
                db, scope.workspace_id, scope.run_id
            )
            row = await repository.get(db, session.id)
            valid = bool(
                info
                and row
                and row.state in {"creating", "ready"}
                and row.holder == session.holder
                and row.holder_expires_at
                and repository.aware(row.holder_expires_at) > utc_now()
                and info[0].deadline_at > utc_now()
                and (
                    scope.worker_task_id is None
                    or info[0].worker_task_id == scope.worker_task_id
                )
            )
            if valid:
                valid = await repository.update_owned(
                    db,
                    session,
                    session.holder,
                    holder_expires_at=utc_now() + timedelta(seconds=15),
                )
                await db.commit()
            return valid

    async def release(self, session):
        async with get_session_factory()() as db:
            await repository.update_owned(
                db, session, session.holder, holder=None, holder_expires_at=None
            )
            await db.commit()

    async def closing(self, session, *, owned=False):
        async with get_session_factory()() as db:
            if owned:
                changed = await repository.update_owned(
                    db, session, session.holder, state="closing"
                )
            else:
                await repository.mark_closing(db, session.id)
                changed = True
            await db.commit()
            return changed

    async def closed(self, session):
        async with get_session_factory()() as db:
            await repository.mark_closed(db, session.id)
            await db.commit()

    async def for_run(self, workspace_id, run_id, host_id=None):
        async with get_session_factory()() as db:
            records = await repository.for_run(db, workspace_id, run_id)
            return [
                record
                for record in records
                if host_id is None or record.host_id == host_id
            ]

    async def reclaimable(self, host_id=None):
        async with get_session_factory()() as db:
            records = await repository.reclaimable(db, utc_now())
            return [
                record
                for record in records
                if host_id is None or record.host_id == host_id
            ]

    async def tracked(self, host_id=None):
        async with get_session_factory()() as db:
            return await repository.tracked_sessions(db, host_id)

    async def release_admission(self, identity):
        async with get_session_factory()() as db:
            await placements.release(db, identity)
            await db.commit()

    async def due_admissions(self, host_id):
        from app.infra.execution.placement import PlacementStore

        return await PlacementStore().release_due(host_id)

    async def reservation_held(self, identity):
        async with get_session_factory()() as db:
            placement = await placements.get(db, identity)
            return bool(
                placement
                and not placement.released
                and repository.aware(placement.expires_at) > utc_now()
            )
