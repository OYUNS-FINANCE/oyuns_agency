"""Field types shared by agent schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, HttpUrl, TypeAdapter

_HTTP_URL: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


def _normalise_http_url(value: str) -> str:
    return str(_HTTP_URL.validate_python(value))


WebUrl = Annotated[str, AfterValidator(_normalise_http_url)]
"""An http(s) URL validated and normalised like HttpUrl but stored as str, so models stay
msgpack-serialisable for the LangGraph checkpointer (pydantic Url objects are not)."""
