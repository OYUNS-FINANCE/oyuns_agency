"""Markdown dossier → HTML → PDF with WeasyPrint (ADR 0007).

The plan holds model-written text, so rendering is locked down: raw HTML in the Markdown is
not rendered, and WeasyPrint may load nothing but the bundled fonts (no network fetches
for images or stylesheets named in the text).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any
from urllib.request import url2pathname

from markdown_it import MarkdownIt

from app.core.errors import ServiceUnavailableError

EXPORT_DIR = Path(__file__).parent
FONTS = EXPORT_DIR / "fonts"
STYLESHEET = EXPORT_DIR / "templates" / "dossier.css"

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable(
    "table"
)


class PdfUnavailableError(ServiceUnavailableError):
    code = "pdf_unavailable"


def markdown_to_html(markdown: str, title: str) -> str:
    body = _md.render(markdown)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title></head><body>{body}</body></html>"
    )


def _fetcher(weasyprint: Any) -> Any:
    allowed = {p.resolve() for p in FONTS.glob("*.ttf")}

    class FontsOnlyFetcher(weasyprint.URLFetcher):  # type: ignore[misc]
        def fetch(self, url: str, headers: Any = None) -> Any:
            if url.startswith("file://"):
                path = Path(url2pathname(url.removeprefix("file://")))
                if path.resolve() in allowed:
                    return super().fetch(url, headers)
            raise ValueError(f"blocked resource: {url[:200]}")

    return FontsOnlyFetcher(allowed_protocols={"file"}, allow_redirects=False)


def render_pdf(markdown: str, title: str, *, compress: bool = True) -> bytes:
    try:
        import weasyprint  # needs Pango; imported here so the rest of the app runs without it
    except OSError as exc:
        raise PdfUnavailableError(
            "PDF export needs the Pango library on the server (see the README)."
        ) from exc
    fetcher = _fetcher(weasyprint)
    # @font-face rules are only honoured with a FontConfiguration.
    fonts = weasyprint.text.fonts.FontConfiguration()
    css = weasyprint.CSS(
        string=STYLESHEET.read_text(encoding="utf-8"),
        base_url=f"{FONTS.as_uri()}/",
        url_fetcher=fetcher,
        font_config=fonts,
    )
    document = weasyprint.HTML(
        string=markdown_to_html(markdown, title), base_url=f"{FONTS.as_uri()}/", url_fetcher=fetcher
    )
    pdf: bytes = document.write_pdf(
        stylesheets=[css], font_config=fonts, uncompressed_pdf=not compress
    )
    return pdf
