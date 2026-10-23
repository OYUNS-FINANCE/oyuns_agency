"""Prompt-injection hygiene for fetched web content (ADR 0008).

Defence in depth: this runs first, then `wrap_untrusted` delimits what is left and every
prompt tells the model to treat the block as data. The sanitiser

- strips markup, control and invisible characters (zero-width, bidi overrides, tag
  characters), which are the usual way to hide instructions from a human reviewer,
- redacts sentences that read as instructions to an AI system, and logs each one,
- caps field lengths.

It never rewrites numbers or facts: only whole instruction-like sentences are replaced, by a
visible marker, so a redaction is auditable in the prompt and in the logs.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Sequence

import structlog

from app.providers.search.base import SearchProvider, SearchResult

log = structlog.get_logger(__name__)

REDACTION = "[removed: instruction-like text]"
ELLIPSIS = "…"

_SCRIPT_OR_STYLE = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.I | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]{0,2000}>")
_WHITESPACE = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")

# Unicode "format" characters that render as nothing: zero-width spaces/joiners, bidi
# overrides and isolates, word joiner, BOM, and the Tags block (U+E0000..U+E007F).
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b"
        r".{0,40}\b(instructions?|prompts?|rules?|guidelines?|context|directives?)\b",
        r"\b(you are|you're|you will be|act as|pretend to be|behave as)\b.{0,30}"
        r"\b(now|admin|developer|root|jailbroken|dan|unrestricted|system)\b",
        r"^\s*(system|assistant|developer|admin)\s*(prompt|message|override)?\s*:",
        r"\b(new|updated|revised)\s+(system\s+)?(instructions?|prompt|rules)\b",
        r"\b(reveal|print|output|repeat|show)\b.{0,30}"
        r"\b(system prompt|hidden instructions?|your instructions)\b",
        r"\b(rate|score|rank|grade)\b.{0,30}\b(every|all|each)\b.{0,30}\b(ideas?|opportunit\w+|results?)\b"
        r".{0,20}\b(\d+\s*/\s*10|10|highest|maximum|perfect)\b",
        r"\binvent\b.{0,30}\b(numbers?|figures?|statistics|data)\b",
        r"\b(do not|don't|never)\b.{0,20}\b(mention|tell|reveal|disclose)\b.{0,30}"
        r"\b(user|founder|human)\b",
        r"\bas an ai (language )?model\b.{0,40}\byou (must|should|will)\b",
        r"<\s*/?\s*(system|instructions?|untrusted_web_content)\b",
    )
)


def strip_markup(text: str) -> str:
    text = _SCRIPT_OR_STYLE.sub(" ", text)
    text = _COMMENT.sub(" ", text)
    text = _TAG.sub(" ", text)
    return html.unescape(text)


def strip_invisible(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


def tidy(text: str) -> str:
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def looks_like_injection(sentence: str) -> bool:
    return any(p.search(sentence) for p in _INJECTION_PATTERNS)


def redact_injections(text: str) -> tuple[str, int]:
    """Replaces every instruction-like sentence with a marker; returns (text, count)."""
    redacted = 0
    out: list[str] = []
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0)
        if looks_like_injection(sentence):
            redacted += 1
            out.append(f" {REDACTION} ")
        else:
            out.append(sentence)
    return tidy("".join(out)), redacted


def cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - len(ELLIPSIS)]
    # Back off to a word boundary when one is near, so a figure is not cut mid-number.
    space = cut.rfind(" ")
    if space > limit * 0.8:
        cut = cut[:space]
    return cut.rstrip() + ELLIPSIS


def clean_text(text: str, max_chars: int) -> tuple[str, int]:
    """Markup and invisible characters out, instruction-like sentences redacted, length
    capped. Returns (clean text, number of redactions). Idempotent."""
    text = tidy(strip_invisible(strip_markup(text)))
    text, redacted = redact_injections(text)
    return cap(text, max_chars), redacted


def sanitize_result(
    result: SearchResult, *, snippet_max_chars: int, title_max_chars: int
) -> tuple[SearchResult, int]:
    title, t_redacted = clean_text(result.title, title_max_chars)
    snippet, s_redacted = clean_text(result.snippet, snippet_max_chars)
    cleaned = result.model_copy(update={"title": title or "(untitled)", "snippet": snippet})
    return cleaned, t_redacted + s_redacted


def sanitize_results(
    results: Sequence[SearchResult], *, snippet_max_chars: int, title_max_chars: int
) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()
    for result in results:
        if result.url in seen:
            continue
        seen.add(result.url)
        cleaned, redacted = sanitize_result(
            result, snippet_max_chars=snippet_max_chars, title_max_chars=title_max_chars
        )
        if redacted:
            log.warning("search.injection_suspected", url=result.url, redacted_sentences=redacted)
        out.append(cleaned)
    return out


class SanitizingSearch:
    """Wraps a provider so nothing it returns reaches a prompt unsanitised."""

    def __init__(self, inner: SearchProvider, *, snippet_max_chars: int, title_max_chars: int):
        self.inner = inner
        self.snippet_max_chars = snippet_max_chars
        self.title_max_chars = title_max_chars

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        return sanitize_results(
            await self.inner.search(query, max_results=max_results),
            snippet_max_chars=self.snippet_max_chars,
            title_max_chars=self.title_max_chars,
        )
