# VIE v0.1 Release Checklist

This file is the single source of truth for Vocabulary Ingestion Engine v0.1 release status. Implementation, documentation, or a passing unit test alone is not enough to mark a release gate `PASS`; every `PASS` must point to executable evidence from the release candidate workload.

Allowed statuses: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `PASS`, `FAIL`.

Last audited: 2026-10-01 (Asia/Taipei)  
Branch: `bootstrap/v0.1.0-alpha`  
Audited code commit: `e9d9995823e2feb12abd4ff7851674298507ca3c`  
Pull request: [#1](https://github.com/simplemind121/vocabulary-ingestion-engine/pull/1) (`OPEN`, `MERGEABLE`)  
Source PDF SHA256: `485771d63e747788d855d2ec033436239001f24a1d835d1e00a6ec9467c632fd`  
Database schema: `0007_gold_xlsx`

## Gate summary

| Gate | Status | Release evidence | Current blocker / next executable action |
|---|---|---|---|
| R0 — Repository / CI | PASS | Local `ruff` passed and `pytest` passed with 186 tests at `e9d9995`. Remote test, Gold readiness/evidence validation, and production-topology container smoke all passed for the same code commit in [CI run 36867104793](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/36867104793). PR #1 is open and mergeable. | Keep this gate green; any code, migration, workflow, or release-evidence change requires a new successful CI run before release. |
| R1 — Gold Dataset | BLOCKED | 30 annotation files and all required layout tags are present. The executable readiness result is `annotation_count=30`, `human_verified_count=0`, `publish_allowed=false`, `status=NOT_READY`. The real PostgreSQL run has all 30 selected pages represented by SourceBlocks, but 0/19 entry-bearing pages currently have persisted SourceEntry/Vocabulary rows. | A real human must resolve six low-confidence OCR tasks before retrying the persisted pipeline. Then generate the 30-page machine draft/review packet, obtain 30/30 real reviewer sign-offs, prove unresolved/schema/provenance errors are zero, and freeze the manifest. Never promote machine output to `HUMAN_VERIFIED`. |
| R2 — Gold Regression | BLOCKED | The regression implementation and release gate exist, but there is no frozen 30/30 HUMAN_VERIFIED Gold manifest or real benchmark artifact to consume. | Complete R1, run the benchmark against the frozen manifest, save the report, and execute the regression gate against that artifact. |
| R3 — Full-book E2E | BLOCKED | Real PDF audit artifact validates successfully and covers 1120/1120 pages, 23,458 SourceBlocks, 3,401 entry candidates, 569 cross-page candidates, and 3 low-confidence cover OCR blocks. Real PostgreSQL ProcessingRun `cfb68afa-6b9f-4992-b86d-0db27f950014` contains 1120 pages and 23,458 SourceBlocks; G0 is `PASS`, G1 is `REVIEW_REQUIRED`, and six review tasks are open. | Resolve the six OCR reviews with a real reviewer, retry the same run, and continue through SourceEntry, canonical vocabulary, validation, review, and export. Current database counts are SourceEntry=0, VocabularyEntry=0, ProvenanceRecord=0, GoldRelease=0, so this is not an end-to-end pass. |
| R4 — Dataset Publication | BLOCKED | Publication code and JSON/CSV/XLSX/API tests exist, but the real source database has no canonical vocabulary or Gold release. | Complete R3, publish Vocabulary Database v1, produce actual JSON/CSV/XLSX artifacts, compare counts/checksums, and prove sampled reverse provenance to page/document/source SHA256. |
| R5 — Production Deployment | IN_PROGRESS | The isolated Compose runtime currently reports API live version `0.1.0-alpha.4` and readiness checks `database=ok`, `redis=ok`, `storage=ok`. PostgreSQL, Redis, worker, API, and object storage run with persistent volumes, and migration `0007_gold_xlsx` completed. | Execute the documented workflow in a clean ordinary Ubuntu VM/VPS from clone through upload, processing, review, publish, and export without manual database/source edits or undocumented commands. |
| R6 — Recovery / Operations | IN_PROGRESS | Restarting the isolated Compose project preserved the real 1120 pages and 23,458 SourceBlocks, and health/readiness recovered. Human-reviewed OCR block reuse/protection and terminal reviewed-task retry behavior have regression tests. | Execute and record the complete failure matrix, then perform PostgreSQL plus object-artifact backup and restore into a clean environment. Verify counts, dataset version, provenance, human review state, upgrade, migration, and rollback. A successful backup alone is not `PASS`. |
| R7 — Release Candidate | BLOCKED | No immutable v0.1.0 release candidate has been created. | R0–R6 must be `PASS`. Tag `v0.1.0-rc1`, rerun all release gates on the same commit/artifacts, record image and artifact digests, and cut a new RC for any fix. |

## Executable evidence

### R0 commands

```bash
.venv/bin/ruff check app tests
.venv/bin/pytest -q
gh pr view 1 --json url,state,mergeable,headRefOid,statusCheckRollup
gh run list --branch bootstrap/v0.1.0-alpha --limit 6
```

### R1 readiness command and audited result

```bash
.venv/bin/python -m app.gold_corpus_cli \
  --annotations gold_samples/annotations \
  --output data-private/release-audit/gold-readiness.json
```

Result: `NOT_READY`; 30 annotations, 0 HUMAN_VERIFIED, publishing refused.

### R3 full-book evidence commands and audited result

```bash
.venv/bin/python -m app.full_book_evidence_check_cli \
  release_evidence/full-book-audit-v1.json \
  --source-metadata gold_samples/source_document.json
```

Result: `PASS` for evidence integrity. The underlying workload result remains `REVIEW_REQUIRED`, not a full-book E2E pass.

Persisted runtime evidence:

- Document ID: `440419a6-79a5-4480-8f13-c20e576b70bb`
- DocumentVersion ID: `22f520e0-d554-4004-8c08-16dfc7c7d738`
- ProcessingRun ID: `cfb68afa-6b9f-4992-b86d-0db27f950014`
- G0: `PASS`
- G1: `REVIEW_REQUIRED`
- Pages: 1120
- SourceBlocks: 23,458
- Open review tasks: 6
- SourceEntries / VocabularyEntries / ProvenanceRecords / GoldReleases: 0 / 0 / 0 / 0

### R5 runtime probes

```bash
curl --fail http://127.0.0.1:8766/health/live
curl --fail http://127.0.0.1:8766/health/ready
docker compose --env-file .env.gold-runtime -p vie-gold-runtime ps
```

Local runtime evidence is useful hardening evidence but is not a substitute for the required clean Ubuntu deployment.

## Release blockers in execution order

1. Six real G1 OCR review tasks require a named human reviewer. Until resolved, retrying the persisted run must continue to stop at G1.
2. Retry the same ProcessingRun and persist SourceEntry, VocabularyEntry, and provenance for the 30 selected pages and the full book.
3. Generate the minimum 30-page review packet and complete 30/30 explicit HUMAN_VERIFIED sign-offs.
4. Freeze the Gold manifest, create the real Gold benchmark artifact, and pass Gold regression.
5. Finish the same 1120-page run through verified publication and consistent JSON/CSV/XLSX/API outputs.
6. Complete clean Ubuntu deployment plus verified backup/restore/upgrade/rollback before creating RC1.

## Final v0.1.0 release invariant

`G6 = PASS` and tag `v0.1.0` are forbidden until every R0–R7 gate above is `PASS`, the immutable RC commit/artifacts have passed the complete release workflow, and the required acceptance, benchmark, full-book, deployment, recovery, known-issues, image-digest, commit-SHA, schema-version, Gold-manifest-SHA256, and release-artifact-SHA256 evidence is recorded.
