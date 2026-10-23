import pytest
from pydantic import BaseModel

from app.providers.llm.base import ChatMessage, LLMOutputError, LLMRequest, UsageRecord
from app.providers.llm.fake import FakeLLM


class Answer(BaseModel):
    value: int


def _request(**kwargs: object) -> LLMRequest[Answer]:
    return LLMRequest(
        agent="test",
        model="claude-sonnet-5-5",
        system="Answer.",
        messages=[ChatMessage(role="user", content="Give me a number.")],
        output_type=Answer,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_valid_response_on_first_attempt() -> None:
    llm = FakeLLM({"test": [Answer(value=3)]})
    result = await llm.generate(_request())
    assert result.output == Answer(value=3)
    assert result.attempts == 1
    assert len(result.usage) == 1


async def test_retries_after_schema_failure_and_feeds_error_back() -> None:
    llm = FakeLLM({"test": [{"value": "not a number"}, {"value": 4}]})
    result = await llm.generate(_request())
    assert result.output.value == 4
    assert result.attempts == 2
    retry_call = llm.calls[1]
    assert retry_call.attempt == 2
    assert retry_call.messages[-2].role == "assistant"
    assert "failed validation" in retry_call.messages[-1].content
    assert "value" in retry_call.messages[-1].content


async def test_retries_on_invalid_json() -> None:
    llm = FakeLLM({"test": ["{not json", {"value": 1}]})
    assert (await llm.generate(_request())).attempts == 2


async def test_semantic_validator_triggers_retry() -> None:
    def must_be_even(a: Answer) -> None:
        if a.value % 2:
            raise ValueError("value must be even")

    llm = FakeLLM({"test": [{"value": 3}, {"value": 8}]})
    result = await llm.generate(_request(validator=must_be_even))
    assert result.output.value == 8
    assert "value must be even" in llm.calls[1].messages[-1].content


async def test_gives_up_after_max_retries_with_usage() -> None:
    llm = FakeLLM({"test": [{"value": "x"}] * 3}, max_validation_retries=2)
    with pytest.raises(LLMOutputError) as exc:
        await llm.generate(_request())
    assert exc.value.attempts == 3
    assert len(exc.value.usage) == 3


async def test_usage_hook_sees_every_attempt() -> None:
    seen: list[UsageRecord] = []

    async def hook(u: UsageRecord) -> None:
        seen.append(u)

    llm = FakeLLM({"test": [{"value": "x"}, {"value": 2}]}, usage_hook=hook)
    await llm.generate(_request())
    assert [u.attempt for u in seen] == [1, 2]
    assert all(u.agent == "test" and u.input_tokens > 0 for u in seen)


async def test_unscripted_agent_raises() -> None:
    with pytest.raises(LookupError, match="no scripted response"):
        await FakeLLM().generate(_request())
