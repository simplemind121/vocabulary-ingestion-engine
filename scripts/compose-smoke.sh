#!/usr/bin/env sh
set -eu

project="vie-smoke-${VIE_SMOKE_SUFFIX:-$$}"
export COMPOSE_PROJECT_NAME="$project"
export POSTGRES_DB="vie"
export POSTGRES_USER="vie"
export POSTGRES_PASSWORD="vie-smoke-postgres-password"
export DATABASE_URL="postgresql+psycopg://vie:${POSTGRES_PASSWORD}@postgres:5432/vie"
export VIE_API_KEY="vie-smoke-api-key"
export VIE_OCR_MIN_CONFIDENCE="1.0"
export S3_ACCESS_KEY_ID="vie-smoke-access"
export S3_SECRET_ACCESS_KEY="vie-smoke-secret-password"
export S3_BUCKET="vie-smoke-artifacts"
export API_PORT="0"
backup_parent=""
previous_source=""
previous_image=""
current_image_name="${VIE_IMAGE:-vocabulary-ingestion-engine:local}"
upgrade_from_sha="${VIE_UPGRADE_FROM_SHA:-17d453b924f318dcce7ae723d438a6197a85ed96}"

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
  if [ -n "$previous_source" ]; then rm -rf "$previous_source"; fi
  if [ -n "$previous_image" ]; then docker image rm "$previous_image" >/dev/null 2>&1 || true; fi
  exit "$status"
}
trap cleanup EXIT INT TERM

capture_recovery_state() {
  compose exec -T api python - <<'PY'
import json

from sqlalchemy import func, select, text

from app.db import SessionLocal
from app.models import (
    GoldRelease,
    ProcessingRun,
    ProvenanceRecord,
    ReviewTask,
    SourceBlock,
    SourceEntry,
    VocabularyEntry,
)

with SessionLocal() as db:
    reviews = list(db.scalars(select(ReviewTask).order_by(ReviewTask.id)))
    releases = list(db.scalars(select(GoldRelease).order_by(GoldRelease.id)))
    if not reviews or any(item.status != "RESOLVED" for item in reviews):
        raise RuntimeError("recovery state must contain only resolved human reviews")
    reviewer_ids = sorted(
        str(item.candidate_values[0]["reviewer_id"])
        for item in reviews
        if item.candidate_values
    )
    if len(reviewer_ids) != len(reviews) or any(not item for item in reviewer_ids):
        raise RuntimeError("resolved review audit is missing reviewer identity")
    count = lambda model: db.scalar(select(func.count()).select_from(model))
    payload = {
        "counts": {
            "gold_releases": count(GoldRelease),
            "processing_runs": count(ProcessingRun),
            "provenance_records": count(ProvenanceRecord),
            "review_tasks": count(ReviewTask),
            "source_blocks": count(SourceBlock),
            "source_entries": count(SourceEntry),
            "vocabulary_entries": count(VocabularyEntry),
        },
        "human_review_provenance": db.scalar(
            select(func.count()).select_from(ProvenanceRecord).where(
                ProvenanceRecord.provenance_type == "HUMAN_REVIEW"
            )
        ),
        "releases": [
            {
                "id": item.id,
                "record_count": item.record_count,
                "schema_version": item.schema_version,
                "sha256": item.sha256,
                "version": item.version,
            }
            for item in releases
        ],
        "reviews": [
            {
                "candidate_values": item.candidate_values,
                "id": item.id,
                "status": item.status,
            }
            for item in reviews
        ],
        "reviewer_ids": reviewer_ids,
    }
print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
PY
}

schema_version() {
  compose exec -T postgres sh -c \
    'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="select version_num from alembic_version"' \
    | tr -d '[:space:]'
}

assert_recovery_state() {
  expected=$1
  actual=$2
  capture_recovery_state > "$actual"
  if ! cmp -s "$expected" "$actual"; then
    diff -u "$expected" "$actual" || true
    echo "Recovery state differs from its immutable snapshot." >&2
    return 1
  fi
}

verify_recovered_downloads() {
  compose exec -T api python - <<'PY'
import urllib.request

from sqlalchemy import select

from app.db import SessionLocal
from app.models import GoldRelease
from app.settings import get_settings

with SessionLocal() as db:
    release_id = db.scalar(select(GoldRelease.id).order_by(GoldRelease.created_at).limit(1))
if release_id is None:
    raise RuntimeError("recovered snapshot has no Gold release")
token = get_settings().api_key.get_secret_value()
for artifact_format, prefix in (("json", b"{"), ("csv", b"id,"), ("xlsx", b"PK")):
    request = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/gold/releases/{release_id}/download/{artifact_format}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    if not payload.startswith(prefix):
        raise RuntimeError(f"recovered {artifact_format} artifact is invalid")
PY
}

compose up --detach --build --wait --wait-timeout 180

compose exec -T api python -c \
  "import json, urllib.request; payload=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready')); assert payload == {'status': 'ready', 'checks': {'database': 'ok', 'redis': 'ok', 'storage': 'ok'}}, payload"

