import asyncio
import sys


def configure_windows_event_loop_policy() -> None:
    """Use a selector-based asyncio loop on Windows.

    Python 3.8+ defaults Windows to the ProactorEventLoop, which psycopg
    (async) refuses: SQLAlchemy async connections fail with an
    InterfaceError. Celery tasks run ``asyncio.run`` per task and the ASGI
    server creates its own loop, so the policy must be installed before
    either process starts. No-op on other platforms.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
