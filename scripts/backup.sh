#!/usr/bin/env sh
set -eu

target=${1:-}
if [ -z "$target" ]; then
  echo "Usage: scripts/backup.sh /absolute/path/to/new-backup" >&2
  exit 2
fi
case "$target" in
  /*) ;;
  *) echo "Backup path must be absolute." >&2; exit 2 ;;
esac
if [ -e "$target" ]; then
  echo "Backup target already exists: $target" >&2
  exit 2
fi

parent=$(dirname "$target")
mkdir -p "$parent"
stage=$(mktemp -d "$parent/.vie-backup.XXXXXX")
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
  rm -rf "$stage"
  exit "$status"
}
trap cleanup EXIT INT TERM

docker compose stop --timeout 30 api worker >/dev/null
maintenance=1

docker compose exec -T postgres sh -c \
  'pg_dump --format=custom --no-owner --username="$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$stage/database.dump"
docker compose run --rm --no-deps -T api \
  python -m app.snapshot_cli storage-export --file - \
  > "$stage/object-storage.tar.gz"
docker compose run --rm --no-deps -T api \
  python -m app.snapshot_cli volume-export --root /app/data --file - \
  > "$stage/application-volume.tar.gz"

docker compose config --images > "$stage/images.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$stage/created-at.txt"
(
  cd "$stage"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum database.dump object-storage.tar.gz application-volume.tar.gz images.txt created-at.txt > SHA256SUMS
  else
    shasum -a 256 database.dump object-storage.tar.gz application-volume.tar.gz images.txt created-at.txt > SHA256SUMS
  fi
)

resume_services
mv "$stage" "$target"
trap - EXIT INT TERM
echo "Backup completed: $target"
