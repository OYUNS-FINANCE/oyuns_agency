import type { Metadata } from "next";
import { Suspense } from "react";

import { PlanRoute } from "./plan-route";

export const metadata: Metadata = { title: "Business plan" };

export default function PlanPage({ params }: PageProps<"/runs/[runId]/plan">) {
  return (
    <Suspense>
      <PlanRoute params={params} />
    </Suspense>
  );
}
