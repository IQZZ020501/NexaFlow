"""Deterministic harness integration: lifecycle, loadout, context and durable input."""

import asyncio
import base64
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.agents.agents import (
    AgentModelHandler,
    agent_model_server,
    agents_url,
    model_payload,
)
from tests.agents.evaluation import ScriptedModel, answer_message
from tests.support import activate_admin, auth_headers, create_active_user, test_client
from tests.support import settings as test_settings

from app.application.agents.runs.executor import run_durable_agent_run
from app.application.agents.runs.memory import _run_messages
from app.application.agents.runs.service import skill_execution_context
from app.domain.agents.models import AgentRunState
from app.domain.agents.runtime import AgentToolResult, create_agent_tool, run_agent
from app.domain.agents.runtime.capabilities import CapabilityRegistry
from app.domain.agents.runtime.context import AgentContextManager
from app.domain.agents.runtime.extensions import AgentExtension, ExtensionRuntime
from app.domain.agents.runtime.session import AgentSession
from app.entities.agent_skills import AgentSkillSnapshot
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.repositories.runs.runs import finalize_agent_run
from app.infra.db.repositories.runs.session_inputs import (
    enqueue_session_input,
    pending_session_inputs,
)
from app.infra.db.session import get_session_factory


def call(name, args, call_id):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
        response_metadata={"finish_reason": "tool_calls"},
    )


def skill():
    return AgentSkillSnapshot(
        schema_version=2,
        skill_id="s1",
        version_id="v1",
        version_number=1,
        name="Research",
        description="Research a topic",
        definition={
            "instructions": "PRIVATE_FULL_SKILL_INSTRUCTIONS",
            "intents": ["research"],
        },
        definition_hash="hash",
        bound_by_user_id="owner",
    )


