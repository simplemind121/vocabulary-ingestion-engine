#!/usr/bin/env sh
set -eu

project="vie-smoke-${VIE_SMOKE_SUFFIX:-$$}"
export POSTGRES_DB="vie"
export POSTGRES_USER="vie"
export POSTGRES_PASSWORD="vie-smoke-postgres-password"
export DATABASE_URL="postgresql+psycopg://vie:${POSTGRES_PASSWORD}@postgres:5432/vie"
export S3_ACCESS_KEY_ID="vie-smoke-access"
export S3_SECRET_ACCESS_KEY="vie-smoke-secret-password"
export S3_BUCKET="vie-smoke-artifacts"
export API_PORT="0"

compose() {
  docker compose -p "$project" "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose ps || true
    compose logs --no-color --tail 200 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT INT TERM

compose up --detach --build --wait --wait-timeout 180

compose exec -T api python -c \
  "import json, urllib.request; payload=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready')); assert payload == {'status': 'ready', 'checks': {'database': 'ok', 'redis': 'ok', 'storage': 'ok'}}, payload"

compose exec -T api python -c \
  "from app.settings import get_settings; from app.storage import build_storage_adapter; adapter=build_storage_adapter(get_settings()); expected=b'vie-g6-smoke'; stored=adapter.put_bytes('smoke/runtime.txt', expected); assert stored['sha256'] == '0ac61cb56f969acbd48ca077a0a0ebd6cfef482872ab1f7d39289f6d6f23fb63'; assert adapter.read_bytes('smoke/runtime.txt') == expected"

compose exec -T api python -c \
  "from sqlalchemy import text; from app.db import engine; connection=engine.connect(); assert connection.execute(text('select version_num from alembic_version')).scalar() == '0007_gold_xlsx'; connection.close()"

compose exec -T worker celery -A app.worker.celery_app inspect ping --timeout 5 | grep -q pong

echo "Production topology smoke test passed."
