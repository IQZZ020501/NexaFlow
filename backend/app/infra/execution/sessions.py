"""Short transactions for Run and sandbox fencing; never hold a DB lock during I/O."""

import hashlib
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.entities.defaults import utc_now
from app.entities.execution import ExecutionSession
from app.infra.db.repositories.execution import sessions as repository
from app.infra.db.session import get_session_factory
from app.infra.execution.profile import execution_profile, require_execution_profile
from app.ports.execution import ExecutionBusy, ExecutionNotStarted


class SessionStore:
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
                raise ExecutionBusy("Previous Run sandbox cleanup is pending.")
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
                raise ExecutionBusy("Expired Run sandbox cleanup is pending.")
            # Covers startup; the command watchdog keeps a much shorter lease.
            until = now + timedelta(seconds=60)
            expires = run.deadline_at + timedelta(seconds=60)
            if session is None:
                session = ExecutionSession(
                    workspace_id=scope.workspace_id,
                    run_id=scope.run_id,
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
                    if run.access_source in {"public", "api"}
                    else None,
                )
                try:
                    await repository.create(db, session)
                except IntegrityError as exc:
                    await db.rollback()
                    raise ExecutionBusy(
                        "Run sandbox creation is already in progress."
                    ) from exc
            else:
                if not await repository.claim(db, session.id, holder, until, now):
                    raise ExecutionBusy("Run sandbox is owned by another command.")
                session.holder = holder
                session.holder_expires_at = until
                session.expires_at = expires
                await repository.update_owned(db, session, holder, expires_at=expires)
            await db.commit()
            return session, run, reset, stale

    async def acquire_existing(self, settings, scope, timeout, *, purpose="run", owner_key=""):
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
            if session.state == "closing":
                raise ExecutionBusy("Previous Run sandbox cleanup is pending.")
            if session.expires_at is not None and repository.aware(
                session.expires_at
            ) <= now:
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
            await db.commit()
        if not saved:
            raise ExecutionBusy("Run sandbox lease was lost.")
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

    async def for_run(self, workspace_id, run_id):
        async with get_session_factory()() as db:
            return await repository.for_run(db, workspace_id, run_id)

    async def reclaimable(self):
        async with get_session_factory()() as db:
            return await repository.reclaimable(db, utc_now())

    async def tracked(self):
        async with get_session_factory()() as db:
            return await repository.tracked_sessions(db)
