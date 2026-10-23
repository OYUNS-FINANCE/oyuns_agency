import { History, Plus, UserRound, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: "/" | "/runs" | "/settings/profile";
  label: string;
  icon: LucideIcon;
  match: (pathname: string) => boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: "New run", icon: Plus, match: (p) => p === "/" },
  { href: "/runs", label: "Runs", icon: History, match: (p) => p.startsWith("/runs") },
  {
    href: "/settings/profile",
    label: "Profile",
    icon: UserRound,
    match: (p) => p.startsWith("/settings"),
  },
];
