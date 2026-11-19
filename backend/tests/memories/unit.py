"""Pure memory rules and disposable runtime projections."""

import asyncio
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import HumanMessage, SystemMessage

from app.application.agents.runs.suggestions import generate_suggested_questions
from app.domain.agents.runtime.capabilities import CapabilityRegistry
from app.domain.agents.runtime.extensions import ExtensionRuntime
from app.domain.agents.runtime.session import PERSONAL_CONTEXT_MARKER, AgentSession
from app.domain.agents.runtime.usage import empty_usage
from app.domain.memories.services import parse_candidates, select_memories
from app.entities.defaults import utc_now
from app.entities.memories import UserMemory


class MemoryTests(unittest.TestCase):
    def test_scope_expiry_and_relevance(self):
        now = utc_now()
        items = [
            UserMemory(key="language", content="请使用中文"),
            UserMemory(category="goal", key="docker", content="学习 Docker"),
            UserMemory(category="background", key="gardening", content="园艺"),
            UserMemory(
                category="project",
                project_id="other",
                key="docker",
                content="Other secret",
            ),
            UserMemory(
                key="old", content="expired", expires_at=now - timedelta(days=1)
            ),
        ]
        selected = select_memories(items, "Docker 部署", "current", now)
        self.assertEqual([item["key"] for item in selected], ["language", "docker"])
        self.assertLessEqual(sum(len(item["content"]) for item in selected), 2400)

    def test_only_source_backed_eligible_statements(self):
        candidate = {
            "action": "upsert",
            "category": "preference",
            "scope": "user",
            "key": "style",
            "content": "回答简洁",
            "source_index": 0,
            "quote": "回答简洁",
        }
        source = ["我希望回答简洁"]
        self.assertEqual(
            parse_candidates(
                json.dumps([candidate]), source, automatic=False, project_id=""
            ),
            [],
        )
        accepted = parse_candidates(
            json.dumps([candidate]),
            ["请记住，回答简洁"],
            automatic=False,
            project_id="",
        )
        self.assertEqual(accepted[0]["origin"], "explicit")
        for patch in (
            {"quote": "assistant invented"},
            {"source_index": True},
            {"content": "password: secret"},
            {"scope": "other"},
            {"category": "project"},
            {"action": "delete"},
        ):
            self.assertEqual(
                parse_candidates(
                    json.dumps([{**candidate, **patch}]),
                    source,
                    automatic=True,
                    project_id="",
                ),
                [],
            )
        for invalid in ("not-json", "{}", "[null]", '["text"]'):
            self.assertEqual(
                parse_candidates(invalid, source, automatic=True, project_id=""), []
            )

    def test_personalization_is_refreshed_and_excluded_from_compaction(self):
        async def check():
            seen = []

            async def prepare(messages, _tools):
                seen.append(messages)
                return messages, empty_usage()

            context = SimpleNamespace(
                restore=lambda _: None,
                prepare=prepare,
                memory=None,
                context_window=32768,
                tokens=lambda *_: 1,
            )
            personal = AsyncMock(side_effect=["Private preference", ""])
            session = AgentSession(
                CapabilityRegistry(ExtensionRuntime([]), []),
                context,
                personal_context=personal,
            )
            state = {
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="Question"),
                ],
                "model_usage": empty_usage(),
                "harness": {},
                "events": [],
            }
            first = await session.prepare_turn(state)
            self.assertTrue(
                first["messages"][-1].additional_kwargs.get(PERSONAL_CONTEXT_MARKER)
            )
            second = await session.prepare_turn(first)
            self.assertFalse(
                any(
                    message.additional_kwargs.get(PERSONAL_CONTEXT_MARKER)
                    for message in second["messages"]
                )
            )
            self.assertFalse(
                any(
                    "Private preference" in str(message.content)
                    for messages in seen
                    for message in messages
                )
            )

        asyncio.run(check())

    def test_suggestions_can_be_empty_and_receive_bounded_context(self):
        async def check():
            model = SimpleNamespace(
                ainvoke=AsyncMock(
                    return_value=SimpleNamespace(
                        text="[]", usage_metadata={}, response_metadata={}
                    )
                )
            )
            questions, _ = await generate_suggested_questions(
                model,
                "Deploy?",
                "Done",
                provider_type="openai_compatible",
                request_params={},
                timeout_seconds=1,
                related_context="Docker background" * 1000,
            )
            self.assertEqual(questions, [])
            messages = model.ainvoke.call_args.args[0]
            self.assertIn("take precedence", messages[0]["content"])
            self.assertEqual(
                len(json.loads(messages[1]["content"])["related_context"]), 9000
            )

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
