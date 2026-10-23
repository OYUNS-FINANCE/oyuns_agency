import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
  event(2, "agent.started", { node: "scout", iteration: 1, items: null }, "scout"),
  event(
    3,
    "agent.tool_call",
    { tool: "search", query: "cafe paper receipts", result_count: 6, idea_key: null },
    "scout",
  ),
  event(4, "agent.completed", { node: "scout", duration_ms: 2100, summary: { kept: 3 } }, "scout"),
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
