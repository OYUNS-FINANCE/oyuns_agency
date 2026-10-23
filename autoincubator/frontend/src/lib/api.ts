import type { HealthResponse } from "@/lib/types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  const valid = (s: unknown): boolean => s === "ok" || s === "error";
  return valid(v.db) && valid(v.redis);
}

/** Health returns 503 with a valid body when a dependency is down, so read the body either way. */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/health", { signal, cache: "no-store" });
  const body: unknown = await response.json().catch(() => null);
  if (isHealthResponse(body)) return body;
  throw new ApiError(`Health check failed (HTTP ${response.status})`, response.status);
}
