/** Typed builders for API payloads and SSE events used across tests. */
import type { EventOf, IdeaView, RunDetail, RunEvent, RunEventType } from "@/lib/api/types";

export const RUN_ID = "11111111-1111-4111-8111-111111111111";

let ts = Date.parse("2026-10-23T10:00:00Z");

export function event<T extends RunEventType>(
  id: number,
  type: T,
  data: EventOf<T>["data"],
  agent: string | null = null,
): EventOf<T> {
  ts += 1_000;
  return { id, run_id: RUN_ID, ts: new Date(ts).toISOString(), agent, type, data } as EventOf<T>;
}

export const statusEvent = (id: number, status: EventOf<"run.status">["data"]["status"]) =>
  event(id, "run.status", { status, previous: null, detail: null });

export function idea(overrides: Partial<IdeaView> = {}): IdeaView {
  const figure = (value: number, source_url: string | null) => ({
    value,
    unit: "USD",
    source_url,
    assumption: source_url ? null : "Bottom-up from 2,000 cafés × $50/month",
  });
  return {
    id: "22222222-2222-4222-8222-222222222222",
    key: "opp-01",
    status: "active",
    rank: 1,
    composite_score: 7.4,
    version: 1,
    version_source: "agent",
    title: "Receipt-to-ledger for cafés",
    opportunity: {
      id: "opp-01",
      iteration: 1,
      title: "Receipt-to-ledger for cafés",
      one_liner: "Photograph paper receipts and get a reconciled ledger every Friday.",
      problem: "Small cafés still keep paper receipts and reconcile by hand.",
      target_customer: "Independent cafés with 1–3 locations",
      industry: "Hospitality",
      business_model: "b2b",
      signals: [
        { category: "complaint_thread", url: "https://example.com/a", evidence: "Owners complain" },
        { category: "rising_search", url: "https://example.com/b", evidence: "Search interest" },
      ],
      novelty_score: 7,
      signal_strength: 8,
      is_generic: false,
    },
    analysis: {
      opportunity_id: "opp-01",
      sizing: {
        method: "bottom_up",
        method_explanation: "Count of cafés times price.",
        tam: figure(4_200_000_000, "https://example.com/a"),
        sam: figure(120_000_000, "https://example.com/c"),
        som: figure(1_200_000, null),
      },
      competitors: [{ name: "BigBooks", url: "https://example.com/d", positioning: "Generic" }],
      pricing_benchmarks: [],
      segments: [{ name: "Cafés", description: "Independent cafés" }],
      summary: "A narrow but reachable market.",
    },
    critique: {
      opportunity_id: "opp-01",
      scores: [
        { dimension: "cac_risk", score: 6, justification: "Cafés are reachable." },
        { dimension: "channel_dependency", score: 5, justification: "Mostly direct sales." },
        { dimension: "churn_risk", score: 7, justification: "Sticky once set up." },
        { dimension: "defensibility", score: 3, justification: "Easy to copy features." },
        { dimension: "regulatory_risk", score: 9, justification: "Little regulation." },
        { dimension: "time_to_first_revenue", score: 8, justification: "Weeks, not months." },
        {
          dimension: "solo_founder_feasibility",
          score: 8,
          justification: "One builder is enough.",
        },
      ],
      most_likely_failure_cause: "Accounting suites bundle the same feature for free.",
      attack_summary: "The wedge is thin and incumbents can close it quickly.",
    },
    ...overrides,
  };
}

export function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: RUN_ID,
    mode: "seeded",
    seed: "Bookkeeping for cafés",
    status: "running",
    error: null,
    viable_count: null,
    created_at: "2026-10-23T10:00:00Z",
    updated_at: "2026-10-23T10:00:00Z",
    started_at: "2026-10-23T10:00:01Z",
    finished_at: null,
    input: {
      mode: "seeded",
      seed: "Bookkeeping for cafés",
      constraints: { business_model: "any", solo_founder: false },
    },
    shortfall: null,
    budget: {
      max_tokens: 1_000_000,
      tokens_used: 1_000,
      max_searches: 100,
      searches_used: 2,
      cost_usd: 0.01,
    },
    ideas: [],
    ...overrides,
  };
}

/** Encodes events as an SSE body, the way the API writes them. */
export function sse(events: readonly RunEvent[]): string {
  return events.map((e) => `id: ${e.id}\ndata: ${JSON.stringify(e)}\n\n`).join("");
}

/**
 * A streamed `Response` whose body emits `chunks` and then either ends or fails, like a
 * connection dropped mid-run.
 */
export function streamResponse(
  chunks: readonly string[],
  { fail = false, status = 200 }: { fail?: boolean; status?: number } = {},
): Response {
  const encoder = new TextEncoder();
  let next = 0;
  // Pull-based so every chunk is read before the error: `error()` would discard queued chunks.
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      const chunk = chunks[next++];
      if (chunk !== undefined) controller.enqueue(encoder.encode(chunk));
      else if (fail) controller.error(new TypeError("network error"));
      else controller.close();
    },
  });
  return new Response(body, { status, headers: { "content-type": "text/event-stream" } });
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
