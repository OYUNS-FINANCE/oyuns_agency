import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunDetail, RunEvent } from "@/lib/api/types";
import {
  RUN_ID,
  event,
  idea,
  jsonResponse,
  runDetail,
  sse,
  statusEvent,
  streamResponse,
} from "@/test/fixtures";

import { RunView } from "./run-view";

function renderRun(detail: RunDetail | { status: number; body: unknown }, events: RunEvent[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.endsWith("/stream")) {
        return Promise.resolve(
          "body" in detail
            ? jsonResponse(detail.body, detail.status)
            : streamResponse([sse(events)]),
        );
      }
      return Promise.resolve(
        "body" in detail ? jsonResponse(detail.body, detail.status) : jsonResponse(detail),
      );
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RunView runId={RUN_ID} />
    </QueryClientProvider>,
  );
}

const scoutPass = [
  event(2, "agent.started", { node: "scout", iteration: 1, items: null, idea_id: null }, "scout"),
  event(
    3,
    "agent.tool_call",
    { tool: "search", query: "cafe paper receipts", result_count: 6, idea_key: null },
    "scout",
  ),
  event(
    4,
    "agent.completed",
    { node: "scout", duration_ms: 2100, summary: { kept: 3 }, idea_id: null },
    "scout",
  ),
];

describe("RunView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a skeleton while loading", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <RunView runId={RUN_ID} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Loading run…")).toBeInTheDocument();
  });

  it("renders activity and ranked cards for a run awaiting review", async () => {
    renderRun(runDetail({ status: "awaiting_human", viable_count: 1, ideas: [idea()] }), [
      statusEvent(1, "running"),
      ...scoutPass,
      statusEvent(5, "awaiting_human"),
    ]);
    expect(await screen.findByText(/1 idea is ready for your review/)).toBeInTheDocument();
    expect(
      screen.getByRole("article", { name: "Receipt-to-ledger for cafés" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Trend Scout")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Ideas (1)" })).toBeInTheDocument();
  });

  it("explains a budget-exhausted run", async () => {
    renderRun(
      runDetail({
        status: "budget_exhausted",
        error: { code: "budget_exhausted", message: "Search budget exhausted (100/100)." },
      }),
      [statusEvent(1, "running"), statusEvent(2, "budget_exhausted")],
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Budget exhausted");
    expect(alert).toHaveTextContent("Search budget exhausted (100/100).");
  });

  it("breaks the cost down by agent and shows the daily cap", async () => {
    const base = runDetail({ status: "awaiting_human", viable_count: 0 });
    renderRun(
      {
        ...base,
        budget: {
          ...base.budget,
          cost_usd: 0.4123,
          cost_by_agent: [
            {
              agent: "scout",
              model: "claude-haiku-5-5",
              calls: 3,
              input_tokens: 12_000,
              output_tokens: 2_400,
              cache_read_input_tokens: 8_000,
              cost_usd: 0.0123,
            },
            {
              agent: "skeptic",
              model: "claude-opus-5-5",
              calls: 2,
              input_tokens: 9_000,
              output_tokens: 3_000,
              cache_read_input_tokens: 0,
              cost_usd: 0.4,
            },
          ],
          daily_cap_usd: 20,
          daily_spent_usd: 4.5,
        },
      },
      [statusEvent(1, "awaiting_human")],
    );
    const table = await screen.findByRole("table", { name: "LLM cost by agent" });
    expect(within(table).getByRole("rowheader", { name: "Trend Scout" })).toBeInTheDocument();
    expect(within(table).getByText("$0.0123")).toBeInTheDocument();
    expect(within(table).getByText("claude-opus-5-5")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Daily spend, all runs" })).toHaveAttribute(
      "aria-valuenow",
      "4.5",
    );
  });

  it("shows the error of a failed run", async () => {
    renderRun(
      runDetail({ status: "failed", error: { code: "llm_output_error", message: "Bad JSON" } }),
      [statusEvent(1, "failed")],
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The run failed");
    expect(alert).toHaveTextContent("llm_output_error");
  });

  it("shows an honest empty state with the shortfall", async () => {
    renderRun(
      runDetail({
        status: "awaiting_human",
        viable_count: 0,
        shortfall: "Only 0 idea(s) reached the bar.",
      }),
      [statusEvent(1, "awaiting_human")],
    );
    expect(await screen.findByText("No ranked ideas")).toBeInTheDocument();
  });

  it("shows not-found for an unknown run", async () => {
    renderRun(
      { status: 404, body: { error: { code: "not_found", message: "Run not found" } } },
      [],
    );
    expect(await screen.findByText("Run not found")).toBeInTheDocument();
  });
});
