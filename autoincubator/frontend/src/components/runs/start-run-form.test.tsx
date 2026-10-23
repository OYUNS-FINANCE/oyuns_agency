import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RUN_ID, jsonResponse } from "@/test/fixtures";

import { StartRunForm, toCreateRunRequest, type StartRunValues } from "./start-run-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const base: StartRunValues = {
  mode: "seeded",
  seed: "  Bookkeeping for cafés  ",
  region: "",
  budgetCeiling: "",
  businessModel: "any",
  soloFounder: false,
  excludedIndustries: [],
};

describe("toCreateRunRequest", () => {
  it("builds a seeded request with trimmed seed and empty constraints as null", () => {
    expect(toCreateRunRequest(base)).toEqual({
      ok: true,
      body: {
        mode: "seeded",
        seed: "Bookkeeping for cafés",
        constraints: {
          region: null,
          budget_ceiling_usd: null,
          business_model: "any",
          solo_founder: false,
          excluded_industries: [],
        },
      },
    });
  });

  it("drops the seed for autonomous runs", () => {
    const result = toCreateRunRequest({ ...base, mode: "autonomous", seed: "ignored" });
    expect(result.ok && result.body.seed).toBeNull();
  });

  it("rejects a too-short seed and a bad budget", () => {
    expect(toCreateRunRequest({ ...base, seed: "ab" })).toMatchObject({ ok: false, field: "seed" });
    expect(toCreateRunRequest({ ...base, budgetCeiling: "-5" })).toMatchObject({
      ok: false,
      field: "budget",
    });
  });
});

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StartRunForm />
    </QueryClientProvider>,
  );
}

describe("StartRunForm", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    push.mockReset();
  });

  it("shows a field error instead of submitting an empty seed", () => {
    const fetchMock = vi.fn<(url: string) => Promise<Response>>(() =>
      Promise.resolve(jsonResponse({ profile: {}, updated_at: null })),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderForm();
    fireEvent.click(screen.getByRole("button", { name: /discover & incubate/i }));
    expect(screen.getByText(/at least 3 characters/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/runs"))).toBe(false);
  });

  it("starts an autonomous run and opens it", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) =>
      Promise.resolve(
        init?.method === "POST"
          ? jsonResponse({ run_id: RUN_ID, status: "queued" }, 202)
          : jsonResponse({ profile: {}, updated_at: null }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderForm();
    fireEvent.click(screen.getByLabelText(/scan for opportunities/i));
    fireEvent.click(screen.getByRole("button", { name: /discover & incubate/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ mode: "autonomous", seed: null });
  });

  it("shows the server's validation message when the API rejects the run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) =>
        Promise.resolve(
          init?.method === "POST"
            ? jsonResponse(
                {
                  error: {
                    code: "validation_error",
                    message: "Invalid request",
                    details: [
                      { loc: ["body", "seed"], msg: "String should have at most 500 characters" },
                    ],
                  },
                },
                422,
              )
            : jsonResponse({ profile: {}, updated_at: null }),
        ),
      ),
    );
    renderForm();
    fireEvent.change(screen.getByLabelText(/your seed idea/i), {
      target: { value: "A fine idea" },
    });
    fireEvent.click(screen.getByRole("button", { name: /discover & incubate/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "seed: String should have at most 500",
    );
  });
});
