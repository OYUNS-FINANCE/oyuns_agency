import { ApiError } from "@/lib/api/client";

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat("en");
const usd = new Intl.NumberFormat("en", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});
// Per-agent costs are often fractions of a cent.
const usdFine = new Intl.NumberFormat("en", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});
const clock = new Intl.DateTimeFormat("en", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });
const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export const formatCompact = (n: number) => compact.format(n);
export const formatInteger = (n: number) => integer.format(n);
export const formatUsd = (n: number) => usd.format(n);
export const formatUsdFine = (n: number) => usdFine.format(n);
export const formatClock = (iso: string) => clock.format(new Date(iso));
export const formatDateTime = (iso: string) => dateTime.format(new Date(iso));

export function formatDuration(ms: number): string {
  if (ms < 1_000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  return `${minutes}m ${Math.round((ms % 60_000) / 1_000)}s`;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400_000],
  ["hour", 3_600_000],
  ["minute", 60_000],
];

export function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = new Date(iso).getTime() - now;
  for (const [unit, size] of UNITS) {
    if (Math.abs(diff) >= size) return relative.format(Math.round(diff / size), unit);
  }
  return "just now";
}

/** `{value, unit}` figures from the Analyst, e.g. "$4.2B" or "120K users". */
export function formatFigure(value: number, unit: string): string {
  if (unit.toUpperCase().startsWith("USD")) {
    const rest = unit.slice(3);
    return `$${compact.format(value)}${rest}`;
  }
  return `${compact.format(value)} ${unit}`;
}

/** A readable message for any error, including the field list of a 422. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "validation_error" && Array.isArray(error.details)) {
      const fields = error.details
        .map((d: unknown) => {
          if (typeof d !== "object" || d === null) return null;
          const { loc, msg } = d as { loc?: unknown; msg?: unknown };
          const path = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
          return typeof msg === "string" ? (path ? `${path}: ${msg}` : msg) : null;
        })
        .filter((s): s is string => s !== null);
      if (fields.length > 0) return fields.join("; ");
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong";
}
