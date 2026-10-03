# VIE v0.1 Release Checklist

This file is the single source of truth for Vocabulary Ingestion Engine v0.1 release status. Implementation, documentation, or a passing unit test alone is not enough to mark a release gate `PASS`; every `PASS` must point to executable evidence from the release candidate workload.

Allowed statuses: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `PASS`, `FAIL`.

Last audited: 2026-10-03 (Asia/Taipei)
Branch: `bootstrap/v0.1.0-alpha`  
Audited code commit: `414dfdf2feb0c3b74c17a4d513b625f2eb2f0de4`
Pull request: [#1](https://github.com/simplemind121/vocabulary-ingestion-engine/pull/1) (`OPEN`, `MERGEABLE`)  
Source PDF SHA256: `485771d63e747788d855d2ec033436239001f24a1d835d1e00a6ec9467c632fd`  
Database schema: `0007_gold_xlsx`

## Gate summary

| Gate | Status | Release evidence | Current blocker / next executable action |
|---|---|---|---|
| R0 — Repository / CI | PASS | Commit `414dfdf` passed local `ruff` plus 188 tests. Its push and PR CI both passed tests, Gold readiness validation, and the production-topology smoke test in [run 37093375079](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/37093375079) and [run 37093377733](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/37093377733). PR #1 is open and mergeable. | Keep subsequent commits green; any failure returns this gate to `FAIL` until repaired. |
| R1 — Gold Dataset | PASS | Pages 221, 330, 461, and 462 were explicitly re-reviewed and signed `HUMAN_VERIFIED` by reviewer `wangsanqiang`. Corpus readiness is again 30/30 with every required layout tag covered and no errors. The corrected Gold Sample Dataset v1 is frozen with manifest SHA256 `c24afe5e1403e920222ce3c3dc9e5389ae3197e996f0ba1029ef16429847f9d5`. | Treat the corrected annotations and manifest as immutable release truth. Any later change requires explicit re-review and a new manifest hash. |
| R2 — Gold Regression | PASS | Real PostgreSQL ProcessingRun `5d6557a5-b63c-47a8-b638-e86b412e5d7c` generated the committed 30-page predictions on the narrowed parser. `release_evidence/gold-benchmark-v1.json` is bound to manifest `c24afe5e…f9d5`; all 30 pages exact-match with OCR F1 `1.0`, segmentation F1 `1.0`, canonical field accuracy `1.0`, and no failed samples. The unchanged exact-match gate reports `PASS`. | Keep CI consuming the committed real-run predictions and forbid threshold or Gold-truth changes without explicit review. |
| R3 — Full-book E2E | PASS | Final real PostgreSQL run `5d6557a5-b63c-47a8-b638-e86b412e5d7c` completed G0–G6 on 1120/1120 pages after 6/6 source-identical OCR review decisions. It produced 23,458 SourceBlocks, 3,401 SourceEntries, 3,401 verified VocabularyEntries, 21,684 provenance records, 570 cross-page entries, zero unresolved cross-page entries, zero duplicate lemmas/source entries, and zero open reviews. Full ingest-to-finish was 273.471 s; the final queued pass was 123.689 s. Cgroup peaks were API 896,475,136, worker 527,380,480, PostgreSQL 351,047,680, object storage 275,746,816, and Redis 15,167,488 bytes (1.925 GiB conservative sum-of-service-peaks upper bound). Final persistent footprint was 939,100,629 bytes. | Preserve this run and its release as RC evidence; repeat only if code, source identity, render contract, or Gold truth changes. |
| R4 — Dataset Publication | PASS | PostgreSQL GoldRelease `13e45a80-ed86-4737-8dfe-7278c913630b` v1 contains 3,401 records. API and downloaded JSON/CSV/XLSX matched row-for-row and field-for-field. Artifact evidence: JSON 917,899 bytes (`b7ae1ec14d5640f2ef132ae94fe2e0aaf3d0b037fa826b9f415d28fabfce4feb`), CSV 411,105 bytes (`4651f86ef3c017c325cd951731599c8c857a329183e48b0e36462079ab5012ea`), XLSX 311,589 bytes (`e7f626ecc331bbb737cbfeb1ff13849ca8486f666452d94b0ee25f5dfabc43aa`). All 3,401 vocabulary rows have provenance; first/middle/last deterministic samples resolve to source pages and PDF SHA256. | Keep release artifacts immutable; any regenerated dataset must produce a new evidence set and pass R1–R4 again. |
| R5 — Production Deployment | PASS | Clean Ubuntu CI built the production image from commit `414dfdf`, applied migration `0007_gold_xlsx`, started PostgreSQL/Redis/worker/API/object storage, passed readiness and real Tesseract OCR, uploaded and queued two PDFs through the authenticated API, completed one automatically and one only after two explicit review decisions, published two Gold releases, and downloaded valid JSON/CSV/XLSX. The push and PR executions passed in [run 37093375079](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/37093375079) and [run 37093377733](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/37093377733). No source or database edit was used to make either application run pass. | Keep the executable Compose smoke green on every release-candidate commit. |
| R6 — Recovery / Operations | IN_PROGRESS | Restarting the isolated real-book Compose project preserved 1120 pages and 23,458 SourceBlocks; a forced worker exit (137) recovered without volume loss and retained all six review records. On clean Ubuntu, the `414dfdf` smoke checksummed PostgreSQL/object/application snapshots, deliberately polluted all three stores, restored them, removed stale state, preserved the expected objects, and returned API/worker readiness. Human-reviewed OCR reuse/protection and terminal retry behavior have regression tests. | Prove an immutable-image upgrade and snapshot rollback in a disposable environment, then verify schema, dataset version, provenance, and resolved human-review state after both transitions. A successful same-version restore alone is not `PASS`. |
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

## Release blockers in execution order

1. Complete immutable-image upgrade/rollback evidence with post-transition schema, dataset, provenance, and human-review verification.
2. Run the aggregate Release Gate on that immutable commit, resolve any operational failure without weakening gates, and create RC1 only after R0–R6 are all `PASS`.

## Final v0.1.0 release invariant

`G6 = PASS` and tag `v0.1.0` are forbidden until every R0–R7 gate above is `PASS`, the immutable RC commit/artifacts have passed the complete release workflow, and the required acceptance, benchmark, full-book, deployment, recovery, known-issues, image-digest, commit-SHA, schema-version, Gold-manifest-SHA256, and release-artifact-SHA256 evidence is recorded.
