"""Run-scoped reuse of remote MCP sessions within one worker process.

The MCP SDK enters and exits a client session through anyio task groups, which
must close in the task that opened them. Each pooled session is therefore owned
by a dedicated task; callers borrow the open client and the owner closes it once
the session is retired or idle.
"""

import asyncio
import weakref
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, TypeVar

from app.ports.mcp import McpClientError

IDLE_SECONDS = 60.0
CLOSE_WAIT_SECONDS = 5.0
_T = TypeVar("_T")


@dataclass(frozen=True)
class SessionKey:
    run_id: str
    url: str
    credential: str
    network_policy: str
    workspace_id: str | None


class _Session:
    def __init__(
        self,
        opener: Callable[[], AbstractAsyncContextManager[Any]],
        on_closed: Callable[["_Session"], None],
    ) -> None:
        loop = asyncio.get_running_loop()
        self._opener = opener
        self._on_closed = on_closed
        self._ready: asyncio.Future[Any] = loop.create_future()
        self._wake = asyncio.Event()
        self.client: Any = None
        self.active = 0
        self.retired = False
        self.last_used = loop.time()
        self.task = asyncio.create_task(self._own())

    async def ready(self) -> Any:
        # A cancelled caller must not cancel the shared opening of the session.
        self.client = await asyncio.shield(self._ready)
        return self.client

    def touch(self) -> None:
        self.last_used = asyncio.get_running_loop().time()
        self._wake.set()

    def retire(self) -> None:
        self.retired = True
        self._wake.set()

    async def _own(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            async with self._opener() as client:
                self._ready.set_result(client)
                while not (self.retired and self.active == 0):
                    idle = loop.time() - self.last_used
                    if self.active == 0 and idle >= IDLE_SECONDS:
                        break
                    self._wake.clear()
                    try:
                        async with asyncio.timeout(
                            None if self.active else IDLE_SECONDS - idle
                        ):
                            await self._wake.wait()
                    except TimeoutError:
                        pass
        except asyncio.CancelledError:
            if not self._ready.done():
                self._ready.set_exception(
                    McpClientError("MCP session closed.", request_sent=False)
                )
            raise
        except Exception as exc:
            # After opening, a transport failure only ends this session; callers
            # observe their own request errors.
            if not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            self.retired = True
            self._on_closed(self)


class SessionPool:
    def __init__(self) -> None:
        self._sessions: dict[SessionKey, _Session] = {}
        self._locks: dict[SessionKey, asyncio.Lock] = {}

    async def call(
        self,
        key: SessionKey,
        opener: Callable[[], AbstractAsyncContextManager[Any]],
        operation: Callable[[Any], Awaitable[_T]],
    ) -> _T:
        session = await self._acquire(key, opener)
        session.active += 1
        try:
            return await operation(session.client)
        except BaseException:
            # A failed or cancelled request may leave the session inconsistent.
            self._retire(key, session)
            raise
        finally:
            session.active -= 1
            session.touch()

    async def close_run(self, run_id: str) -> None:
        closing = [
            (key, session)
            for key, session in list(self._sessions.items())
            if key.run_id == run_id
        ]
        for key, session in closing:
            self._retire(key, session)
        tasks = [session.task for _, session in closing]
        if tasks:
            await asyncio.wait(tasks, timeout=CLOSE_WAIT_SECONDS)

    async def _acquire(
        self,
        key: SessionKey,
        opener: Callable[[], AbstractAsyncContextManager[Any]],
    ) -> _Session:
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            session = self._sessions.get(key)
            if session is None or session.retired:
                session = _Session(opener, lambda closed: self._forget(key, closed))
                self._sessions[key] = session
        try:
            await session.ready()
        except BaseException:
            self._retire(key, session)
            raise
        return session

    def _retire(self, key: SessionKey, session: _Session) -> None:
        session.retire()
        self._forget(key, session)

    def _forget(self, key: SessionKey, session: _Session) -> None:
        if self._sessions.get(key) is session:
            del self._sessions[key]
            lock = self._locks.get(key)
            if lock is not None and not lock.locked():
                del self._locks[key]


_pools: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, SessionPool]" = (
    weakref.WeakKeyDictionary()
)


def session_pool() -> SessionPool:
    loop = asyncio.get_running_loop()
    pool = _pools.get(loop)
    if pool is None:
        pool = _pools[loop] = SessionPool()
    return pool


async def close_run_sessions(run_id: str) -> None:
    pool = _pools.get(asyncio.get_running_loop())
    if pool is not None:
        await pool.close_run(run_id)
