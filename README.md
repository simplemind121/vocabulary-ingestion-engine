# Vocabulary Ingestion Engine

Production-oriented, provenance-first vocabulary database factory.

> Upload PDF → Bronze → Render/IDR → OCR/Layout adapters → Entry Segmentation → Canonical Vocabulary → Validation/Review → Verified Gold.

## Current alpha state

The pipeline, persistent schema, migrations, review workflow, deterministic Gold publication, JSON/CSV/XLSX exports, API, worker, and production service topology are implemented. The real 30-page Gold Sample remains fail-closed until all pages receive explicit human verification; machine preannotation never grants `HUMAN_VERIFIED`.

## Non-negotiable Gold contract

Gold permits only resolved, validated and traceable records. Unresolved records, missing required provenance, open required reviews or blocking validation errors prevent publication.

## Run

```bash
cp .env.example .env
# Replace every placeholder in .env before starting.
docker compose up --detach --build --wait
```

API: `http://localhost:8000`

OpenAPI: `http://localhost:8000/docs`

Liveness: `GET /health/live`

Readiness: `GET /health/ready`

API calls require `Authorization: Bearer <VIE_API_KEY>` in the Compose deployment.

Upload: `POST /api/v1/documents` using multipart field `file`.

Gold preflight: `POST /api/v1/gold/preflight`.

See [Production operations](docs/OPERATIONS.md) for install, backup, restore, upgrade, and rollback procedures.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

## Architecture baseline

- Python / FastAPI
- PostgreSQL / SQLAlchemy / Alembic
- Redis + worker queue
- S3-compatible object storage (SeaweedFS locally; AWS S3/Backblaze B2 compatible adapter)
- Next.js / React target UI
- PyMuPDF baseline renderer
- Replaceable OCR/parser adapters (MinerU, PaddleOCR/PP-Structure, vision fallback)
- Gate-driven G0–G6 pipeline
- 30-page manually verified Gold Sample Dataset before parser optimization

The ingestion engine is independent from IELTS Vocabulary Coach and exposes verified datasets/API for downstream products.
