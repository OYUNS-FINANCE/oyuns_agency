/** Word-level text diff and a field-level comparison of two idea versions. */
import type { IdeaVersionView } from "@/lib/api/types";

export type DiffPart = { kind: "same" | "added" | "removed"; text: string };

function tokens(text: string): string[] {
  return text.split(/(\s+)/).filter((t) => t !== "");
}

/** LCS over words (whitespace kept as tokens), merged into runs of the same kind. */
export function diffWords(before: string, after: string): DiffPart[] {
  const a = tokens(before);
  const b = tokens(after);
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i]![j] =
        a[i] === b[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }
  const parts: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = parts.at(-1);
    if (last?.kind === kind) last.text += text;
    else parts.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("same", a[i]!);
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      push("removed", a[i++]!);
    } else {
      push("added", b[j++]!);
    }
  }
  while (i < a.length) push("removed", a[i++]!);
  while (j < b.length) push("added", b[j++]!);
  return parts;
}

export interface FieldChange {
  path: string;
  label: string;
  before: string | null;
  after: string | null;
}

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

const SECTION: Record<string, string> = {
  opportunity: "Idea",
  analysis: "Market",
  critique: "Scorecard",
};

function humanize(token: string): string {
  if (/^\d+$/.test(token)) return `#${Number(token) + 1}`;
  return token.replaceAll("_", " ");
}

/** List items that carry their own identity are labelled by it, not by position. */
function itemName(item: Json): string | null {
  if (item === null || typeof item !== "object" || Array.isArray(item)) return null;
  const name = item.dimension ?? item.name;
  return typeof name === "string" ? name : null;
}

/** Leaf values by JSON-pointer-like path, rendered as display strings; `labels` gets the
 *  readable label of each path segment (a rubric dimension instead of "#3"). */
function flatten(
  value: Json,
  path: string,
  labels: string[],
  out: Map<string, string>,
  names: Map<string, string[]>,
): void {
  if (value === null || typeof value !== "object") {
    if (value !== null) {
      out.set(path, String(value));
      names.set(path, labels);
    }
    return;
  }
  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i), v, itemName(v) ?? humanize(String(i))] as const)
    : Object.entries(value).map(([k, v]) => [k, v, humanize(k)] as const);
  for (const [key, child, label] of entries) {
    flatten(child, `${path}/${key}`, [...labels, label], out, names);
  }
}

/** Every leaf field that differs between two versions, in a stable reading order. */
export function compareVersions(before: IdeaVersionView, after: IdeaVersionView): FieldChange[] {
  const left = new Map<string, string>();
  const right = new Map<string, string>();
  const names = new Map<string, string[]>();
  for (const section of ["opportunity", "analysis", "critique"] as const) {
    const root = [SECTION[section] ?? section];
    flatten(before[section] as unknown as Json, `/${section}`, root, left, names);
    flatten(after[section] as unknown as Json, `/${section}`, root, right, names);
  }
  const paths = [...new Set([...left.keys(), ...right.keys()])];
  const order = new Map([...left.keys(), ...right.keys()].map((p, i) => [p, i]));
  return paths
    .filter((p) => left.get(p) !== right.get(p))
    .filter((p) => !p.endsWith("/opportunity_id") && !p.endsWith("/iteration"))
    .sort((x, y) => (order.get(x) ?? 0) - (order.get(y) ?? 0))
    .map((path) => ({
      path,
      label: (names.get(path) ?? [path]).map((n) => n.replaceAll("_", " ")).join(" › "),
      before: left.get(path) ?? null,
      after: right.get(path) ?? null,
    }));
}

/** "/opportunity/one_liner" → "Idea › one liner", for patch previews. */
export function pathLabel(pointer: string): string {
  const [section = "", ...rest] = pointer
    .slice(1)
    .split("/")
    .map((t) => t.replaceAll("~1", "/").replaceAll("~0", "~"));
  return [SECTION[section] ?? section, ...rest.map((t) => (t === "-" ? "new" : humanize(t)))].join(
    " › ",
  );
}
