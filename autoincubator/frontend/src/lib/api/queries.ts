"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { EMPTY_EVENT_STORE, type RunEventStore } from "@/lib/run-events";

import { ApiError, api } from "./client";
import { isTerminal, type CreateRunRequest, type FounderProfile } from "./types";

export const queryKeys = {
  runs: ["runs"] as const,
  runList: (limit: number, offset: number) => ["runs", "list", { limit, offset }] as const,
  run: (runId: string) => ["runs", "detail", runId] as const,
  runEvents: (runId: string) => ["runs", "events", runId] as const,
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
