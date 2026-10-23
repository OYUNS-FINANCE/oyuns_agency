import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthDot } from "./health-dot";

function renderWithClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HealthDot />
    </QueryClientProvider>,
  );
}

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status }))),
  );
}

describe("HealthDot", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is healthy when every dependency is ok", async () => {
    mockFetch(200, { db: "ok", redis: "ok" });
    renderWithClient();
    expect(await screen.findByRole("img", { name: "API healthy" })).toBeInTheDocument();
  });

  it("names the failing dependency on a 503", async () => {
    mockFetch(503, { db: "ok", redis: "error" });
    renderWithClient();
    expect(await screen.findByRole("img", { name: /degraded.*Redis error/ })).toBeInTheDocument();
  });

  it("is unreachable when the API returns garbage", async () => {
    mockFetch(502, { detail: "bad gateway" });
    renderWithClient();
    expect(await screen.findByRole("img", { name: "API unreachable" })).toBeInTheDocument();
  });
});
