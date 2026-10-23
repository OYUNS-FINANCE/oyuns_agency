import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { afterEach, vi } from "vitest";

// The App Router keeps `useSearchParams` in sync with history.pushState/replaceState. Tests
// have no router, so mirror that: patch both methods to notify, and read window.location.
// Node-environment test files (`@vitest-environment node`) have no window.
const browser = typeof window !== "undefined";
const listeners = new Set<() => void>();
for (const method of browser ? (["pushState", "replaceState"] as const) : []) {
  const original = window.history[method].bind(window.history);
  window.history[method] = (...args: Parameters<History["pushState"]>) => {
    original(...args);
    for (const listener of listeners) listener();
  };
}

vi.mock("next/navigation", () => ({
  useSearchParams: () =>
    new URLSearchParams(
      useSyncExternalStore(
        (listener) => {
          listeners.add(listener);
          window.addEventListener("popstate", listener);
          return () => {
            listeners.delete(listener);
            window.removeEventListener("popstate", listener);
          };
        },
        () => window.location.search,
      ),
    ),
  usePathname: () => window.location.pathname,
}));

afterEach(() => {
  cleanup();
  if (browser) window.history.replaceState(null, "", "/");
});
