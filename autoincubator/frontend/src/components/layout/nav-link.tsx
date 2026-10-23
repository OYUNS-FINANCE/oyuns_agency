import Link from "next/link";

import { cn } from "@/lib/utils";

import type { NavItem } from "./nav-items";

export function NavLink({ item, active = false }: { item: NavItem; active?: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      aria-label={item.label}
      className={cn(
        "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 transition-colors",
        active ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="size-4 sm:hidden" aria-hidden />
      <span className="hidden sm:inline">{item.label}</span>
    </Link>
  );
}