compose exec -T api python -c \
  "from app.settings import get_settings; from app.storage import build_storage_adapter; adapter=build_storage_adapter(get_settings()); expected=b'vie-g6-smoke'; stored=adapter.put_bytes('smoke/runtime.txt', expected); assert stored['sha256'] == '0ac61cb56f969acbd48ca077a0a0ebd6cfef482872ab1f7d39289f6d6f23fb63'; assert adapter.read_bytes('smoke/runtime.txt') == expected"

compose exec -T api python -c \
  "import fitz; from app.adapters.ocr_base import OcrPageInput; from app.services.ocr_factory import build_ocr_adapter; from app.settings import get_settings; document=fitz.open(); page=document.new_page(); page.insert_text((72, 100), 'vocabulary engine', fontsize=32); image=page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes('png'); result=build_ocr_adapter(get_settings()).extract_page(OcrPageInput(page_number=1, image_bytes=image)); assert 'vocabulary' in ' '.join(block.text for block in result.blocks).lower()"

compose exec -T api python -c \
  "from sqlalchemy import text; from app.db import engine; connection=engine.connect(); assert connection.execute(text('select version_num from alembic_version')).scalar() == '0008_source_media'; connection.close()"

compose exec -T worker celery -A app.worker.celery_app inspect ping --timeout 5 | grep -q pong
compose exec -T api python -m app.production_pipeline_smoke_cli
compose exec -T api python -c \
  "import urllib.request; request=urllib.request.Request('http://127.0.0.1:8000/metrics', headers={'Authorization': 'Bearer vie-smoke-api-key'}); payload=urllib.request.urlopen(request).read().decode(); assert 'vie_build_info' in payload; assert 'vie_processing_runs{status=\"COMPLETED\"} 2' in payload; assert 'vie_gold_releases_total 2' in payload"

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

current_image_id=$(docker image inspect "$current_image_name" --format '{{.Id}}')
previous_source=$(mktemp -d)
previous_image="vocabulary-ingestion-engine:upgrade-from-${upgrade_from_sha}"
git cat-file -e "${upgrade_from_sha}^{commit}"
git archive --format=tar --output "$previous_source/source.tar" "$upgrade_from_sha"
tar -xf "$previous_source/source.tar" -C "$previous_source"
rm "$previous_source/source.tar"
docker build --tag "$previous_image" "$previous_source"
previous_image_id=$(docker image inspect "$previous_image" --format '{{.Id}}')

# A release that changes the schema is rolled back by downgrading the schema
# with the new image first; only then can the previous image own the database.
previous_schema=$(sed -n 's/^revision = "\(.*\)"$/\1/p' \
  "$(ls "$previous_source"/migrations/versions/*.py | sort | tail -n 1)")
current_schema=$(schema_version)
compose stop --timeout 30 api worker >/dev/null
compose run --rm --no-deps -T migrate alembic downgrade "$previous_schema"

export VIE_IMAGE="$previous_image"
compose up --detach --no-build --wait --wait-timeout 180
running_image_id=$(docker inspect "$(compose ps -q api)" --format '{{.Image}}')
test "$running_image_id" = "$previous_image_id"
test "$(schema_version)" = "$previous_schema"
capture_recovery_state > "$backup_parent/pre-upgrade-state.json"
scripts/backup.sh "$backup_parent/pre-upgrade"

export VIE_IMAGE="$current_image_name"
compose up --detach --no-build --wait --wait-timeout 180
running_image_id=$(docker inspect "$(compose ps -q api)" --format '{{.Image}}')
test "$running_image_id" = "$current_image_id"
test "$(schema_version)" = "$current_schema"
assert_recovery_state \
  "$backup_parent/pre-upgrade-state.json" \
  "$backup_parent/post-upgrade-state.json"
compose exec -T api python -m app.production_pipeline_smoke_cli

export VIE_IMAGE="$previous_image"
scripts/restore.sh --confirm "$backup_parent/pre-upgrade"
running_image_id=$(docker inspect "$(compose ps -q api)" --format '{{.Image}}')
test "$running_image_id" = "$previous_image_id"
test "$(schema_version)" = "$previous_schema"
assert_recovery_state \
  "$backup_parent/pre-upgrade-state.json" \
  "$backup_parent/post-rollback-state.json"
verify_recovered_downloads

echo "Production topology, immutable-image upgrade, and rollback smoke test passed."

if [ -n "${VIE_SMOKE_EVIDENCE:-}" ]; then
  git_sha="${GITHUB_SHA:-}"
  if [ -z "$git_sha" ]; then git_sha=$(git rev-parse HEAD); fi
  if command -v sha256sum >/dev/null 2>&1; then
    recovery_state_sha256=$(sha256sum "$backup_parent/pre-upgrade-state.json" | awk '{print $1}')
  else
    recovery_state_sha256=$(shasum -a 256 "$backup_parent/pre-upgrade-state.json" | awk '{print $1}')
  fi
  python3 -m app.production_smoke_evidence_cli \
    --output "$VIE_SMOKE_EVIDENCE" \
    --git-sha "$git_sha" \
    --image-id "$current_image_id" \
    --upgrade-from-git-sha "$upgrade_from_sha" \
    --upgrade-from-image-id "$previous_image_id" \
    --recovery-state-sha256 "$recovery_state_sha256"
fi
