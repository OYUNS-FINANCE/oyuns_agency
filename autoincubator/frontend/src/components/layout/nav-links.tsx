"use client";

import { usePathname } from "next/navigation";

import { NavLink } from "./nav-link";
import { NAV_ITEMS } from "./nav-items";

export function NavLinks() {
  const pathname = usePathname();
  return NAV_ITEMS.map((item) => (
    <NavLink key={item.href} item={item} active={item.match(pathname)} />
  ));
}
