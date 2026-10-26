#!/bin/sh
# Nightly pg_dump. `backup.sh once` dumps now; `backup.sh loop` dumps daily at BACKUP_HOUR_UTC.
# Dumps go to /backups (a volume); with RCLONE_REMOTE set (e.g. r2:bucket/autoincubator) each is
# also copied off the box. rclone reads its config from RCLONE_CONFIG_* variables.
set -eu

dump() {
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  file="/backups/${POSTGRES_DB}-${ts}.dump"
  pg_dump -h "${PGHOST:-postgres}" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$file.part"
  mv "$file.part" "$file"
  echo "backup.ok file=$file bytes=$(wc -c <"$file")"
  if [ -n "${RCLONE_REMOTE:-}" ]; then
    rclone copy "$file" "$RCLONE_REMOTE" && echo "backup.offsite_ok remote=$RCLONE_REMOTE"
  fi
  find /backups -name '*.dump' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
}

case "${1:-loop}" in
  once) dump ;;
  loop)
    while :; do
      now=$(date -u +%s)
      next=$(date -u -d "$(date -u +%Y-%m-%d) ${BACKUP_HOUR_UTC:-03}:00:00" +%s 2>/dev/null || echo $((now + 86400)))
      [ "$next" -le "$now" ] && next=$((next + 86400))
      sleep $((next - now))
      # A failed dump must not stop the loop; the next night tries again.
      dump || echo "backup.failed" >&2
    done ;;
  *) echo "usage: backup.sh once|loop" >&2; exit 2 ;;
esac
