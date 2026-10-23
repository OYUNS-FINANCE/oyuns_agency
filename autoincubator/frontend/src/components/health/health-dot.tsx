"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/** A small API health light: Postgres and Redis behind the API, checked every 30 seconds. */
export function HealthDot() {
  const { data, error, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: 30_000,
    retry: false,
  });

  const state = isPending
    ? "checking"
    : error
      ? "unreachable"
      : data.db === "ok" && data.redis === "ok"
        ? "ok"
        : "degraded";
  const label = {
    checking: "Checking API health",
    ok: "API healthy",
    degraded: `API degraded (database ${data?.db ?? "?"}, Redis ${data?.redis ?? "?"})`,
    unreachable: "API unreachable",
  }[state];

  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      data-state={state}
      className="flex size-5 items-center justify-center"
    >
      <span
        className={cn(
          "size-2 rounded-full",
          state === "ok" && "bg-signal",
          state === "checking" && "bg-muted-foreground/40 animate-pulse",
          state === "degraded" && "bg-warning",
          state === "unreachable" && "bg-destructive",
        )}
      />
    </span>
  );
}
