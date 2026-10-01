#!/usr/bin/env sh
set -eu

project="vie-smoke-${VIE_SMOKE_SUFFIX:-$$}"
export COMPOSE_PROJECT_NAME="$project"
export POSTGRES_DB="vie"
export POSTGRES_USER="vie"
export POSTGRES_PASSWORD="vie-smoke-postgres-password"
export DATABASE_URL="postgresql+psycopg://vie:${POSTGRES_PASSWORD}@postgres:5432/vie"
export VIE_API_KEY="vie-smoke-api-key"
export S3_ACCESS_KEY_ID="vie-smoke-access"
export S3_SECRET_ACCESS_KEY="vie-smoke-secret-password"
export S3_BUCKET="vie-smoke-artifacts"
export API_PORT="0"
backup_parent=""

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
  if [ -n "$backup_parent" ]; then rm -rf "$backup_parent"; fi
  exit "$status"
}
trap cleanup EXIT INT TERM

compose up --detach --build --wait --wait-timeout 180

compose exec -T api python -c \
  "import json, urllib.request; payload=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready')); assert payload == {'status': 'ready', 'checks': {'database': 'ok', 'redis': 'ok', 'storage': 'ok'}}, payload"

compose exec -T api python -c \
  "from app.settings import get_settings; from app.storage import build_storage_adapter; adapter=build_storage_adapter(get_settings()); expected=b'vie-g6-smoke'; stored=adapter.put_bytes('smoke/runtime.txt', expected); assert stored['sha256'] == '0ac61cb56f969acbd48ca077a0a0ebd6cfef482872ab1f7d39289f6d6f23fb63'; assert adapter.read_bytes('smoke/runtime.txt') == expected"

compose exec -T api python -c \
  "import fitz; from app.adapters.ocr_base import OcrPageInput; from app.services.ocr_factory import build_ocr_adapter; from app.settings import get_settings; document=fitz.open(); page=document.new_page(); page.insert_text((72, 100), 'vocabulary engine', fontsize=32); image=page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes('png'); result=build_ocr_adapter(get_settings()).extract_page(OcrPageInput(page_number=1, image_bytes=image)); assert 'vocabulary' in ' '.join(block.text for block in result.blocks).lower()"

compose exec -T api python -c \
  "from sqlalchemy import text; from app.db import engine; connection=engine.connect(); assert connection.execute(text('select version_num from alembic_version')).scalar() == '0007_gold_xlsx'; connection.close()"

compose exec -T worker celery -A app.worker.celery_app inspect ping --timeout 5 | grep -q pong
compose exec -T api python -m app.production_pipeline_smoke_cli

compose exec -T api python -c \
  "from pathlib import Path; path=Path('/app/data/smoke/original.txt'); path.parent.mkdir(parents=True, exist_ok=True); path.write_text('original', encoding='utf-8')"
backup_parent=$(mktemp -d)
scripts/backup.sh "$backup_parent/snapshot"

compose exec -T api python -c \
  "from app.settings import get_settings; from app.storage import build_storage_adapter; adapter=build_storage_adapter(get_settings()); adapter.delete('smoke/runtime.txt'); adapter.put_bytes('smoke/stale.txt', b'stale')"
compose exec -T api python -c \
  "from pathlib import Path; Path('/app/data/smoke/original.txt').unlink(); Path('/app/data/smoke/stale.txt').write_text('stale', encoding='utf-8')"
compose exec -T postgres sh -c \
  'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --set=ON_ERROR_STOP=1 --command="CREATE TABLE restore_smoke (id integer)"' \
  >/dev/null

scripts/restore.sh --confirm "$backup_parent/snapshot"

compose exec -T api python -c \
  "from app.settings import get_settings; from app.storage import build_storage_adapter; adapter=build_storage_adapter(get_settings()); assert adapter.read_bytes('smoke/runtime.txt') == b'vie-g6-smoke'; assert not adapter.exists('smoke/stale.txt')"
compose exec -T api python -c \
  "from pathlib import Path; assert Path('/app/data/smoke/original.txt').read_text(encoding='utf-8') == 'original'; assert not Path('/app/data/smoke/stale.txt').exists()"
compose exec -T api python -c \
  "from sqlalchemy import text; from app.db import engine; connection=engine.connect(); assert connection.execute(text(\"select to_regclass('public.restore_smoke')\")).scalar() is None; connection.close()"

echo "Production topology smoke test passed."

if [ -n "${VIE_SMOKE_EVIDENCE:-}" ]; then
  git_sha="${GITHUB_SHA:-}"
  if [ -z "$git_sha" ]; then git_sha=$(git rev-parse HEAD); fi
  image_name="${VIE_IMAGE:-vocabulary-ingestion-engine:local}"
  image_id=$(docker image inspect "$image_name" --format '{{.Id}}')
  python3 -m app.production_smoke_evidence_cli \
    --output "$VIE_SMOKE_EVIDENCE" \
    --git-sha "$git_sha" \
    --image-id "$image_id"
fi
