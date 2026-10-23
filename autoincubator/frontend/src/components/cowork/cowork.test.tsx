import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunView } from "@/components/runs/run-view";
import type { CoworkMessage, IdeaView } from "@/lib/api/types";
import {
  IDEA_ID,
  RUN_ID,
  idea,
  jsonResponse,
  message,
  namedSse,
  routeFetch,
  runDetail,
  sse,
  statusEvent,
  streamResponse,
  version,
} from "@/test/fixtures";

const SECOND_ID = "44444444-4444-4444-8444-444444444444";
const first = idea();
const second = idea({ id: SECOND_ID, key: "opp-02", rank: 2, title: "Shift swaps for clinics" });
const edited: IdeaView = {
  ...first,
  version: 2,
  version_source: "cowork",
  score_stale: true,
  opportunity: { ...first.opportunity, one_liner: "Reconciled ledgers for café chains." },
};

function setup({ messages = [] as CoworkMessage[] } = {}) {
  const state = {
    messages,
    detail: runDetail({ status: "awaiting_human", ideas: [first, second] }),
  };
  const routes = routeFetch({
    [`GET /runs/${RUN_ID}`]: () => jsonResponse(state.detail),
    "GET /stream": () => streamResponse([sse([statusEvent(1, "awaiting_human")])]),
    [`GET /ideas/${IDEA_ID}`]: () =>
      jsonResponse({
        idea: state.detail.ideas[0],
        versions: [version(1), version(2, { opportunity: edited.opportunity })],
      }),
    [`GET /ideas/${IDEA_ID}/cowork`]: () => jsonResponse({ items: state.messages }),
    [`POST /ideas/${IDEA_ID}/cowork`]: () => {
      const user = message({ id: "u-1", role: "user", content: "Focus on chains" });
      const pending = message({ id: "a-1", state: "pending", content: "" });
      const done = message({
        id: "a-1",
        content: "Chains have more receipts.",
        proposed_patch: [
          { op: "replace", path: "/opportunity/one_liner", value: edited.opportunity.one_liner },
        ],
      });
      state.messages = [user, done];
      const body = namedSse([
        { event: "started", data: { user_message: user, assistant_message: pending } },
        { event: "delta", data: { text: "Chains have " } },
        { event: "delta", data: { text: "more receipts." } },
        { event: "completed", data: done },
      ]);
      return streamResponse([body]);
    },
    [`POST /ideas/${IDEA_ID}/versions`]: () => {
      state.messages = state.messages.map((m) =>
        m.id === "a-1" ? { ...m, applied_version: 2 } : m,
      );
      state.detail = { ...state.detail, ideas: [edited, second] };
      return jsonResponse(edited, 201);
    },
    "POST /select": async () => {
      await new Promise((r) => setTimeout(r, 20));
      return jsonResponse({ run_id: RUN_ID, status: "running", selected_idea_id: IDEA_ID }, 202);
    },
    "POST /ideas/merge": () => jsonResponse({ job_id: "merge:1" }, 202),
    [`POST /ideas/${IDEA_ID}/reject`]: () =>
      jsonResponse({ ...first, status: "rejected", rank: null }),
  });
  vi.stubGlobal("fetch", routes.fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RunView runId={RUN_ID} />
    </QueryClientProvider>,
  );
  return routes;
}

const posts = (calls: { method: string; url: string; body: unknown }[], suffix: string) =>
  calls.filter((c) => c.method === "POST" && c.url.endsWith(suffix));

