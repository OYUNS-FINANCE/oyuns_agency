# Runbook

Production is one Dokploy Compose service on a VPS (ADR 0009). Variables: `.env.production.example`.

## First deploy
1. VPS with Docker; install Dokploy (`curl -sSL https://dokploy.com/install.sh | sh`), open
   `http://<ip>:3000`, create the admin, set the panel domain + HTTPS, then firewall port 3000.
2. DNS: A record `app.example.com` → VPS.
3. Dokploy → Create Compose: Git provider, repo, branch `main`, compose path
   `./autoincubator/docker-compose.prod.yml`. Turn **Autodeploy off**.
4. Environment tab: fill every variable from `.env.production.example`. Generate:
   - `POSTGRES_PASSWORD`: `openssl rand -hex 24`
   - `BASIC_AUTH_USERS`: `echo $(htpasswd -nbB me 'PASSWORD') | sed -e 's/\$/\$\$/g'`
5. Deploy. Wait for `migrate` to exit 0 and `api` to be healthy.
6. Check: `curl -u me:PASSWORD https://app.example.com/api/health` → `{"db":"ok","redis":"ok"}`.
7. Start one real run in the UI; confirm events stream and survive a page reload.

## Routine deploy
Merge to `main`. CI runs, then calls Dokploy. Secrets (GitHub → Environments → production):
`DOKPLOY_URL`, `DOKPLOY_API_KEY` (Dokploy → Settings → API), `DOKPLOY_COMPOSE_ID` (in the
compose service's URL). Manual: press Deploy in Dokploy.

## Rollback
Dokploy → Compose → Deployments → redeploy the previous one, or `git revert` on main.
Migrations are not auto-reversed: if the bad release added one, run
`docker compose exec api alembic downgrade -1` **before** redeploying old code, or restore a backup.

## Backups
- Nightly 03:00 UTC (`BACKUP_HOUR_UTC`), kept 14 days in the `backups` volume, copied to
  `RCLONE_REMOTE` if set. Logs: `docker compose logs backup`.
- Take one now: `docker compose exec backup backup.sh once`.
- **Test a restore (do monthly):** `docker compose exec backup restore-test.sh` — restores the
  newest dump into a scratch DB, prints `restore.ok tables=N runs=M`, drops it.
- **Real restore:** stop `api` and `worker`; fetch the dump (from the volume or
  `rclone copy`); `docker compose exec -T postgres pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists < dump`;
  start `api`, `worker`.

## Rotating keys
- Anthropic / Tavily / Serper: change in the Environment tab → Deploy (restarts api + worker).
  Revoke the old key at the provider afterwards.
- Basic-auth password: regenerate `BASIC_AUTH_USERS` → Deploy.
- `POSTGRES_PASSWORD`: also changes inside Postgres:
  `docker compose exec postgres psql -U $POSTGRES_USER -c "ALTER USER $POSTGRES_USER PASSWORD '…'"`,
  then update the variable and Deploy.

## Troubleshooting
- Stream stalls behind the proxy: check the response has `Cache-Control: no-cache, no-transform`
  and nothing between Traefik and the browser (Cloudflare proxy, extra middleware) compresses it.
- Runs stuck `running` after a worker restart: the recovery cron re-enqueues them after
  `RUN_LEASE_TTL_S`; look for `recover_runs` in `docker compose logs worker`.
- Spend: `DAILY_COST_CAP_USD` stops new LLM calls for the UTC day; the run page shows cost.
