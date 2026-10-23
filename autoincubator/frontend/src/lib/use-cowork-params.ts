"use client";

import { useSearchParams } from "next/navigation";
import { useCallback } from "react";

import type { CoworkAgent } from "@/lib/api/types";

export type CoworkTab = "chat" | "versions" | "scorecard";

const TABS: readonly CoworkTab[] = ["chat", "versions", "scorecard"];
const AGENTS: readonly CoworkAgent[] = ["scout", "analyst", "skeptic"];

export interface CoworkParams {
  ideaId: string | null;
  tab: CoworkTab;
  agent: CoworkAgent;
}

export function parseCoworkParams(params: URLSearchParams): CoworkParams {
  const tab = params.get("tab");
  const agent = params.get("agent");
  return {
    ideaId: params.get("idea"),
    tab: TABS.includes(tab as CoworkTab) ? (tab as CoworkTab) : "chat",
    agent: AGENTS.includes(agent as CoworkAgent) ? (agent as CoworkAgent) : "analyst",
  };
}

/**
 * The co-working drawer's state lives in the URL (`?idea=…&tab=…&agent=…`), so a reload
 * reopens the same idea, tab and agent; the content itself is re-read from the server.
 * Opening pushes a history entry (Back closes the drawer); tab and agent changes replace it.
 */
export function useCoworkParams() {
  const search = useSearchParams();
  const current = parseCoworkParams(new URLSearchParams(search.toString()));

  const write = useCallback(
    (next: Partial<Record<"idea" | "tab" | "agent", string | null>>, push = false) => {
      const params = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(next)) {
        if (value === null) params.delete(key);
        else params.set(key, value);
      }
      const query = params.toString();
      const url = `${window.location.pathname}${query ? `?${query}` : ""}`;
      if (push) window.history.pushState(null, "", url);
      else window.history.replaceState(null, "", url);
    },
    [],
  );

  return {
    ...current,
    open: useCallback(
      (ideaId: string, tab: CoworkTab = "chat") => write({ idea: ideaId, tab }, true),
      [write],
    ),
    close: useCallback(() => write({ idea: null, tab: null, agent: null }), [write]),
    setTab: useCallback((tab: CoworkTab) => write({ tab }), [write]),
    setAgent: useCallback((agent: CoworkAgent) => write({ agent }), [write]),
  };
}
