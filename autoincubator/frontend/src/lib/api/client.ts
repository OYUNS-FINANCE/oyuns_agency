/** Thin fetch wrapper over the backend API. Every non-2xx becomes an `ApiError`. */
import type {
  CreateRunRequest,
  CreateRunResponse,
  ErrorBody,
  FounderProfile,
  HealthResponse,
  ProfileResponse,
  RunDetail,
  RunList,
} from "./types";

export const API_BASE = "/api/incubator";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = "http_error",
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

function isErrorBody(value: unknown): value is { error: ErrorBody } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as Record<string, unknown>).code === "string" &&
    typeof (error as Record<string, unknown>).message === "string"
  );
}

/** Builds an `ApiError` from a failed response, using the backend's error shape when present. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null);
  if (isErrorBody(body)) {
    return new ApiError(body.error.message, response.status, body.error.code, body.error.details);
  }
  return new ApiError(`Request failed (HTTP ${response.status})`, response.status);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      cache: "no-store",
      ...init,
      headers: { accept: "application/json", ...init.headers },
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError("The API is unreachable", 0, "network_error");
  }
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

function jsonBody(body: unknown): RequestInit {
  return { body: JSON.stringify(body), headers: { "content-type": "application/json" } };
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

export const api = {
  createRun: (body: CreateRunRequest) =>
    apiFetch<CreateRunResponse>(`${API_BASE}/runs`, { method: "POST", ...jsonBody(body) }),
  listRuns: (params: { limit: number; offset: number }, signal?: AbortSignal) =>
    apiFetch<RunList>(`${API_BASE}/runs?limit=${params.limit}&offset=${params.offset}`, {
      signal,
    }),
  getRun: (runId: string, signal?: AbortSignal) =>
    apiFetch<RunDetail>(`${API_BASE}/runs/${encodeURIComponent(runId)}`, { signal }),
  getProfile: (signal?: AbortSignal) =>
    apiFetch<ProfileResponse>(`${API_BASE}/profile`, { signal }),
  putProfile: (profile: FounderProfile) =>
    apiFetch<ProfileResponse>(`${API_BASE}/profile`, { method: "PUT", ...jsonBody(profile) }),
  streamUrl: (runId: string) => `${API_BASE}/runs/${encodeURIComponent(runId)}/stream`,
};
