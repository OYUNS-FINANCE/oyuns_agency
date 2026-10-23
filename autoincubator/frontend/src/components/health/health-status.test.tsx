import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthStatus } from "./health-status";

function renderWithClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HealthStatus />
    </QueryClientProvider>,
  );
}

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status }))),
  );
}

describe("HealthStatus", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows ok for every service when healthy", async () => {
    mockFetch(200, { db: "ok", redis: "ok" });
    renderWithClient();
    expect(await screen.findAllByText("ok")).toHaveLength(2);
  });

  it("shows the failing service on a 503", async () => {
    mockFetch(503, { db: "error", redis: "ok" });
    renderWithClient();
    expect(await screen.findByText("error")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("shows an error when the API is unreachable", async () => {
    mockFetch(502, { detail: "bad gateway" });
    renderWithClient();
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 502");
  });
});
