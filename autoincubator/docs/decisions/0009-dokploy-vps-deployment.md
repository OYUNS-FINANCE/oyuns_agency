# 0009 — Deployment: one VPS, Dokploy, basic auth at the proxy
Date: 2026-10-26    Status: accepted

## Context
Phase 7 needs a public URL behind auth, backups, a repeatable deploy and working SSE. One
founder runs it; the traffic is one user. Five processes: Postgres, Redis, API, worker, frontend.
The worker holds long jobs (up to `RUN_JOB_TIMEOUT_S`), which rules out request-scoped
serverless hosting.

## Options considered
1. **One VPS (Hetzner-class, 4 GB) + Dokploy** — roughly €5–8/month for the box (not re-verified
   against current price lists). Runs the whole Compose stack including Postgres. Dokploy gives
   Traefik, Let's Encrypt, env storage and deploy triggers. Risk: one box, so backups must leave
   it.
2. **Railway / Render** — less to run, but three services plus managed Postgres and Redis each
   bill separately; the always-on worker makes it dearer than a VPS for a single user.
3. **Fly.io** — good SSE and regions, but more configuration (volumes, multiple apps, Redis)
   for no benefit at this scale.

## Decision
Option 1, with the stack as a single Dokploy **Compose** service (`docker-compose.prod.yml`).

- **Routing:** Traefik labels in the compose file. `/api` goes straight to the API and
  everything else to the frontend, so SSE does not pass through the Next rewrite proxy.
  (The rewrite still works: verified a full run and `Last-Event-ID` replay through it.)
  `compress: false` in `next.config.ts` keeps that path unbuffered.
- **Auth:** Traefik `basicauth` middleware on both routers, credentials in the
  `BASIC_AUTH_USERS` secret. No code change; every row keeps `DEFAULT_USER_ID`. The browser
  attaches its credentials to the SSE request because it is same-origin. Magic-link auth
  becomes worth it only with a second user.
- **Migrations:** a one-shot `migrate` service; `api` and `worker` wait for it to exit 0.
- **Secrets:** Dokploy's Environment tab. The compose file lists every variable the services
  receive; nothing is baked into images.
- **Backups:** a `backup` service runs `pg_dump -Fc` nightly into a volume, 14 days kept,
  and with `RCLONE_REMOTE` set also copies each dump to S3-compatible storage (R2/B2).
  `restore-test.sh` restores the newest dump into a scratch database and drops it.
- **CI/CD:** GitHub Actions runs lint, types and tests, builds the three images, then calls
  Dokploy's `compose.deploy` API. Dokploy's own auto-deploy is turned off so red CI cannot ship.
- **Errors:** optional Sentry (`SENTRY_DSN`) in API and worker. Uptime: an external check on
  `/api/health` with the basic-auth credentials.

## Consequences
- Single point of failure: a dead VPS means downtime until restore. Acceptable for one user;
  off-box dumps are what makes it recoverable, so `RCLONE_REMOTE` should be set before real use.
- Basic auth is shared-password protection, not per-user identity. Rotating it is an env change.
- Unverified until first real deploy: Traefik label names against the installed Dokploy
  (`dokploy-network`, `letsencrypt` resolver), the `compose.deploy` API call, and
  `TRUSTED_PROXY_HOPS=1` seeing the real client address.
