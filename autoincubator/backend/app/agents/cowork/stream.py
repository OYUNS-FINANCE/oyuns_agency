"""Incremental reader for the `reply` string of a streamed CoworkOutput JSON object."""

from __future__ import annotations

import json

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class ReplyStreamReader:
    """Feeds raw JSON text; returns newly decoded characters of the top-level `reply` value.

    Structured output follows the schema's property order, so `reply` normally arrives first
    and the founder sees it while the edits are still being generated. If the text has a
    different shape the reader yields nothing, and the final message carries the full reply.
    """

    KEY = '"reply"'

    def __init__(self) -> None:
        self._buffer = ""
        self._pos = 0
        self._state = "seek"  # seek → colon → open → string → done
        self._unicode = ""

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        out: list[str] = []
        while self._pos < len(self._buffer) and self._state != "done":
            if self._state == "seek":
                at = self._buffer.find(self.KEY, self._pos)
                if at < 0:
                    self._pos = max(self._pos, len(self._buffer) - len(self.KEY))
                    break
                self._pos = at + len(self.KEY)
                self._state = "open"
                continue
            ch = self._buffer[self._pos]
            if self._state == "open":
                self._pos += 1
                if ch == '"':
                    self._state = "string"
                elif ch not in " \t\r\n:":
                    self._state = "done"  # not a string value; give up quietly
                continue
            # Inside the string: stop before an incomplete escape and wait for more text.
            if ch == "\\":
                if self._pos + 1 >= len(self._buffer):
                    break
                esc = self._buffer[self._pos + 1]
                if esc == "u":
                    if self._pos + 6 > len(self._buffer):
                        break
                    out.append(self._decode_unicode(self._buffer[self._pos + 2 : self._pos + 6]))
                    self._pos += 6
                else:
                    out.append(_ESCAPES.get(esc, esc))
                    self._pos += 2
                continue
            self._pos += 1
            if ch == '"':
                self._state = "done"
            else:
                out.append(ch)
        return "".join(out)

    def _decode_unicode(self, hex4: str) -> str:
        """Joins UTF-16 surrogate pairs that arrive as two \\u escapes."""
        code = int(hex4, 16)
        if 0xD800 <= code <= 0xDBFF:
            self._unicode = hex4
            return ""
        if 0xDC00 <= code <= 0xDFFF and self._unicode:
            pair = json.loads(f'"\\u{self._unicode}\\u{hex4}"')
            self._unicode = ""
            return str(pair)
        return chr(code)
