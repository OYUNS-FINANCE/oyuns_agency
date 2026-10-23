"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { EMPTY_EVENT_STORE, type RunEventStore } from "@/lib/run-events";

import { ApiError, api } from "./client";
import {
  isTerminal,
  type CoworkMessageList,
  type CreateRunRequest,
  type FounderProfile,
} from "./types";

export const queryKeys = {
  runs: ["runs"] as const,
  runList: (limit: number, offset: number) => ["runs", "list", { limit, offset }] as const,
  run: (runId: string) => ["runs", "detail", runId] as const,
  runEvents: (runId: string) => ["runs", "events", runId] as const,
  ideas: (runId: string) => ["runs", "ideas", runId] as const,
  idea: (runId: string, ideaId: string) => ["runs", "ideas", runId, ideaId] as const,
  messages: (runId: string, ideaId: string) => ["runs", "ideas", runId, ideaId, "cowork"] as const,
  plan: (runId: string) => ["runs", "plan", runId] as const,
  profile: ["profile"] as const,
};

/** Retry transient failures only; a 4xx (bad id, missing run) will not change on retry. */
function retryTransient(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: queryKeys.run(runId),
    queryFn: ({ signal }) => api.getRun(runId, signal),
    retry: retryTransient,
    // Token/search counters and cost only reach the client through this endpoint (events
    // carry them only at 80% and 100%), so poll gently while the run is working.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 5_000 : false;
    },
  });
}

export function getEventStore(client: QueryClient, runId: string): RunEventStore {
  return client.getQueryData<RunEventStore>(queryKeys.runEvents(runId)) ?? EMPTY_EVENT_STORE;
}

/**
 * The run's event log. `useRunStream` is its only writer (via `setQueryData`); the query
 * function just returns what is cached, so a refetch can never wipe streamed events.
 */
export function useRunEvents(runId: string): RunEventStore {
  const client = useQueryClient();
  const { data } = useQuery({
    queryKey: queryKeys.runEvents(runId),
    queryFn: () => getEventStore(client, runId),
    staleTime: Infinity,
    gcTime: 30 * 60_000,
  });
  return data ?? EMPTY_EVENT_STORE;
}

/** The run's business plan; only fetched once the run has completed (404 before). */
export function usePlan(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.plan(runId),
    queryFn: ({ signal }) => api.getPlan(runId, signal),
    enabled,
    retry: retryTransient,
    staleTime: Infinity,
  });
}

export function useRunList(limit: number, offset: number) {
  return useQuery({
    queryKey: queryKeys.runList(limit, offset),
    queryFn: ({ signal }) => api.listRuns({ limit, offset }, signal),
    retry: retryTransient,
    // Keep badges fresh while anything on the page is still moving.
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => !isTerminal(r.status) && r.status !== "awaiting_human")
        ? 4_000
        : false,
  });
}

export function useCreateRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateRunRequest) => api.createRun(body),
    onSuccess: () => client.invalidateQueries({ queryKey: [...queryKeys.runs, "list"] }),
  });
}

export function useProfile() {
  return useQuery({
    queryKey: queryKeys.profile,
    queryFn: ({ signal }) => api.getProfile(signal),
    retry: retryTransient,
  });
}

export function useSaveProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (profile: FounderProfile) => api.putProfile(profile),
    onSuccess: (saved) => client.setQueryData(queryKeys.profile, saved),
  });
}

// --- Co-working (ADR 0006) --------------------------------------------------------------

export function useIdea(runId: string, ideaId: string | null) {
  return useQuery({
    queryKey: queryKeys.idea(runId, ideaId ?? ""),
    queryFn: ({ signal }) => api.getIdea(runId, ideaId ?? "", signal),
    enabled: ideaId !== null,
    retry: retryTransient,
  });
}

export function useCoworkMessages(runId: string, ideaId: string | null) {
  return useQuery({
    queryKey: queryKeys.messages(runId, ideaId ?? ""),
    queryFn: ({ signal }) => api.listMessages(runId, ideaId ?? "", signal),
    enabled: ideaId !== null,
    retry: retryTransient,
    // A reply generated for another tab (or before a reload) has no stream here: poll
    // until it is stored.
    refetchInterval: (query) =>
      query.state.data?.items.some((m) => m.state === "pending") ? 2_000 : false,
  });
}

/** Refreshes the run detail (cards) and the open idea after a co-working write. */
function invalidateIdeas(client: QueryClient, runId: string) {
  void client.invalidateQueries({ queryKey: queryKeys.run(runId) });
  void client.invalidateQueries({ queryKey: queryKeys.ideas(runId) });
}

export function useApplyVersion(runId: string, ideaId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (messageId: string) => api.applyVersion(runId, ideaId, messageId),
    onSettled: () => invalidateIdeas(client, runId),
  });
}

export function useRescore(runId: string) {
  return useMutation({ mutationFn: (ideaId: string) => api.rescore(runId, ideaId) });
}

export function useReject(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ ideaId, reason }: { ideaId: string; reason: string | null }) =>
      api.reject(runId, ideaId, reason),
    onSettled: () => invalidateIdeas(client, runId),
  });
}

export function useMerge(runId: string) {
  return useMutation({ mutationFn: (ideaIds: readonly string[]) => api.merge(runId, ideaIds) });
}

export function useSelectIdea(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ideaId: string) => api.select(runId, ideaId),
    onSettled: () => invalidateIdeas(client, runId),
  });
}

export function setMessages(
  client: QueryClient,
  runId: string,
  ideaId: string,
  update: (items: CoworkMessageList["items"]) => CoworkMessageList["items"],
) {
  client.setQueryData<CoworkMessageList>(queryKeys.messages(runId, ideaId), (list) => ({
    items: update(list?.items ?? []),
  }));
}
