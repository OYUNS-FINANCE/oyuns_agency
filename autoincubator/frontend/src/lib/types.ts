export type CheckStatus = "ok" | "error";

export interface HealthResponse {
  db: CheckStatus;
  redis: CheckStatus;
}
