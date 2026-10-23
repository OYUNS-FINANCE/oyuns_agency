# Phase 7 — Deployment

## Goal
The app is running on a public URL behind auth, with backups and a repeatable deploy.

## Scope
- Production Dockerfiles (multi-stage) for api, worker and frontend; `docker-compose.prod.yml`.
- **Recommend a target in an ADR.** Compare: a single VPS (e.g., Hetzner) with Compose + Caddy; Railway/Render; or Fly.io. Use managed Postgres where it is cheap enough. Optimize for a solo founder: low cost, low ops.
- **Auth:** simple single-user protection to start (e.g., an email magic link via Auth.js, or Cloudflare Access). The `user_id` columns are already in place.
- **Secrets:** handled through the platform's secret store. Migrations run on deploy.
- **CI (GitHub Actions):** lint, typecheck and tests on PR; build and deploy on main.
- **Ops:** nightly Postgres backups with a tested restore, uptime check, error alerts (e.g., Sentry).
- SSE works behind the proxy (buffering disabled, timeouts raised).

## Acceptance criteria
- [ ] Fresh deploy from main with one command or one push.
- [ ] A full run works on the public URL, including SSE reconnect.
- [ ] A backup is restored into a scratch DB successfully.
- [ ] `docs/RUNBOOK.md` covers deploy, rollback, restore, rotating keys.

## Prompt to paste
```
Phase 7. Read CLAUDE.md, docs/PROGRESS.md and docs/phases/07-deployment.md.
Write the hosting ADR with monthly cost estimates (verify current pricing), recommend one, wait for my OK, then implement and verify every acceptance criterion.
```
