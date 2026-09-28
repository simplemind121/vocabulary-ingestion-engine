# Vocabulary Ingestion Engine

Production-oriented, provenance-first vocabulary database factory.

> Upload PDF → Bronze → Render/IDR → OCR/Layout adapters → Entry Segmentation → Canonical Vocabulary → Validation/Review → Verified Gold.

## v0.1.0-alpha bootstrap

The first executable slice implements PDF ingestion, SHA-256 source preservation, PyMuPDF page rendering, Processing Run identity, G0 document-integrity evidence, and a G6 Gold preflight guard. PostgreSQL and Redis are present in the deployment topology; persistent repositories, migrations, OCR adapters, Review UI and Gold snapshots follow in the next slices.

## Non-negotiable Gold contract

Gold permits only resolved, validated and traceable records. Unresolved records, missing required provenance, open required reviews or blocking validation errors prevent publication.

## Run

```bash
docker compose up --build
```

API: `http://localhost:8000`

OpenAPI: `http://localhost:8000/docs`

Health: `GET /health`

Upload: `POST /api/v1/documents` using multipart field `file`.

Gold preflight: `POST /api/v1/gold/preflight`.

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
- S3-compatible object storage / Backblaze B2 target
- Next.js / React target UI
- PyMuPDF baseline renderer
- Replaceable OCR/parser adapters (MinerU, PaddleOCR/PP-Structure, vision fallback)
- Gate-driven G0–G6 pipeline
- 30-page manually verified Gold Sample Dataset before parser optimization

The ingestion engine is independent from IELTS Vocabulary Coach and exposes verified datasets/API for downstream products.
