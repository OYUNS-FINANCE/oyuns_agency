import { describe, expect, it } from "vitest";

import { SseParser } from "./parse";

describe("SseParser", () => {
  it("parses id, data and retry, and ignores comment pings", () => {
    const parser = new SseParser();
    const messages = parser.push(': ping\n\nid: 7\nretry: 3000\ndata: {"a":1}\n\n');
    expect(messages).toEqual([{ id: "7", event: "message", data: '{"a":1}', retry: 3000 }]);
  });

  it("joins multi-line data and handles CRLF line endings", () => {
    const parser = new SseParser();
    expect(parser.push("id: 1\r\ndata: one\r\ndata: two\r\n\r\n")).toEqual([
      { id: "1", event: "message", data: "one\ntwo", retry: null },
    ]);
  });

  it("reassembles messages split across arbitrary chunk boundaries", () => {
    const parser = new SseParser();
    const text = 'id: 1\ndata: {"x":"a"}\n\nid: 2\r\ndata: {"x":"b"}\r\n\r\n';
    const out = [];
    for (const char of text) out.push(...parser.push(char));
    expect(out.map((m) => [m.id, m.data])).toEqual([
      ["1", '{"x":"a"}'],
      ["2", '{"x":"b"}'],
    ]);
  });

  it("keeps the last id for later messages without one, as EventSource does", () => {
    const parser = new SseParser();
    expect(parser.push("id: 4\ndata: a\n\ndata: b\n\n").map((m) => m.id)).toEqual(["4", "4"]);
  });

  it("does not dispatch an unfinished message", () => {
    const parser = new SseParser();
    expect(parser.push("id: 1\ndata: partial")).toEqual([]);
    expect(parser.push("\n\n")).toHaveLength(1);
  });
});
