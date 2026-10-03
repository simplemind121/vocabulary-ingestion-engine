# VIE v0.1 Release Checklist

This file is the single source of truth for Vocabulary Ingestion Engine v0.1 release status. Implementation, documentation, or a passing unit test alone is not enough to mark a release gate `PASS`; every `PASS` must point to executable evidence from the release candidate workload.

Allowed statuses: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `PASS`, `FAIL`.

Last audited: 2026-10-03 (Asia/Taipei), after the Source Media Fidelity work  
Branch: `bootstrap/v0.1.0-alpha`  
Pull request: [#1](https://github.com/simplemind121/vocabulary-ingestion-engine/pull/1)  
Source PDF SHA256: `485771d63e747788d855d2ec033436239001f24a1d835d1e00a6ec9467c632fd`  
Database schema: `0008_source_media`

`v0.1.0-rc1` (commit `976555a`) is superseded: it passed its Release Gate on
evidence this audit found to be wrong (139 entries missing, source media not
covered). The tag is untouched. `v0.1.0-rc2` replaced it and was promoted to `v0.1.0`.

## Gate summary

| Gate | Status | Release evidence | Current blocker / next executable action |
|---|---|---|---|
| R0 — Repository / CI | PASS | `ruff` and 233 tests pass; push and PR CI green on the branch head. | Keep green. |
| R1 — Gold Dataset (text) | PASS | 30/30 pages `HUMAN_VERIFIED` by `wangsanqiang`; pages 300 and 750 re-reviewed after the segmentation fix. | Immutable; any change needs re-review and a new manifest. |
| R1M — Gold Source Media | PASS | 30/30 overlays `HUMAN_VERIFIED`: 12 pages with 15 images, 18 pages verified as zero media. Manifest 1.1 SHA256 `cbe2e7303cc96b647a3e6d961d72b2f361f4d8497ba5da0191283d816492e31e` (`gold_samples/manifest_v1_1.json`). | Same. |
| R2 — Gold Regression | PASS | Predictions from PostgreSQL run `a5ba88aa…`: text 30/30 exact match (OCR F1, segmentation F1, canonical accuracy all 1.0); media 15/15 detected, extracted and correctly associated. Both bound to manifest `cbe2e730…e31e`. | CI consumes the committed predictions. |
| R3 — Full-book E2E (text) | PASS | Run `a5ba88aa-2b04-4208-a8e8-cf9a70692c93` `COMPLETED`, G0–G6 `PASS`, 1120/1120 pages, 23,458 blocks, 3,540 SourceEntries, 3,540 `AUTO_VERIFIED` VocabularyEntries, 23,134 provenance records, 577 cross-page, 0 duplicate lemmas, 9/9 reviews resolved. Source-bound audit: 3,540 candidates, 3,540 parsed. | See `docs/FULL_BOOK_RUN_REPORT.md`. |
| R3M — Full-book Source Media | PASS | 1120/1120 pages scanned; 374 detected = extracted = persisted; 272 bound to entries (270 layout, 2 human); 102 non-vocabulary; 0 unbound, unresolved, missing, broken artifact or broken provenance. `release_evidence/source-media-full-book-v1.json`. | See `docs/SOURCE_MEDIA_REPORT.md`. |
| R4 — Dataset Publication | PASS | GoldRelease `66055ec7-d539-401b-bc92-ecad2235e9f6`, schema 1.1, 3,540 records, 272 with source media. API = JSON; CSV = XLSX; JSON and CSV agree per record. JSON `1f746429…dda4`, CSV `2cc93a32…f289`, XLSX `383dc7b2…266e`. All 374 media objects served by the API match their SHA256. | Immutable. |
| R5 — Production Deployment | PASS | CI `container-smoke` on clean Ubuntu: image build, migration `0008`, PostgreSQL/Redis/worker/API/object storage, Tesseract, queued G0–G6 with a source illustration stored, bound, served and exported, and a reviewed run. | Reproduced by the tag-triggered Release Gate. |
| R6 — Recovery / Operations | PASS | Same smoke: backup, pollution, exact restore; schema-aware drill (downgrade `0008`→`0007`, previous image `17d453b`, upgrade, new workload, rollback, byte-identical state). | Reproduced by the tag-triggered Release Gate. |
| R7 — Release Candidate | PASS | `v0.1.0-rc2` = commit `71c065f333810f20fa7803897798a2e438467f77`. Tag-triggered [Release Gate 37110786120](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/37110786120): Gold regression, production topology smoke and aggregate G6 all `PASS` (10/10 production checks, no blockers). Image `sha256:d80680f9…fe87b`; upgrade from `17d453b` image `sha256:9d4b9962…2462`; recovery state `3d48220f…0527`; G6 report `6c0300e2…cd71`. | Promoted. |

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

Result: `READY_TO_FREEZE`; 30 text annotations and 30 media overlays HUMAN_VERIFIED. Frozen manifest 1.1 SHA256: `cbe2e7303cc96b647a3e6d961d72b2f361f4d8497ba5da0191283d816492e31e`.

### R2 exact-match result

```bash
.venv/bin/python -m app.gold_dataset_benchmark_cli \
  --annotations gold_samples/annotations \
  --predictions benchmarks/gold_sample_v1/predictions \
  --output release_evidence/gold-benchmark-v1.json
.venv/bin/python -m app.gold_regression_cli \
  release_evidence/gold-benchmark-v1.json
```

Result: `PASS`; 30/30 pages exact-match, with OCR, segmentation, and canonical
metrics all `1.0` and no blocking failures.

### R3 full-book evidence

```bash
.venv/bin/python -m app.full_book_evidence_check_cli \
  release_evidence/full-book-audit-v1.json \
  --source-metadata gold_samples/source_document.json
```

Result: `PASS`. Runtime evidence is in `docs/FULL_BOOK_RUN_REPORT.md`.

### R5 runtime probes

```bash
curl --fail http://127.0.0.1:8766/health/live
curl --fail http://127.0.0.1:8766/health/ready
docker compose --env-file .env.gold-runtime -p vie-gold-runtime ps
```

Local runtime evidence is useful hardening evidence but is not a substitute for the required clean Ubuntu deployment.

### Source media commands

```bash
# inside the api container, against the release run
python -m app.source_media_cli pass RUN_ID --publish
python -m app.source_media_cli evidence RUN_ID \
  --output release_evidence/source-media-full-book-v1.json
# no database needed
python -m app.gold_media_cli --require-pass
```

## Release

`v0.1.0` was promoted on 2026-10-03 with explicit user approval. The tag points
at commit `71c065f333810f20fa7803897798a2e438467f77`, the same commit as
`v0.1.0-rc2`. The tag-triggered
[Release Gate 37111131723](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/37111131723)
passed Gold regression, the production topology smoke and the aggregate G6 Gate
on that commit. Commits after the tag change documentation only.

No release blockers remain. Open items are listed in `docs/KNOWN_ISSUES.md`.

## Final v0.1.0 release invariant

`G6 = PASS` and tag `v0.1.0` are forbidden until every gate above, including R1M and R3M, is `PASS`, the immutable RC commit/artifacts have passed the complete release workflow, and the required acceptance, benchmark, full-book, deployment, recovery, known-issues, image-digest, commit-SHA, schema-version, Gold-manifest-SHA256, and release-artifact-SHA256 evidence is recorded.
