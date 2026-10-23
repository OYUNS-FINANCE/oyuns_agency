/** Friendly aliases over the types generated from `backend/openapi.json` (`pnpm gen:api`). */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type HealthResponse = Schemas["HealthResponse"];
export type CheckStatus = HealthResponse["db"];

export type RunStatus = Schemas["RunStatus"];
export type RunMode = Schemas["RunSummary"]["mode"];
export type RunSummary = Schemas["RunSummary"];
export type RunList = Schemas["RunList"];
export type RunDetail = Schemas["RunDetail"];
export type BudgetUsage = Schemas["BudgetUsage"];
export type CreateRunRequest = Schemas["CreateRunRequest"];
export type CreateRunResponse = Schemas["CreateRunResponse"];
export type RunConstraints = Schemas["RunConstraints"];
export type BusinessModel = NonNullable<RunConstraints["business_model"]>;

export type IdeaView = Schemas["IdeaView"];
export type IdeaStatus = IdeaView["status"];
export type IdeaVersionSource = IdeaView["version_source"];
export type IdeaDetail = Schemas["IdeaDetail"];
export type IdeaVersionView = Schemas["IdeaVersionView"];
export type PatchOperation = Schemas["PatchOperation"];
export type SourcedFigure = IdeaView["analysis"]["sizing"]["tam"];

export type CoworkAgent = Schemas["CoworkRequest"]["agent"];
export type CoworkRequest = Schemas["CoworkRequest"];
export type CoworkMessage = Schemas["CoworkMessageView"];
export type CoworkMessageList = Schemas["CoworkMessageList"];
export type CoworkStarted = Schemas["CoworkStarted"];
export type CoworkDelta = Schemas["CoworkDelta"];
export type CoworkFailed = Schemas["CoworkFailed"];
export type JobAccepted = Schemas["JobAccepted"];
export type SelectResponse = Schemas["SelectResponse"];
export type RubricScore = Schemas["RubricScore"];
export type RubricDimension = RubricScore["dimension"];

export type FounderProfile = Schemas["FounderProfile"];
export type RiskTolerance = NonNullable<FounderProfile["risk_tolerance"]>;
export type ProfileResponse = Schemas["ProfileResponse"];

export type ErrorBody = Schemas["ErrorBody"];

/** One SSE event envelope, discriminated on `type`. */
export type RunEvent = Schemas["Event"];
export type RunEventType = RunEvent["type"];
export type EventOf<T extends RunEventType> = Extract<RunEvent, { type: T }>;

export const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "completed",
  "failed",
  "budget_exhausted",
]);

export function isTerminal(status: RunStatus | undefined): boolean {
  return status !== undefined && TERMINAL_STATUSES.has(status);
}
