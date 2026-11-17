"""Public contract compatibility and dependency direction."""

import ast
import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import nexaflow_extension_api as public

from app.domain.agents.runtime import tools
from app.domain.agents.runtime.extensions import AgentExtension, ExtensionRuntime


async def check():
    assert AgentExtension is public.AgentExtension
    for name in (
        "AgentToolResult",
        "AgentExecutionPaused",
        "AgentToolBusy",
        "AgentToolUncertain",
    ):
        assert getattr(tools, name) is getattr(public, name)
    source = Path(public.__file__).resolve()
    for file in source.parent.rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert name.split(".")[0] in sys.stdlib_module_names, name

    async def after(name, arguments, result):
        return replace(result, summary=f"{name}: trusted")

    extension = public.AgentExtension("test", "1.0.0", after_tool=after)
    runtime = ExtensionRuntime([extension])
    result = public.AgentToolResult("value", "initial", outcome_uncertain=True)
    decorated = await runtime.after_tool("echo", {}, result)
    assert decorated.content == "value" and decorated.summary == "echo: trusted"
    assert decorated.outcome_uncertain
    for version in (0, 2, True, "1"):
        try:
            ExtensionRuntime([replace(extension, api_version=version)])
        except ValueError as exc:
            assert "Unsupported extension API" in str(exc)
        else:
            raise AssertionError("An incompatible contract was accepted.")
    busy = public.AgentToolBusy("call", "capacity", {"reason": "host_capacity"})
    assert isinstance(busy, tools.AgentExecutionPaused)
    assert busy.call_id == "call" and busy.resource_wait["reason"] == "host_capacity"
    print("EXTENSION_API_OK")


if __name__ == "__main__":
    asyncio.run(check())
