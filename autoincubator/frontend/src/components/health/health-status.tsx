"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchHealth } from "@/lib/api";
import type { CheckStatus } from "@/lib/types";

const SERVICES = [
  { key: "db", label: "Database" },
  { key: "redis", label: "Redis" },
] as const;

function StatusBadge({ status }: { status: CheckStatus }) {
  return status === "ok" ? (
    <Badge variant="secondary">
      <CircleCheck aria-hidden /> ok
    </Badge>
  ) : (
    <Badge variant="destructive">
      <CircleAlert aria-hidden /> error
    </Badge>
  );
}

export function HealthStatus() {
  const { data, error, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: 15_000,
  });

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>System health</CardTitle>
        <CardDescription>Backend dependencies, checked every 15 seconds.</CardDescription>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Checking…
          </p>
        ) : error ? (
          <p className="text-destructive flex items-center gap-2 text-sm" role="alert">
            <CircleAlert className="size-4" aria-hidden /> API unreachable: {error.message}
          </p>
        ) : (
          <ul className="space-y-2">
            {SERVICES.map(({ key, label }) => (
              <li key={key} className="flex items-center justify-between text-sm">
                <span>{label}</span>
                <StatusBadge status={data[key]} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
