#!/usr/bin/env sh
set -eu

if [ "${1:-}" != "--confirm" ] || [ -z "${2:-}" ] || [ -n "${3:-}" ]; then
  echo "Usage: scripts/restore.sh --confirm /absolute/path/to/backup" >&2
  exit 2
fi
backup=$2
case "$backup" in
  /*) ;;
  *) echo "Backup path must be absolute." >&2; exit 2 ;;
esac
for required in database.dump object-storage.tar.gz application-volume.tar.gz SHA256SUMS; do
  if [ ! -f "$backup/$required" ]; then
    echo "Backup is incomplete; missing $required" >&2
    exit 2
  fi
done

(
  cd "$backup"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 --check SHA256SUMS
  fi
)

api_was_running=$(docker compose ps --status running -q api || true)
worker_was_running=$(docker compose ps --status running -q worker || true)
maintenance=0

resume_services() {
  if [ "$maintenance" -eq 1 ]; then
    if [ -n "$api_was_running" ]; then docker compose start api >/dev/null; fi
    if [ -n "$worker_was_running" ]; then docker compose start worker >/dev/null; fi
    maintenance=0
  fi
}

cleanup() {
  status=$?
  resume_services || true
  exit "$status"
}
trap cleanup EXIT INT TERM

docker compose stop --timeout 30 api worker >/dev/null
maintenance=1

docker compose exec -T postgres sh -c \
  'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --set=ON_ERROR_STOP=1 --command="DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION CURRENT_USER"'
docker compose exec -T postgres sh -c \
  'pg_restore --exit-on-error --no-owner --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  < "$backup/database.dump"

docker compose run --rm --no-deps -T \
  -e VIE_ALLOW_DESTRUCTIVE_RESTORE=1 api \
  python -m app.snapshot_cli storage-restore --replace --file - \
  < "$backup/object-storage.tar.gz"
docker compose run --rm --no-deps -T \
  -e VIE_ALLOW_DESTRUCTIVE_RESTORE=1 api \
  python -m app.snapshot_cli volume-restore --replace --root /app/data --file - \
  < "$backup/application-volume.tar.gz"

maintenance=0
docker compose up --detach --wait --wait-timeout 180 api worker
trap - EXIT INT TERM
echo "Restore completed and services are ready."
