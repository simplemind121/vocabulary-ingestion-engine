# VIE v0.1 Release Checklist

This file is the single source of truth for Vocabulary Ingestion Engine v0.1 release status. Implementation, documentation, or a passing unit test alone is not enough to mark a release gate `PASS`; every `PASS` must point to executable evidence from the release candidate workload.

Allowed statuses: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `PASS`, `FAIL`.

Last audited: 2026-10-03 (Asia/Taipei), after the Source Media Fidelity work  
Branch: `bootstrap/v0.1.0-alpha`  
Pull request: [#1](https://github.com/simplemind121/vocabulary-ingestion-engine/pull/1)  
Source PDF SHA256: `485771d63e747788d855d2ec033436239001f24a1d835d1e00a6ec9467c632fd`  
Database schema: `0008_source_media`

**v0.1.0 promotion is paused.** `v0.1.0-rc1` (commit `976555a`) passed its
Release Gate on evidence that this audit found to be wrong: 139 entries were
missing and source media was not covered. The tag stays untouched; the next
candidate is `v0.1.0-rc2`. See `docs/KNOWN_ISSUES.md` and
`docs/SOURCE_MEDIA_REPORT.md`.

## Gate summary

| Gate | Status | Release evidence | Current blocker / next executable action |
|---|---|---|---|
| R0 — Repository / CI | PASS | `ruff` and 231 tests pass locally; push and PR CI must be green on the head commit. | Keep subsequent commits green. |
| R1 — Gold Dataset (text) | BLOCKED | 28/30 pages `HUMAN_VERIFIED`. Pages 300 and 750 were reopened as `DRAFT`: their verified annotations merged `contrast` into `tunnel` and `bow` into `renew`. The other 28 pages match the corrected pipeline exactly and are unchanged. Manifest `c24afe5e…f9d5` no longer represents the corpus. | Human re-review of pages 300 and 750. |
| R1M — Gold Source Media | BLOCKED | Review packet built from the real PDF: 12 of 30 pages contain media, 15 images. 0/30 overlays are human-verified. | Human media review of the 30 pages (`/media` in the local review UI). |
| R2 — Gold Regression | BLOCKED | The committed predictions predate the segmentation fix. | After R1/R1M: regenerate text and media predictions from the completed PostgreSQL run, freeze manifest 1.1, require exact match. |
| R3 — Full-book E2E (text) | IN_PROGRESS | Source-bound audit regenerated on the fixed pipeline: 1120/1120 pages represented, 23,458 blocks, 3,540 candidates, 3,540 parsed, 576 cross-page (`release_evidence/full-book-audit-v1.json`). PostgreSQL run `a5ba88aa-2b04-4208-a8e8-cf9a70692c93` passed G0 and stopped at G1 with 6 open low-confidence OCR reviews. | Human OCR review, then the run continues. |
| R3M — Full-book Source Media | IN_PROGRESS | Pre-review pass over the real PDF: 374 detected = extracted = persisted, 270 bound, 101 non-vocabulary, 3 unresolved, 0 missing, 0 broken. | Human decision on 3 images (pages 5, 665, 816) in the run's Review Queue; then write `release_evidence/source-media-full-book-v1.json`. |
| R4 — Dataset Publication | BLOCKED | GoldRelease `13e45a80…` (3,401 records, schema 1.0) is superseded. Schema 1.1 adds `source_media`, `source_fields`, `source_pages`; CSV/XLSX add `source_pages`, `source_media_count`, `source_media_refs`, `source_media_sha256`. | Publish from the completed run; verify API = JSON = CSV = XLSX. |
| R5 — Production Deployment | IN_PROGRESS | Local clean Compose smoke passed on the new code, including one source illustration stored in S3-compatible storage, bound, served by the API with a matching SHA256, and exported. | CI `container-smoke` on the head commit; then the tag-triggered Release Gate. |
| R6 — Recovery / Operations | IN_PROGRESS | Local smoke passed backup, destructive pollution, exact restore, and a schema-aware drill: downgrade `0008`→`0007`, previous image `17d453b`, upgrade to `0008`, new workload, rollback and byte-identical state. | Same as R5. |
| R7 — Release Candidate | BLOCKED | `v0.1.0-rc1` is superseded and unchanged. | All gates above `PASS`, then tag `v0.1.0-rc2` and rerun the full Release Gate on that commit. |

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

Result: `READY_TO_FREEZE`; 30 annotations, 30 HUMAN_VERIFIED, publishing allowed. Frozen manifest SHA256: `c24afe5e1403e920222ce3c3dc9e5389ae3197e996f0ba1029ef16429847f9d5`.

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

### R3 full-book evidence commands and audited result

```bash
.venv/bin/python -m app.full_book_evidence_check_cli \
  release_evidence/full-book-audit-v1.json \
  --source-metadata gold_samples/source_document.json
```

Result: `PASS` for source-bound evidence integrity. The final persisted workload after Gold-driven parser stabilization also passed.

Persisted runtime evidence:

- Document ID: `cfcb9160-6d63-4ecf-bfce-7e91f7fcac45`
- DocumentVersion ID: `1345d2b5-1197-4928-bb43-405ea84a1b18`
- ProcessingRun ID: `5d6557a5-b63c-47a8-b638-e86b412e5d7c`
- G0: `PASS`
- G1–G6: `PASS`
- Pages: 1120
- SourceBlocks: 23,458
- Resolved / open review tasks: 6 / 0
- SourceEntries / VocabularyEntries / ProvenanceRecords / GoldReleases: 3,401 / 3,401 / 21,684 / 1
- Vocabulary verification: 3,401 `AUTO_VERIFIED`, 0 `HUMAN_VERIFIED`
- Cross-page / unresolved cross-page / duplicate lemma / duplicate source-entry rows: 570 / 0 / 0 / 0
- GoldRelease ID: `13e45a80-ed86-4737-8dfe-7278c913630b`

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

## Release blockers in execution order

1. Human review: Gold text pages 300 and 750; Gold media on all 30 pages; the
   release run's Review Queue (6 OCR blocks, then 3 images).
2. Regenerate predictions and evidence from the completed run; freeze manifest 1.1.
3. Green CI on the evidence commit; tag `v0.1.0-rc2`; full Release Gate on that tag.
4. Release Readiness Report, then explicit user approval before `v0.1.0`.

## Final v0.1.0 release invariant

`G6 = PASS` and tag `v0.1.0` are forbidden until every gate above, including R1M and R3M, is `PASS`, the immutable RC commit/artifacts have passed the complete release workflow, and the required acceptance, benchmark, full-book, deployment, recovery, known-issues, image-digest, commit-SHA, schema-version, Gold-manifest-SHA256, and release-artifact-SHA256 evidence is recorded.
