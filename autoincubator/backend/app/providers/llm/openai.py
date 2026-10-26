"""OpenAI implementation of the LLM provider (strict JSON-schema structured output)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog
from openai import AsyncOpenAI
from openai.lib._pydantic import to_strict_json_schema
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
from app.providers.llm.pricing import cost_usd, price_for

log = structlog.get_logger(__name__)


class OpenAILLM(StructuredLLMProvider):
    def __init__(
        self,
        client: AsyncOpenAI,
        *,
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
        self._schemas: dict[type[BaseModel], dict[str, Any]] = {}

    def _schema(self, output_type: type[BaseModel]) -> dict[str, Any]:
        if output_type not in self._schemas:
            self._schemas[output_type] = to_strict_json_schema(output_type)
        return self._schemas[output_type]

    async def _complete(
        self, request: LLMRequest[BaseModel], messages: Sequence[ChatMessage], attempt: int
    ) -> RawCompletion:
        # Prompt caching is automatic on OpenAI (prefix match), so there is nothing to mark.
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_completion_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output_type.__name__,
                    "schema": self._schema(request.output_type),
                    "strict": True,
                },
            },
        }
        if request.on_delta is None:
            response = await self.client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""
            refusal = response.choices[0].message.refusal
            model, usage = response.model, response.usage
            finish = response.choices[0].finish_reason
        else:
            parts: list[str] = []
            refusal = None
            model, usage, finish = request.model, None, None
            stream = await self.client.chat.completions.create(
                **kwargs, stream=True, stream_options={"include_usage": True}
            )
            async for chunk in stream:
                model = chunk.model or model
                if chunk.usage is not None:
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish = choice.finish_reason or finish
                if choice.delta.refusal:
                    refusal = (refusal or "") + choice.delta.refusal
                if choice.delta.content:
                    parts.append(choice.delta.content)
                    await request.on_delta(choice.delta.content, attempt)
            text = "".join(parts)
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cached = (
            usage.prompt_tokens_details.cached_tokens or 0
            if usage and usage.prompt_tokens_details
            else 0
        )
        # OpenAI counts cached tokens inside prompt_tokens; the cost model wants them apart.
        record = UsageRecord(
            agent=request.agent,
            model=model,
            input_tokens=input_tokens - cached,
            output_tokens=output_tokens,
            cache_read_input_tokens=cached,
            cost_usd=cost_usd(
                model,
                input_tokens=input_tokens - cached,
                output_tokens=output_tokens,
                cache_read_input_tokens=cached,
            ),
            attempt=attempt,
        )
        if price_for(model) is None:
            log.warning("llm.unpriced_model", model=model)
        if refusal or finish == "content_filter":
            if self.usage_hook is not None:
                await self.usage_hook(record)
            raise LLMRefusalError(f"{request.agent}: request declined ({refusal or finish})")
        if finish == "length":
            log.warning("llm.max_tokens", agent=request.agent, max_tokens=request.max_tokens)
        return RawCompletion(text=text, usage=record)