describe("co-working", () => {
  beforeEach(() => window.history.replaceState(null, "", `/runs/${RUN_ID}`));
  afterEach(() => vi.unstubAllGlobals());

  it("restores the drawer, tab and diff from the URL after a reload", async () => {
    window.history.replaceState(null, "", `/runs/${RUN_ID}?idea=${IDEA_ID}&tab=versions`);
    setup();
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByRole("heading", { name: first.title })).toBeInTheDocument();
    expect(within(drawer).getByRole("tab", { name: /Versions/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const table = await within(drawer).findByRole("table", { name: /version 1 to version 2/ });
    const row = table.querySelector('[data-path="/opportunity/one_liner"]');
    expect(row).toHaveTextContent("Idea › one liner");
    const added = [...(row?.querySelectorAll("ins") ?? [])].map((n) => n.textContent).join("|");
    expect(added).toContain("Reconciled");
    expect(added).toContain("chains.");
    expect(row?.querySelector("del")).toHaveTextContent("Photograph");
  });

  it("opens from a card, streams a reply and applies the proposed change", async () => {
    const { calls } = setup();
    fireEvent.click(
      within(await screen.findByRole("article", { name: first.title })).getByRole("button", {
        name: "Co-work",
      }),
    );
    await waitFor(() => expect(window.location.search).toBe(`?idea=${IDEA_ID}&tab=chat`));
    const drawer = await screen.findByRole("dialog");
    const box = within(drawer).getByRole("textbox", { name: /Message to the Market Analyst/ });
    fireEvent.change(box, { target: { value: "Focus on chains" } });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(await within(drawer).findByText("Chains have more receipts.")).toBeInTheDocument();
    expect(posts(calls, "/cowork")[0]?.body).toEqual({
      agent: "analyst",
      content: "Focus on chains",
    });
    fireEvent.click(within(drawer).getByRole("button", { name: "Apply change" }));

    expect(await within(drawer).findByText("Applied as v2")).toBeInTheDocument();
    expect(posts(calls, "/versions")[0]?.body).toEqual({ message_id: "a-1" });
    // The card (behind the modal drawer) shows that its score is now out of date.
    const card = await screen.findByRole("article", { name: first.title, hidden: true });
    await waitFor(() => expect(card.querySelector('[data-badge="stale"]')).not.toBeNull());
  });

  it("resumes exactly once when the confirm button is clicked twice", async () => {
    window.history.replaceState(null, "", `/runs/${RUN_ID}?idea=${IDEA_ID}`);
    const { calls } = setup();
    const drawer = await screen.findByRole("dialog");
    fireEvent.click(within(drawer).getByRole("button", { name: /Develop full business plan/ }));
    const confirm = await screen.findByRole("button", { name: "Develop business plan" });
    act(() => {
      fireEvent.click(confirm);
      fireEvent.click(confirm);
    });
    await waitFor(() => expect(window.location.search).toBe(""));
    expect(posts(calls, "/select")).toHaveLength(1);
    expect(posts(calls, "/select")[0]?.body).toEqual({ idea_id: IDEA_ID });
  });

  it("merges two selected ideas after confirmation", async () => {
    const { calls } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Merge ideas" }));
    fireEvent.click(screen.getByRole("checkbox", { name: `Select “${first.title}” for merging` }));
    fireEvent.click(screen.getByRole("checkbox", { name: `Select “${second.title}” for merging` }));
    fireEvent.click(screen.getByRole("button", { name: "Merge 2" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(second.title)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(posts(calls, "/ideas/merge")).toHaveLength(1));
    expect(posts(calls, "/ideas/merge")[0]?.body).toEqual({ idea_ids: [IDEA_ID, SECOND_ID] });
  });

  it("rejects with a reason", async () => {
    window.history.replaceState(null, "", `/runs/${RUN_ID}?idea=${IDEA_ID}&tab=scorecard`);
    const { calls } = setup();
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Defensibility")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.change(within(dialog).getByLabelText("Reason (optional)"), {
      target: { value: "needs a sales team" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject idea" }));
    await waitFor(() => expect(posts(calls, "/reject")).toHaveLength(1));
    expect(posts(calls, "/reject")[0]?.body).toEqual({ reason: "needs a sales team" });
  });

  it("keeps the drawer read-only once the run is no longer paused", async () => {
    window.history.replaceState(null, "", `/runs/${RUN_ID}?idea=${IDEA_ID}`);
    const routes = routeFetch({
      [`GET /runs/${RUN_ID}`]: () =>
        jsonResponse(
          runDetail({
            status: "completed",
            selected_idea_id: IDEA_ID,
            ideas: [{ ...first, status: "selected" }],
          }),
        ),
      "GET /stream": () => streamResponse([sse([statusEvent(1, "completed")])]),
      [`GET /ideas/${IDEA_ID}`]: () =>
        jsonResponse({ idea: { ...first, status: "selected" }, versions: [version(1)] }),
      [`GET /ideas/${IDEA_ID}/cowork`]: () => jsonResponse({ items: [] }),
    });
    vi.stubGlobal("fetch", routes.fetch);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RunView runId={RUN_ID} />
      </QueryClientProvider>,
    );
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Selected for the business plan")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Develop/ })).toBeNull();
    expect(within(drawer).getByRole("textbox")).toBeDisabled();
    expect(await screen.findByText(/Run complete/)).toBeInTheDocument();
  });
});
