# 0001 — Phase 0 version pins and same-origin API proxy
Date: 2026-10-23    Status: accepted

## Context
Phase 0 pins every dependency against current releases. A few "latest" versions are incompatible
with other parts of the stack. The frontend also needs to call the FastAPI backend from the browser.

## Options considered
1. Take latest of everything. Breaks: arq 0.28 requires `redis<6` (latest 8.1); typescript-eslint
   8.72 supports TypeScript `<6.1` (latest 7.0); SQLAlchemy 2.1 contradicts "SQLAlchemy 2.0" in CLAUDE.md.
2. Pin the newest compatible versions — redis 5.3.1, TypeScript 6.0.3, SQLAlchemy 2.0.55.
3. Browser calls the API directly on :8000 with CORS enabled.
4. Next.js `rewrites()` proxies `/api/*` to `BACKEND_URL`; the browser stays same-origin.

## Decision
Option 2 for versions. Option 4 for the API: no CORS config, one origin for cookies once auth
lands, and the backend URL is a server-side env var only.

## Consequences
- Revisit the pins when arq lifts its redis cap, typescript-eslint supports TS 7, or we choose to
  move to SQLAlchemy 2.1 (that needs its own ADR).
- **Phase 2/3 must verify SSE through the rewrite proxy** (no buffering, `Last-Event-ID` forwarded).
  If the proxy buffers, the SSE route will go direct to the API with CORS, recorded in a new ADR.
