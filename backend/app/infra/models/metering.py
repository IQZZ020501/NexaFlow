"""Meter each provider request, including bound tools and compaction requests."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import Field

from app.domain.agents.runtime.usage import usage_from_message
from app.infra.db.repositories.governance import tokens
from app.infra.db.session import get_session_factory
from app.ports.llm import ModelProviderError

OUTPUT_KEYS = (
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
    "num_predict",
)


class MeteredChatModel(BaseChatModel):
    wrapped: Any = Field(exclude=True)
    registered: Any = Field(exclude=True)
    parameters: dict = Field(default_factory=dict)
    tools: list = Field(default_factory=list)

    def __init__(self, model, registered, *, parameters=None, tools=None):
        super().__init__(
            wrapped=model,
            registered=registered,
            parameters=parameters or {},
            tools=tools or [],
            profile=getattr(model, "profile", None),
        )

    @property
    def model(self):
        return self.wrapped

    @property
    def _llm_type(self):
        return "metered-chat"

    def __getattr__(self, name):
        try:
            return super().__getattr__(name)
        except AttributeError:
            return getattr(self.wrapped, name)

    def _generate(self, *_args, **_kwargs):
        raise ModelProviderError("Metered chat calls require async execution.")

    def bind_tools(self, tools, **kwargs):
        from langchain_core.utils.function_calling import convert_to_openai_tool

        return MeteredChatModel(
            self.model.bind_tools(tools, **kwargs),
            self.registered,
            parameters={
                **self.parameters,
                **{key: value for key, value in kwargs.items() if key in OUTPUT_KEYS},
            },
            tools=[convert_to_openai_tool(tool) for tool in tools],
        )

    def bind(self, **kwargs):
        return MeteredChatModel(
            self.model,
            self.registered,
            parameters={**self.parameters, **kwargs},
            tools=self.tools,
        )

    async def _reserve(self, messages, kwargs):
        params = {**self.parameters, **kwargs}
        configured = (self.registered.meta or {}).get("request_params") or {}
        output = min(
            [
                value
                for key in OUTPUT_KEYS
                if type(value := params.get(key, configured.get(key))) is int
                and value > 0
            ]
            or [4096]
        )
        provider = self.registered.provider_type
        key = next(
            (key for key in OUTPUT_KEYS if key in params or key in configured),
            "max_output_tokens"
            if provider == "google_genai"
            else "num_predict"
            if provider == "ollama"
            else "max_tokens",
        )
        # Reserve UTF-8 bytes plus schema/framing overhead, never a billing estimate.
        inputs = (
            messages.to_messages()
            if hasattr(messages, "to_messages")
            else [messages]
            if isinstance(messages, str)
            else messages
        )
        payload = [
            message.model_dump() if hasattr(message, "model_dump") else message
            for message in inputs
        ]
        input_bound = (
            len(
                json.dumps(
                    [payload, self.tools], ensure_ascii=False, default=str
                ).encode()
            )
            + 4096
        )
        identity = str(uuid4())
        async with get_session_factory()() as db:
            enforced = await tokens.reserve(
                db,
                self.registered.workspace_id,
                self.registered.id,
                identity,
                input_bound + output,
            )
            await db.commit()
        if enforced:
            params.update({key: output})
        return identity, params

    async def _settle(self, identity, message):
        usage = usage_from_message(message) if message is not None else None
        response = getattr(message, "response_metadata", None) or {}
        response = response if isinstance(response, Mapping) else {}
        sources = [
            getattr(message, "usage_metadata", None) or {},
            response.get("usage") or {},
            response.get("token_usage") or {},
            response,
        ]
        sources = [source for source in sources if isinstance(source, Mapping)]

        def reported(*keys):
            return any(
                type(value := source.get(key)) is int
                and value >= 0
                or isinstance(value, str)
                and value.isdigit()
                for source in sources
                for key in keys
            )

        complete = reported("total_tokens") or (
            reported("input_tokens", "prompt_tokens")
            and reported("output_tokens", "completion_tokens")
        )
        actual = usage["total_tokens"] if usage and complete else None
        async with get_session_factory()() as db:
            await tokens.settle(db, identity, actual)
            await db.commit()

    async def ainvoke(self, messages, config=None, **kwargs):
        if config is not None:
            kwargs["config"] = config
        identity, params = await self._reserve(messages, kwargs)
        response = None
        try:
            response = await self.model.ainvoke(messages, **params)
            return response
        finally:
            await asyncio.shield(self._settle(identity, response))

    async def astream(self, messages, config=None, **kwargs):
        from contextlib import aclosing

        if config is not None:
            kwargs["config"] = config
        identity, params = await self._reserve(messages, kwargs)
        aggregate = None
        complete = False
        try:
            async with aclosing(self.model.astream(messages, **params)) as stream:
                async for chunk in stream:
                    aggregate = chunk if aggregate is None else aggregate + chunk
                    yield chunk
                complete = True
        finally:
            await asyncio.shield(
                self._settle(identity, aggregate if complete else None)
            )

    def invoke(self, *_args, **_kwargs):
        raise ModelProviderError("Metered chat calls require async execution.")
