"""AnthropicLLM against a stub client: request shape, usage/cost, refusal. No network."""

import dataclasses
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.providers.llm.anthropic import FALLBACK_BETA, AnthropicLLM
from app.providers.llm.base import ChatMessage, LLMRefusalError, LLMRequest
from app.providers.llm.pricing import cost_usd


class Answer(BaseModel):
    value: int


def _response(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        model="claude-sonnet-5-5",
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        ),
    )


class StubMessages:
    def __init__(self, responses: list[SimpleNamespace]):
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.responses.pop(0)

    def stream(self, **kwargs: Any) -> "StubStream":
        self.calls.append({**kwargs, "streamed": True})
        return StubStream(self.responses.pop(0))


class StubStream:
    """Mimics BetaAsyncMessageStreamManager: async context, text_stream, final message."""

    def __init__(self, response: SimpleNamespace):
        self.response = response

    async def __aenter__(self) -> "StubStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def chunks() -> AsyncIterator[str]:
            text = self.response.content[0].text
            for i in range(0, len(text), 4):
                yield text[i : i + 4]

        return chunks()

    async def get_final_message(self) -> SimpleNamespace:
        return self.response


def _llm(*responses: SimpleNamespace) -> tuple[AnthropicLLM, StubMessages]:
    messages = StubMessages(list(responses))
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicLLM(cast(AsyncAnthropic, client)), messages


def _request() -> LLMRequest[Answer]:
    return LLMRequest(
        agent="test",
        model="claude-sonnet-5-5",
        system="sys",
        messages=[ChatMessage(role="user", content="hi")],
        output_type=Answer,
    )


async def test_sends_json_schema_and_fallbacks_and_prices_usage() -> None:
    llm, messages = _llm(_response('{"value": 5}'))
    result = await llm.generate(_request())
    assert result.output.value == 5
    call = messages.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "value" in call["output_config"]["format"]["schema"]["properties"]
    assert call["output_config"]["effort"] == "medium"
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["system"] == "sys"
    assert result.usage[0].cost_usd == pytest.approx(
        cost_usd("claude-sonnet-5-5", input_tokens=1000, output_tokens=200)
    )
    assert result.usage[0].cost_usd == pytest.approx(0.004)


async def test_validation_retry_resends_conversation() -> None:
    llm, messages = _llm(_response('{"value": "x"}'), _response('{"value": 1}'))
    await llm.generate(_request())
    second = messages.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]


async def test_refusal_raises() -> None:
    llm, _ = _llm(_response("", stop_reason="refusal"))
    with pytest.raises(LLMRefusalError, match="category=cyber"):
        await llm.generate(_request())


async def test_streams_deltas_per_attempt_when_on_delta_is_set() -> None:
    llm, messages = _llm(_response('{"value": "x"}'), _response('{"value": 12}'))
    seen: list[tuple[str, int]] = []

    async def on_delta(text: str, attempt: int) -> None:
        seen.append((text, attempt))

    result = await llm.generate(dataclasses.replace(_request(), on_delta=on_delta))
    assert result.output.value == 12 and result.attempts == 2
    assert all(c["streamed"] for c in messages.calls)
    assert "".join(t for t, a in seen if a == 1) == '{"value": "x"}'
    assert "".join(t for t, a in seen if a == 2) == '{"value": 12}'
