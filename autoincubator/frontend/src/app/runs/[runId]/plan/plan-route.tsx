"use client";

import { use } from "react";

import { PlanView } from "@/components/plan/plan-view";

export function PlanRoute({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  return <PlanView key={runId} runId={runId} />;
}
