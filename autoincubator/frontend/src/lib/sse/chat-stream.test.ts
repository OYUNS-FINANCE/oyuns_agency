import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { jsonResponse, message, namedSse, streamResponse } from "@/test/fixtures";

import { streamChat, type ChatStreamEvent } from "./chat-stream";

describe("streamChat", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("POSTs the message and yields named events split across chunks", async () => {
    const body = namedSse([
      {
        event: "started",
        data: {
          user_message: message({ role: "user" }),
          assistant_message: message({ state: "pending" }),
        },
      },
      { event: "delta", data: { text: "Hel" } },
      { event: "reset", data: {} },
      { event: "delta", data: { text: "Hello" } },
      { event: "completed", data: message({ content: "Hello" }) },
    ]);
    const fetch = vi.fn(() => Promise.resolve(streamResponse([body.slice(0, 40), body.slice(40)])));
    vi.stubGlobal("fetch", fetch);
    const seen: ChatStreamEvent[] = [];
    await streamChat({
      url: "/x/cowork",
      body: { agent: "skeptic", content: "Why?" },
      onEvent: (e) => seen.push(e),
    });
    expect(seen.map((e) => e.event)).toEqual(["started", "delta", "reset", "delta", "completed"]);
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ agent: "skeptic", content: "Why?" });
  });

  it("raises the API error for a refused request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({ error: { code: "run_not_paused", message: "Not paused" } }, 409),
        ),
      ),
    );
    const error = await streamChat({
      url: "/x/cowork",
      body: { agent: "scout", content: "hi" },
      onEvent: () => {},
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "run_not_paused" });
  });
});
