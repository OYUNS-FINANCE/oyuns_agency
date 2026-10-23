import { HealthStatus } from "@/components/health/health-status";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-4 py-16">
      <div className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight">AutoIncubator</h1>
        <p className="text-muted-foreground mt-2">
          Discover, stress-test and co-develop business ideas.
        </p>
      </div>
      <HealthStatus />
    </main>
  );
}
