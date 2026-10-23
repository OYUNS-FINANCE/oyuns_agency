"use client";

import { use } from "react";

import { RunView } from "@/components/runs/run-view";

export function RunRoute({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  // Keyed so that moving between runs starts from a clean view and stream.
  return <RunView key={runId} runId={runId} />;
}