async def assert_capabilities_and_lazy_skills():
    calls = []

    empty_registry = CapabilityRegistry(ExtensionRuntime([]), [])
    assert [tool.name for tool in empty_registry.management_tools] == [
        "search_tools",
        "activate_tools",
    ]

    async def echo(raw):
        calls.append(raw)
        return AgentToolResult(content=raw, summary="Echo done.")

    tool = create_agent_tool(
        name="echo",
        description="Echo a value",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        execute=echo,
        kind="builtin",
    )
    extensions = ExtensionRuntime([AgentExtension("echo_plugin", "1", (tool,))])
    registry = CapabilityRegistry(extensions, [skill()])
    load_skill = next(
        tool for tool in registry.management_tools if tool.name == "load_skill"
    )
    assert load_skill.args_schema["properties"]["version_id"]["enum"] == ["v1"]
    catalog = skill_execution_context([skill()])
    assert "PRIVATE_FULL_SKILL_INSTRUCTIONS" not in catalog
    assert "v1" in catalog
    model = ScriptedModel(
        [
            call("load_skill", {"version_id": "v1"}, "load"),
            call("activate_tools", {"names": []}, "disable"),
            call("activate_tools", {"names": ["echo"]}, "enable"),
            call("echo", {"value": "ready"}, "echo"),
            answer_message("Done"),
        ]
    )
    checkpoints = []

    async def save(state, phase):
        checkpoints.append((state, phase))

    result = await run_agent(
        model,
        [
            {"role": "system", "content": catalog},
            {"role": "user", "content": "Research"},
        ],
        registry.tools,
        session=AgentSession(registry),
        on_checkpoint=save,
    )
    assert result.content == "Done" and len(calls) == 1
    assert result.harness["loaded_skills"] == ["v1"]
    assert "PRIVATE_FULL_SKILL_INSTRUCTIONS" not in str(model.requests[0])
    assert "PRIVATE_FULL_SKILL_INSTRUCTIONS" in str(model.requests[1])
    assert "echo" not in model.bindings[2] and "echo" in model.bindings[3]
    inactive = next(
        state
        for state, phase in checkpoints
        if phase == "agent" and state["harness"].get("active_tools") == []
    )
    restored = CapabilityRegistry(extensions, [skill()])
    restored.restore(inactive["harness"])
    assert "echo" not in [item.name for item in restored.tools]
    rejected = await restored.management_tools[1].ainvoke({"names": ["unauthorized"]})
    assert rejected.is_error and restored.active_names == []
    rejected = await restored.management_tools[2].ainvoke({"version_id": "unbound"})
    assert rejected.is_error
    try:
        CapabilityRegistry(
            ExtensionRuntime(
                [AgentExtension("bad", "1", (replace_tool_name(tool, "load_skill"),))]
            ),
            [],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Reserved tool name was accepted")


def replace_tool_name(tool, name):
    return tool.model_copy(update={"name": name})


async def assert_skill_file_reads_and_revocation():
    snapshot = replace(
        skill(),
        definition={
            "instructions": "Read references/guide.md when needed.",
            "files": {
                "references/guide.md": base64.b64encode(
                    ("x" * 12000 + "next-page").encode()
                ).decode(),
                "assets/data.bin": base64.b64encode(b"\x00\xff").decode(),
            },
        },
    )
    authorize = AsyncMock()
    registry = CapabilityRegistry(ExtensionRuntime([]), [snapshot], authorize)
    read = registry.management_tools[3]
    arguments = {"version_id": "v1", "path": "references/guide.md"}
    assert (await read.ainvoke(arguments)).is_error
    authorize.assert_not_awaited()
    await registry.management_tools[2].ainvoke({"version_id": "v1"})
    result = await read.ainvoke(arguments)
    assert result.content == "x" * 12000
    result = await read.ainvoke({**arguments, "offset": 12000})
    assert result.content == "next-page"
    assert (await read.ainvoke({**arguments, "path": "assets/data.bin"})).is_error
    assert (await read.ainvoke({**arguments, "path": "../escape"})).is_error
    authorize.side_effect = ValueError("revoked")
    for tool, args in (
        (registry.management_tools[2], {"version_id": "v1"}),
        (read, arguments),
    ):
        try:
            await tool.ainvoke(args)
        except ValueError as exc:
            assert str(exc) == "revoked"
        else:
            raise AssertionError("Lazy Skill access bypassed live revocation")
    for state in ({"active_tools": [{}]}, {"loaded_skills": [{}]}):
        try:
            registry.restore(state)
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed checkpoint capability accepted")

    tools = [
        create_agent_tool(
            name=f"tool_{number}",
            description="optional capability",
            parameters={"type": "object"},
            execute=AsyncMock(),
            kind="builtin",
        )
        for number in range(9)
    ]
    large = CapabilityRegistry(
        ExtensionRuntime([AgentExtension("large", "1", tuple(tools))]), []
    )
    assert large.active_names == []
    result = await large.management_tools[0].ainvoke({"query": "capability"})
    assert len(result.output) == 9
    huge = tools[0].model_copy(update={"description": "x" * 17000})
    assert (
        CapabilityRegistry(
            ExtensionRuntime([AgentExtension("huge", "1", (huge,))]), []
        ).active_names
        == []
    )


async def assert_steering_and_followup():
    inputs = [
        {
            "id": 1,
            "input_id": "follow",
            "mode": "follow_up",
            "content": "Then summarize",
        },
        {"id": 2, "input_id": "steer", "mode": "steer", "content": "Use Chinese"},
    ]

    async def source(consumed, settled):
        return [
            item
            for item in inputs
            if item["id"] not in consumed and (settled or item["mode"] == "steer")
        ]

    registry = CapabilityRegistry(ExtensionRuntime([]), [])
    model = ScriptedModel(
        [answer_message("First answer"), answer_message("Final summary")]
    )
    checkpoints = []

    async def save(state, phase):
        checkpoints.append((state, phase))

    result = await run_agent(
        model,
        [{"role": "user", "content": "Start"}],
        registry.tools,
        session=AgentSession(registry, input_source=source),
        on_checkpoint=save,
    )
    assert result.content == "Final summary"
    assert result.harness["input_ids"] == [2, 1]
    assert result.harness["inputs"][1]["previous_answer"] == "First answer"
    history = _run_messages(
        AgentRun(
            status="succeeded",
            goal="Start",
            result=result.content,
            checkpoint={"harness": result.harness},
        )
    )
    assert [item["content"] for item in history] == [
        "Start",
        "Use Chinese",
        "First answer",
        "Then summarize",
        "Final summary",
    ]
    assert "Use Chinese" in str(model.requests[0]) and "Then summarize" not in str(
        model.requests[0]
    )
    assert "Then summarize" in str(model.requests[1])
    restored = ScriptedModel([])
    await run_agent(
        restored,
        [{"role": "user", "content": "Start"}],
        registry.tools,
        checkpoint=checkpoints[-1][0],
        session=AgentSession(
            CapabilityRegistry(ExtensionRuntime([]), []), input_source=source
        ),
    )
    assert restored.requests == []
    # A late accepted input blocks finalization and resumes the completed
    # checkpoint without resetting turns or replaying prior actions.
    inputs.append(
        {"id": 3, "input_id": "late", "mode": "follow_up", "content": "One more task"}
    )
    resumed_model = ScriptedModel([answer_message("Late task completed")])
    resumed = await run_agent(
        resumed_model,
        [{"role": "user", "content": "Start"}],
        registry.tools,
        checkpoint=checkpoints[-1][0],
        session=AgentSession(
            CapabilityRegistry(ExtensionRuntime([]), []), input_source=source
        ),
    )
    assert resumed.content == "Late task completed"
    assert resumed.harness["input_ids"] == [2, 1, 3]
    assert len(resumed_model.requests) == 1


async def assert_context_compaction_and_hooks():
    model = ScriptedModel(
        [answer_message("Goal: complete the task. Retain constraints.")]
    )
    messages = [
        SystemMessage(content="Trusted system rules"),
        HumanMessage(content="Original goal " + "x" * 1100),
        AIMessage(content="Older work " + "y" * 1100),
        HumanMessage(content="Continue " + "z" * 1100),
        AIMessage(content="Older step"),
        HumanMessage(content="Latest goal"),
        call("echo", {"value": "ok"}, "c1"),
        ToolMessage(content="Result", tool_call_id="c1"),
        AIMessage(content="Next step"),
        HumanMessage(content="Continue now"),
    ]
    manager = AgentContextManager(model, 4096)
    compacted, usage = await manager.prepare(messages, [])
    assert compacted[0] == messages[0]
    assert usage["compaction"]["model_calls"] == 1
    assert messages[1].content.startswith("Original goal")
    assert manager.tokens(compacted, []) < manager.tokens(messages, [])
    assert any(
        isinstance(item, ToolMessage) and item.tool_call_id == "c1"
        for item in compacted
    )
    seen = []

    async def context(items):
        seen.append("context")
        return items

    async def before(name, args):
        seen.append("before")
        return AgentToolResult(
            content="Blocked by extension", summary="Blocked", is_error=True
        )

    runtime = ExtensionRuntime(
        [AgentExtension("policy", "1", context=context, before_tool=before)]
    )
    assert await runtime.prepare_context(messages) == messages
    assert (await runtime.before_tool("echo", {})).is_error
    assert seen == ["context", "before"]

    async def after(name, args, result):
        seen.append("after")
        return AgentToolResult(content=f"Wrapped: {result.content}", summary="Wrapped")

    decorated = ExtensionRuntime([AgentExtension("decorate", "1", after_tool=after)])
    wrapped = await decorated.after_tool(
        "echo", {}, AgentToolResult(content="Original", summary="Original")
    )
    assert wrapped.content == "Wrapped: Original" and seen[-1] == "after"
    oversized = [SystemMessage(content="Rules"), HumanMessage(content="x" * 8000)]
    try:
        await manager.prepare(oversized, [])
    except ValueError:
        pass
    else:
        raise AssertionError("Oversized current interaction was silently discarded")
    assert oversized[1].content == "x" * 8000
    try:
        ExtensionRuntime([AgentExtension("same", "1"), AgentExtension("same", "2")])
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate extension registration was accepted")


async def assert_durable_input_finalization():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            db.add(
                AgentRunState(
                    run_id="run1",
                    workspace_id="ws1",
                    agent_id="agent1",
                    access_source="console",
                    consumer_id="owner",
                    conversation_id="conversation1",
                    worker_generation="legacy",
                    status="running",
                    worker_task_id="worker",
                )
            )
            await db.commit()
            first = await enqueue_session_input(
                db, "ws1", "run1", "input1", "follow_up", "Summarize"
            )
            await db.commit()
            duplicate = await enqueue_session_input(
                db, "ws1", "run1", "input1", "follow_up", "Summarize"
            )
            assert duplicate.id == first.id
            try:
                await enqueue_session_input(
                    db, "ws1", "run1", "input1", "steer", "Different"
                )
            except ValueError:
                pass
            else:
                raise AssertionError("Idempotency conflict was accepted")
            assert await pending_session_inputs(db, "run1", [], False) == []
            assert len(await pending_session_inputs(db, "run1", [], True)) == 1
            finalized = await finalize_agent_run(
                db,
                "run1",
                "worker",
                status="succeeded",
                result="Done",
                events=[],
                last_error=None,
                finished_at=utc_now(),
                session_input_ids=[],
            )
            assert not finalized
            finalized = await finalize_agent_run(
                db,
                "run1",
                "worker",
                status="succeeded",
                result="Done",
                events=[],
                last_error=None,
                finished_at=utc_now(),
                session_input_ids=[first.id],
            )
            assert finalized
            await db.commit()
            try:
                await enqueue_session_input(db, "ws1", "run1", "late", "steer", "Late")
            except ValueError:
                pass
            else:
                raise AssertionError("Input accepted after finalization")
            assert (
                await enqueue_session_input(
                    db, "ws1", "run1", "input1", "follow_up", "Summarize"
                )
            ).id == first.id
    finally:
        await engine.dispose()


async def assert_durable_session_memory(run_id):
    async with get_session_factory()() as db:
        current = await agent_repository.get_agent_run_by_id(db, run_id)
        _, history = await agent_repository.list_conversation_memory_runs(
            db,
            AgentRun(
                id="future",
                workspace_id=current.workspace_id,
                agent_id=current.agent_id,
                access_source=current.access_source,
                consumer_id=current.consumer_id,
                conversation_id=current.conversation_id,
                created_at=utc_now(),
            ),
            limit=7,
        )
        assert history and [item["content"] for item in _run_messages(history[-1])] == [
            "Start",
            "Use Chinese",
            "Completed.",
            "Then summarize",
            "Completed.",
        ]


def assert_session_input_api_isolation():
    with (
        test_client() as client,
        agent_model_server() as model_base_url,
        patch(
            "app.application.agents.runs.service.enqueue_prepared_agent_run",
            new=AsyncMock(),
        ),
        patch(
            "app.application.agents.access.service.enqueue_prepared_agent_run",
            new=AsyncMock(),
        ),
        patch(
            "app.application.agents.access.service.enforce_external_agent_rate_limit",
            new=AsyncMock(),
        ),
    ):
        token, workspace_id = activate_admin(client)
        owner = auth_headers(token)
        other_id, other_token = create_active_user(client, token, "harness-other")
        other = auth_headers(other_token)
        membership = client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            headers=owner,
            json={"user_id": other_id, "role": "admin"},
        )
        assert membership.status_code == 201, membership.text
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=owner,
            json=model_payload(model_base_url),
        )
        assert model.status_code == 201, model.text
        agent = client.post(
            agents_url(workspace_id),
            headers=owner,
            json={
                "name": "Harness",
                "instructions": "Answer directly.",
                "model_id": model.json()["id"],
            },
        )
        assert agent.status_code == 201, agent.text
        agent_id = agent.json()["id"]
        management = agents_url(workspace_id, f"/{agent_id}")
        granted = client.put(
            f"{management}/permissions/{other_id}",
            headers=owner,
            json={"permission": "view"},
        )
        assert granted.status_code == 200, granted.text
        published = client.patch(management, headers=owner, json={"published": True})
        assert published.status_code == 200, published.text
        keys = [
            client.post(
                f"{management}/api-credentials", headers=owner, json={"name": name}
            )
            for name in ("A", "B")
        ]
        assert all(key.status_code == 201 for key in keys)
        api_owner, api_other = [auth_headers(key.json()["token"]) for key in keys]
        origins = [
            (management, owner, other),
            (f"/api/v1/public/agents/{agent_id}", owner, other),
            (f"/api/v1/agent-api/{agent_id}", api_owner, api_other),
        ]
        for base, headers, stranger in origins:
            created = client.post(
                f"{base}/runs", headers=headers, json={"goal": "Start"}
            )
            assert created.status_code == 201, created.text
            run_id = created.json()["id"]
            url = f"{base}/runs/{run_id}/inputs"
            payload = {"input_id": "input1", "mode": "steer", "content": "Use Chinese"}
            denied = client.post(url, headers=stranger, json=payload)
            assert denied.status_code == 404, denied.text
            assert client.post(url, json=payload).status_code == 401
            accepted = client.post(url, headers=headers, json=payload)
            assert accepted.status_code == 202, accepted.text
            repeated = client.post(url, headers=headers, json=payload)
            assert repeated.status_code == 202 and repeated.json() == accepted.json()
            conflict = client.post(
                url, headers=headers, json={**payload, "content": "Different"}
            )
            assert conflict.status_code == 409, conflict.text
            blank = client.post(
                url,
                headers=headers,
                json={**payload, "input_id": "blank", "content": " "},
            )
            assert blank.status_code == 422, blank.text
            current = client.get(f"{base}/runs/{run_id}", headers=headers)
            assert current.status_code == 200, current.text
            assert current.json()["session_inputs"] == [accepted.json()]
            # A public/API principal cannot inject input through the console route.
            if base != management:
                denied_console = client.post(
                    f"{management}/runs/{run_id}/inputs", headers=owner, json=payload
                )
                assert denied_console.status_code == 404, denied_console.text
            follow_up = client.post(
                url,
                headers=headers,
                json={
                    "input_id": "follow",
                    "mode": "follow_up",
                    "content": "Then summarize",
                },
            )
            assert follow_up.status_code == 202, follow_up.text
            AgentModelHandler.calls = []
            outcome = asyncio.run(
                run_durable_agent_run(
                    run_id, test_settings(), worker_task_id=f"harness-{run_id}"
                )
            )
            assert outcome == "finished"
            finished = client.get(f"{base}/runs/{run_id}", headers=headers)
            assert finished.status_code == 200, finished.text
            assert finished.json()["status"] == "succeeded", finished.text
            assert all(
                item["status"] == "applied"
                for item in finished.json()["session_inputs"]
            )
            assert (
                finished.json()["session_inputs"][1]["previous_answer"] == "Completed."
            )
            assert len(AgentModelHandler.calls) == 2
            assert "Use Chinese" in str(AgentModelHandler.calls[0])
            assert "Then summarize" not in str(AgentModelHandler.calls[0])
            assert "Then summarize" in str(AgentModelHandler.calls[1])
            asyncio.run(assert_durable_session_memory(run_id))
            late = client.post(
                url, headers=headers, json={**payload, "input_id": "late"}
            )
            assert late.status_code == 409, late.text
            # An idempotent retry remains safe after the Run becomes terminal.
            applied_retry = client.post(url, headers=headers, json=payload)
            assert (
                applied_retry.status_code == 202
                and applied_retry.json()["status"] == "applied"
            )


def main():
    asyncio.run(assert_capabilities_and_lazy_skills())
    asyncio.run(assert_skill_file_reads_and_revocation())
    asyncio.run(assert_steering_and_followup())
    asyncio.run(assert_context_compaction_and_hooks())
    asyncio.run(assert_durable_input_finalization())
    assert_session_input_api_isolation()
    print("AGENT_HARNESS_OK")


if __name__ == "__main__":
    main()
