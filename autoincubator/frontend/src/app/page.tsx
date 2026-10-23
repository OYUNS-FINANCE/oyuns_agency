import Link from "next/link";

import { RunHistory } from "@/components/runs/run-history";
import { StartRunForm } from "@/components/runs/start-run-form";

export default function Home() {
  return (
    <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <section className="flex max-w-2xl flex-col gap-8">
        <header className="flex flex-col gap-3">
          <h1 className="font-serif text-4xl leading-[1.05] tracking-tight sm:text-5xl">
            Find a business worth building.
          </h1>
          <p className="text-muted-foreground max-w-xl">
            A Scout looks for real demand signals, an Analyst sizes the market with cited figures,
            and a Devil&apos;s Advocate tries to kill every idea. You get the survivors, ranked.
          </p>
        </header>
        <StartRunForm />
      </section>
      <aside className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-muted-foreground text-xs font-medium tracking-wider uppercase">
            Recent runs
          </h2>
          <Link href="/runs" className="text-muted-foreground hover:text-foreground text-xs">
            All runs
          </Link>
        </div>
        <RunHistory pageSize={5} compact />
      </aside>
    </div>
  );
}
