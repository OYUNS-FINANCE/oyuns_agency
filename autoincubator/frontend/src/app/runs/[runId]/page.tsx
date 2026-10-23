import type { Metadata } from "next";
import { Suspense } from "react";

import { RunRoute } from "./run-route";

export const metadata: Metadata = { title: "Run" };

export default function RunPage({ params }: PageProps<"/runs/[runId]">) {
  // The run id is only known at request time, so the client part sits behind Suspense.
  return (
    <Suspense>
      <RunRoute params={params} />
    </Suspense>
  );
}
