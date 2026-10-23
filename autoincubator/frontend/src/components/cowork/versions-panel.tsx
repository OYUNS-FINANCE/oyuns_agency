"use client";

import { useState } from "react";

import type { IdeaVersionView } from "@/lib/api/types";
import { VERSION_SOURCE_LABEL } from "@/lib/cowork";
import { compareVersions, diffWords, type DiffPart } from "@/lib/diff";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

function Parts({ parts, side }: { parts: DiffPart[]; side: "before" | "after" }) {
  return (
    <>
      {parts.map((part, i) => {
        if (part.kind === "same") return <span key={i}>{part.text}</span>;
        if (side === "before" && part.kind === "removed") {
          return (
            <del key={i} className="bg-destructive/15 text-destructive rounded-sm no-underline">
              {part.text}
            </del>
          );
        }
        if (side === "after" && part.kind === "added") {
          return (
            <ins key={i} className="bg-signal-soft text-signal rounded-sm no-underline">
              {part.text}
            </ins>
          );
        }
        return null;
      })}
    </>
  );
}

function VersionChip({
  version,
  active,
  onClick,
  label,
}: {
  version: IdeaVersionView;
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={`${label}: version ${version.version}`}
      className={cn(
        "focus-visible:ring-ring/50 rounded-md border px-2 py-1 font-mono text-xs outline-none focus-visible:ring-3",
        active ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted",
      )}
    >
      v{version.version}
    </button>
  );
}

export function VersionsPanel({ versions }: { versions: IdeaVersionView[] }) {
  const latest = versions.at(-1);
  const [picked, setPicked] = useState<{ from: number; to: number } | null>(null);
  if (!latest) return null;
  // Default: the latest version against its predecessor.
  const to = picked?.to ?? latest.version;
  const from = picked?.from ?? Math.max(1, to - 1);
  const before = versions.find((v) => v.version === from) ?? versions[0]!;
  const after = versions.find((v) => v.version === to) ?? latest;
  const changes = before === after ? [] : compareVersions(before, after);

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto px-4 py-4 sm:px-5">
      <ol className="flex flex-col divide-y rounded-lg border" aria-label="Versions">
        {[...versions].reverse().map((v) => (
          <li
            key={v.version}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm"
          >
            <span className="w-8 font-mono">v{v.version}</span>
            <span>{VERSION_SOURCE_LABEL[v.source]}</span>
            <span className="tabular text-muted-foreground font-mono text-xs">
              score {v.composite_score.toFixed(1)}
            </span>
            <time className="text-muted-foreground ml-auto text-xs" dateTime={v.created_at}>
              {formatDateTime(v.created_at)}
            </time>
          </li>
        ))}
      </ol>

      {versions.length < 2 ? (
        <p className="text-muted-foreground text-sm">
          Only the discovered version exists. Apply a change from the chat to create version 2.
        </p>
      ) : (
        <section aria-label="Compare versions" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
            {(["from", "to"] as const).map((side) => (
              <div key={side} className="flex flex-wrap items-center gap-1.5">
                <span className="text-muted-foreground w-9">{side === "from" ? "From" : "To"}</span>
                {versions.map((v) => (
                  <VersionChip
                    key={v.version}
                    version={v}
                    label={side === "from" ? "Compare from" : "Compare to"}
                    active={(side === "from" ? from : to) === v.version}
                    onClick={() =>
                      setPicked({ from, to, [side]: v.version } as { from: number; to: number })
                    }
                  />
                ))}
              </div>
            ))}
          </div>
          {changes.length === 0 ? (
            <p className="text-muted-foreground text-sm">No differences.</p>
          ) : (
            <table className="w-full table-fixed border-collapse text-sm">
              <caption className="sr-only">
                Changes from version {before.version} to version {after.version}
              </caption>
              <thead className="text-muted-foreground text-left text-xs">
                <tr>
                  <th className="hidden w-1/4 pb-2 font-normal sm:table-cell">Field</th>
                  <th className="pb-2 font-normal">v{before.version}</th>
                  <th className="pb-2 pl-3 font-normal">v{after.version}</th>
                </tr>
              </thead>
              <tbody>
                {changes.map((c) => {
                  const parts = diffWords(c.before ?? "", c.after ?? "");
                  return (
                    <tr key={c.path} className="border-t align-top" data-path={c.path}>
                      <th
                        scope="row"
                        className="text-muted-foreground hidden py-2 pr-3 text-left text-xs font-normal sm:table-cell"
                      >
                        {c.label}
                      </th>
                      <td className="py-2 break-words">
                        <span className="text-muted-foreground mb-1 block text-xs sm:hidden">
                          {c.label}
                        </span>
                        {c.before === null ? (
                          <span className="text-muted-foreground italic">absent</span>
                        ) : (
                          <Parts parts={parts} side="before" />
                        )}
                      </td>
                      <td className="border-l py-2 pl-3 break-words">
                        <span className="mb-1 block text-xs sm:hidden">&nbsp;</span>
                        {c.after === null ? (
                          <span className="text-muted-foreground italic">removed</span>
                        ) : (
                          <Parts parts={parts} side="after" />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}
