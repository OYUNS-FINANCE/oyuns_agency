"""Co-working I/O schemas."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from app.services.brief_patch import PatchOperation

CoworkAgentName = Literal["scout", "analyst", "skeptic"]


class ProposedEdit(BaseModel):
    """One JSON Patch operation as the model writes it. The value travels JSON-encoded, so
    the output schema stays a plain object for structured output."""

    op: Literal["add", "replace", "remove"]
    path: str = Field(min_length=2, max_length=200)
    value_json: str | None = Field(
        default=None, max_length=8000, description="New value as JSON; null for remove."
    )

    def to_operation(self) -> PatchOperation:
        if self.op == "remove":
            return PatchOperation(op="remove", path=self.path)
        if self.value_json is None:
            raise ValueError(f"{self.op} {self.path} needs value_json")
        try:
            value = json.loads(self.value_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"value_json for {self.path} is not valid JSON: {exc}") from exc
        return PatchOperation(op=self.op, path=self.path, value=value)


class CoworkOutput(BaseModel):
    """`reply` comes first: the stream reader shows it while the rest is generated."""

    reply: str = Field(min_length=1, max_length=4000)
    edits: list[ProposedEdit] = Field(default_factory=list, max_length=12)

    def patch(self) -> list[PatchOperation]:
        return [e.to_operation() for e in self.edits]


class TranscriptLine(BaseModel):
    role: Literal["user", "assistant"]
    agent: CoworkAgentName
    content: str


class CoworkInput(BaseModel):
    agent: CoworkAgentName
    run_context: str
    """The founder's request and profile (trusted)."""
    brief_json: str
    """The current version's opportunity + analysis + critique, as JSON."""
    version: int
    history: list[TranscriptLine]
    message: str
