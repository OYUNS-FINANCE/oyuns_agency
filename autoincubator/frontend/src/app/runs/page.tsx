import type { Metadata } from "next";

import { RunHistory } from "@/components/runs/run-history";

export const metadata: Metadata = { title: "Runs" };

export default function RunsPage() {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <h1 className="font-serif text-3xl tracking-tight">Runs</h1>
      <RunHistory />
    </div>
  );
}
