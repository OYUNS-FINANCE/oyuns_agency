import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PlanResponse, RunDetail } from "@/lib/api/types";
import { money } from "@/lib/plan";
import { RUN_ID, jsonResponse, runDetail } from "@/test/fixtures";
import planFixture from "@/test/plan.json";

import { PlanView } from "./plan-view";

const PLAN = planFixture as unknown as PlanResponse;

function renderPlan(run: RunDetail | { status: number; body: unknown }) {
  const fetchMock = vi.fn((url: string) => {
    if ("body" in run) return Promise.resolve(jsonResponse(run.body, run.status));
    if (url.endsWith("/plan")) return Promise.resolve(jsonResponse(PLAN));
    return Promise.resolve(jsonResponse(run));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PlanView runId={RUN_ID} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

describe("PlanView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders every section with navigation and export links", async () => {
    renderPlan(runDetail({ status: "completed" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: PLAN.plan.brief.opportunity.title }),
    ).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Plan sections" });
    expect(within(nav).getAllByRole("link")).toHaveLength(9);
    for (const name of ["Executive summary", "Financials", "Sources & assumptions"]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /Export PDF/ })).toHaveAttribute(
      "href",
      `/api/incubator/runs/${RUN_ID}/plan/export?format=pdf`,
    );
    expect(screen.getByRole("link", { name: /Markdown/ })).toHaveAttribute(
      "href",
      `/api/incubator/runs/${RUN_ID}/plan/export?format=md`,
    );
  });

  it("switches the financial tables between base, bear and bull", async () => {
    renderPlan(runDetail({ status: "completed" }));
    const table = await screen.findByRole("region", { name: "12-month projection, base case" });
    const cashOf = (scenario: "base" | "bear" | "bull") =>
      money(PLAN.plan.financials.scenarios[scenario]!.months[11]!.cash);
    expect(within(table).getByText(cashOf("base"))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Bear" }));
    const bear = screen.getByRole("region", { name: "12-month projection, bear case" });
    expect(within(bear).getByText(cashOf("bear"))).toBeInTheDocument();
    expect(screen.getByText(/CAC ×1.3/)).toBeInTheDocument();
    const ltv = money(PLAN.plan.financials.scenarios.bear!.unit_economics.ltv);
    expect(screen.getByText(ltv)).toBeInTheDocument();
  });

  it("shows contradictions inline in their sections and in the full list", async () => {
    renderPlan(runDetail({ status: "completed" }));
    await screen.findByRole("heading", { level: 1 });
    const cac = document.querySelectorAll('[data-contradiction="channel_cac_mismatch"]');
    // GTM, financials, and the contradictions section.
    expect(cac).toHaveLength(3);
    expect(screen.getByText(/2 contradictions between sections/)).toBeInTheDocument();
    const list = screen.getByRole("region", { name: "Contradictions & open questions" });
    expect(within(list).getAllByRole("note")[0]).toHaveAttribute(
      "data-contradiction",
      "channel_cac_mismatch",
    );
  });

  it("shows the hover readout for every scenario on keyboard focus", async () => {
    renderPlan(runDetail({ status: "completed" }));
    const chart = await screen.findByRole("img", { name: "MRR" });
    fireEvent.focus(chart);
    const readout = screen.getByRole("status");
    expect(within(readout).getByText("Month 12")).toBeInTheDocument();
    const mrr = money(PLAN.plan.financials.scenarios.bull!.months[11]!.mrr);
    expect(within(readout).getByText(mrr)).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(within(screen.getByRole("status")).getByText("Month 11")).toBeInTheDocument();
  });

  it("explains that the plan is not ready while the run is still working", async () => {
    const fetchMock = renderPlan(runDetail({ status: "running" }));
    expect(await screen.findByText("The business plan is being written")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/plan"))).toBe(false);
  });

  it("reports an unknown run", async () => {
    renderPlan({ status: 404, body: { error: { code: "not_found", message: "run x not found" } } });
    expect(await screen.findByText("Run not found")).toBeInTheDocument();
  });
});
