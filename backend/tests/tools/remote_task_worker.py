"""Disposable process for the explicit isolated-PostgreSQL recovery check."""

import asyncio
import os
import sys
from dataclasses import replace

from tests.support import settings

from app.application.tools.runtime.service import execute_tool_invocation
from app.infra.db.session import configure_database
from app.infra.security.keyring import initialize_secret_keys


async def main():
    runtime = replace(
        settings(),
        database_url=os.environ["NEXAFLOW_TEST_DATABASE_URL"],
        mcp_allow_private_networks=True,
        mcp_request_timeout_seconds=3,
    )
    assert runtime.database_url.startswith("postgresql+psycopg://")
    configure_database(runtime, worker_process=True)
    await initialize_secret_keys(runtime)
    result = await execute_tool_invocation(sys.argv[1], runtime, "killed-worker")
    print("WORKER_FINISHED", result.ok, result.error_code)


if __name__ == "__main__":
    asyncio.run(main())
