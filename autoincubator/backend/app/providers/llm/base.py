"""LLM provider protocol, structured-output retry loop and usage accounting."""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import structlog
from pydantic import BaseModel, ValidationError

log = structlog.get_logger(__name__)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class UsageRecord(BaseModel):
    """Token and cost accounting for one provider call (one attempt)."""

    agent: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0
    attempt: int = 1


UsageHook = Callable[[UsageRecord], Awaitable[None]]
"""Called after every provider call, successful or not (run_costs + budget accounting)."""
BeforeCallHook = Callable[[str], Awaitable[None]]
"""Called with the agent name before every provider call, retries included. Raising
(e.g. BudgetExhaustedError) stops the call."""


@dataclass(frozen=True)
class LLMRequest[T: BaseModel]:
    agent: str
    model: str
    system: str
    messages: Sequence[ChatMessage]
    output_type: type[T]
    max_tokens: int = 16_000
    validator: Callable[[T], None] | None = None
    """Extra semantic check after schema validation; raise ValueError to trigger a retry."""


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    usage: list[UsageRecord] = field(default_factory=list)
    attempts: int = 1


@dataclass(frozen=True)
class RawCompletion:
    """What a concrete provider returns before validation: the JSON text plus usage."""

    text: str
    usage: UsageRecord


class LLMOutputError(RuntimeError):
    """The model did not produce valid output within the allowed retries."""

    def __init__(self, agent: str, attempts: int, last_error: str, usage: list[UsageRecord]):
        super().__init__(f"{agent}: no valid output after {attempts} attempt(s): {last_error}")
        self.agent = agent
        self.attempts = attempts
        self.last_error = last_error
        self.usage = usage


class LLMRefusalError(RuntimeError):
    """The model (and any server-side fallback) declined the request."""


class LLMProvider(Protocol):
    async def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]: ...


class StructuredLLMProvider(abc.ABC):
    """Shared retry loop: complete → validate → on failure, feed the error back and retry."""

    def __init__(
        self,
        *,
        max_validation_retries: int = 2,
        usage_hook: UsageHook | None = None,
        before_call: BeforeCallHook | None = None,
    ):
        self.max_validation_retries = max_validation_retries
        self.usage_hook = usage_hook
        self.before_call = before_call

    @abc.abstractmethod
    async def _complete(
        self, request: LLMRequest[BaseModel], messages: Sequence[ChatMessage], attempt: int
    ) -> RawCompletion: ...

    async def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]:
        messages: list[ChatMessage] = list(request.messages)
        usage: list[UsageRecord] = []
        last_error = ""
        attempts = self.max_validation_retries + 1
        for attempt in range(1, attempts + 1):
            if self.before_call is not None:
                await self.before_call(request.agent)
            raw = await self._complete(request, messages, attempt)  # type: ignore[arg-type]
            usage.append(raw.usage)
            if self.usage_hook is not None:
                await self.usage_hook(raw.usage)
            try:
                output = request.output_type.model_validate_json(raw.text)
                if request.validator is not None:
                    request.validator(output)
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                log.warning(
                    "llm.validation_failed", agent=request.agent, attempt=attempt, error=last_error
                )
                messages = [
                    *messages,
                    ChatMessage(role="assistant", content=raw.text),
                    ChatMessage(role="user", content=_retry_prompt(last_error)),
                ]
                continue
            return LLMResult(output=output, usage=usage, attempts=attempt)
        raise LLMOutputError(request.agent, attempts, last_error, usage)


def _retry_prompt(error: str) -> str:
    return (
        "Your previous response failed validation:\n"
        f"{error}\n"
        "Return a corrected response that satisfies the schema and every rule in the "
        "instructions. Do not invent sources: if a figure has no source URL from the "
        "provided material, give it an explicit assumption instead."
    )
