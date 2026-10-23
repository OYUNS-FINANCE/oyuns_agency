"""Anthropic implementation of the LLM provider (JSON-schema structured output)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import structlog
from anthropic import AsyncAnthropic, transform_schema
from anthropic.types.beta import (
    BetaAssistantMessageParam,
    BetaMessageParam,
    BetaTextBlockParam,
    BetaUserMessageParam,
)
from pydantic import BaseModel

from app.providers.llm.base import (
    BeforeCallHook,
    ChatMessage,
    LLMRefusalError,
    LLMRequest,
    RawCompletion,
    StructuredLLMProvider,
    UsageHook,
    UsageRecord,
)
from app.providers.llm.pricing import PRICES, cost_usd

log = structlog.get_logger(__name__)

Effort = Literal["low", "medium", "high", "xhigh", "max"]
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM(StructuredLLMProvider):
    def __init__(
        self,
        client: AsyncAnthropic,
        *,
        effort: Effort = "medium",
        prompt_caching: bool = True,
        max_validation_retries: int = 2,
        usage_hook: UsageHook | None = None,
        before_call: BeforeCallHook | None = None,
    ):
        super().__init__(
            max_validation_retries=max_validation_retries,
            usage_hook=usage_hook,
            before_call=before_call,
        )
        self.client = client
        self.effort = effort
        self.prompt_caching = prompt_caching
        self._schemas: dict[type[BaseModel], dict[str, Any]] = {}

    def _schema(self, output_type: type[BaseModel]) -> dict[str, Any]:
        if output_type not in self._schemas:
            self._schemas[output_type] = transform_schema(output_type)
        return self._schemas[output_type]

    async def _complete(
        self, request: LLMRequest[BaseModel], messages: Sequence[ChatMessage], attempt: int
    ) -> RawCompletion:
        params: list[BetaMessageParam] = [
            BetaUserMessageParam(role="user", content=m.content)
            if m.role == "user"
            else BetaAssistantMessageParam(role="assistant", content=m.content)
            for m in messages
        ]
        system: str | list[BetaTextBlockParam] = request.system
        if self.prompt_caching:
            # The system prompt is identical across every call of an agent; a validation
            # retry also resends the whole first user turn (the search results), so that is
            # cached from the second attempt on. Prompts below the model's minimum cacheable
            # length are simply not cached.
            system = [
                BetaTextBlockParam(
                    type="text", text=request.system, cache_control={"type": "ephemeral"}
                )
            ]
            if len(params) > 1 and messages[0].role == "user":
                params[0] = BetaUserMessageParam(
                    role="user",
                    content=[
                        BetaTextBlockParam(
                            type="text",
                            text=messages[0].content,
                            cache_control={"type": "ephemeral"},
                        )
                    ],
                )
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": system,
            "messages": params,
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": self._schema(request.output_type)},
            },
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if request.on_delta is None:
            response = await self.client.beta.messages.create(**kwargs)
        else:
            async with self.client.beta.messages.stream(**kwargs) as stream:
                async for delta in stream.text_stream:
                    await request.on_delta(delta, attempt)
                response = await stream.get_final_message()
        u = response.usage
        record = UsageRecord(
            agent=request.agent,
            model=response.model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_input_tokens=u.cache_read_input_tokens or 0,
            cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
            cost_usd=cost_usd(
                response.model,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_input_tokens=u.cache_read_input_tokens or 0,
                cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
            ),
            attempt=attempt,
        )
        if response.model not in PRICES:
            log.warning("llm.unpriced_model", model=response.model)
        if response.stop_reason == "refusal":
            if self.usage_hook is not None:
                await self.usage_hook(record)
            category = response.stop_details.category if response.stop_details else None
            raise LLMRefusalError(f"{request.agent}: request declined (category={category})")
        text = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason == "max_tokens":
            log.warning("llm.max_tokens", agent=request.agent, max_tokens=request.max_tokens)
        return RawCompletion(text=text, usage=record)
