#!/bin/sh
# Restores a dump (default: the newest in /backups) into a scratch database, checks that the
# tables came back, and drops the scratch database. Never touches POSTGRES_DB.
set -eu
host="${PGHOST:-postgres}"
file="${1:-$(ls -1t /backups/*.dump | head -n1)}"
scratch="restore_test_$(date -u +%s)"
echo "restore.start file=$file scratch=$scratch"
createdb -h "$host" -U "$POSTGRES_USER" "$scratch"
trap 'dropdb -h "$host" -U "$POSTGRES_USER" --if-exists "$scratch"' EXIT
pg_restore -h "$host" -U "$POSTGRES_USER" -d "$scratch" --no-owner --exit-on-error "$file"
tables=$(psql -h "$host" -U "$POSTGRES_USER" -d "$scratch" -Atc \
  "select count(*) from information_schema.tables where table_schema='public'")
runs=$(psql -h "$host" -U "$POSTGRES_USER" -d "$scratch" -Atc "select count(*) from runs")
echo "restore.ok tables=$tables runs=$runs"
[ "$tables" -gt 0 ]
