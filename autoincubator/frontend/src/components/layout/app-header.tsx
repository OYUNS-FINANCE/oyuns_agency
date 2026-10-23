import Link from "next/link";
import { Suspense } from "react";

import { HealthDot } from "@/components/health/health-dot";

import { NavLink } from "./nav-link";
import { NAV_ITEMS } from "./nav-items";
import { NavLinks } from "./nav-links";

export function AppHeader() {
  return (
    <header className="bg-background/85 sticky top-0 z-20 border-b backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4">
        <Link href="/" className="font-serif text-xl leading-none">
          AutoIncubator
        </Link>
        <nav aria-label="Main" className="ml-auto flex items-center gap-0.5 text-sm">
          {/* usePathname suspends under dynamic params, so give it a static fallback. */}
          <Suspense
            fallback={NAV_ITEMS.map((item) => (
              <NavLink key={item.href} item={item} />
            ))}
          >
            <NavLinks />
          </Suspense>
        </nav>
        <HealthDot />
      </div>
    </header>
  );
}
