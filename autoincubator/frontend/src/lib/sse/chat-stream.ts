/**
 * One co-working reply over `POST …/ideas/{id}/cowork` (ADR 0006): named SSE events
 * `started`, `delta`*, `reset`, then `completed` or `error`. Unlike the run stream this is
 * not resumable; after a dropped connection the stored messages are re-read instead.
 */
import { ApiError, errorFromResponse } from "@/lib/api/client";
import type {
  CoworkDelta,
  CoworkFailed,
  CoworkMessage,
  CoworkRequest,
  CoworkStarted,
} from "@/lib/api/types";

import { SseParser } from "./parse";

export type ChatStreamEvent =
  | { event: "started"; data: CoworkStarted }
  | { event: "delta"; data: CoworkDelta }
  | { event: "reset"; data: Record<string, never> }
  | { event: "completed"; data: CoworkMessage }
  | { event: "error"; data: CoworkFailed };

const NAMES = new Set(["started", "delta", "reset", "completed", "error"]);

export async function streamChat({
  url,
  body,
  signal,
  onEvent,
}: {
  url: string;
  body: CoworkRequest;
  signal?: AbortSignal;
  onEvent: (event: ChatStreamEvent) => void;
}): Promise<void> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      cache: "no-store",
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError("The API is unreachable", 0, "network_error");
  }
  if (!response.ok) throw await errorFromResponse(response);
  if (!response.body) throw new ApiError("The reply stream is empty", response.status);

  const parser = new SseParser();
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const message of parser.push(value)) {
      if (!NAMES.has(message.event)) continue;
      onEvent({ event: message.event, data: JSON.parse(message.data) } as ChatStreamEvent);
    }
  }
}
