# VIE v0.1 Release Checklist

This file is the single source of truth for Vocabulary Ingestion Engine v0.1 release status. Implementation, documentation, or a passing unit test alone is not enough to mark a release gate `PASS`; every `PASS` must point to executable evidence from the release candidate workload.

Allowed statuses: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `PASS`, `FAIL`.

Last audited: 2026-10-02 (Asia/Taipei)
Branch: `bootstrap/v0.1.0-alpha`  
Audited code commit: `d55e54303244b649d603d0b028466d52613f8bc5`
Pull request: [#1](https://github.com/simplemind121/vocabulary-ingestion-engine/pull/1) (`OPEN`, `MERGEABLE`)  
Source PDF SHA256: `485771d63e747788d855d2ec033436239001f24a1d835d1e00a6ec9467c632fd`  
Database schema: `0007_gold_xlsx`

## Gate summary

| Gate | Status | Release evidence | Current blocker / next executable action |
|---|---|---|---|
| R0 — Repository / CI | PASS | Commit `d55e543` contains the refreshed real-run Gold DRAFT artifacts and passed local `ruff` plus 186 tests. Its push and PR CI both passed tests, Gold readiness validation, and the production-topology smoke test in [run 36910563523](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/36910563523) and [run 36910572010](https://github.com/simplemind121/vocabulary-ingestion-engine/actions/runs/36910572010). | Keep subsequent commits green; any failure returns this gate to `FAIL` until repaired. |
| R1 — Gold Dataset | PASS | All 30 source-bound annotations were explicitly signed `HUMAN_VERIFIED` by reviewer `wangsanqiang`; corpus readiness reports 30/30 verified, all required layout tags covered, and no errors. Gold Sample Dataset v1 is frozen with manifest SHA256 `d09d2782dea239613083f6ce938e260c97c1f87c0138ec378ba00a76e6e65360`. | Treat the annotations and `gold_samples/manifest_v1.json` as immutable release truth. Any change requires a new reviewed dataset version and manifest hash. |
| R2 — Gold Regression | FAIL | The first benchmark of the real persisted-run predictions against the frozen Gold truth passed 27/30 pages. OCR and segmentation are exact (`1.0`); canonical field accuracy bottoms at `0.9333333333333333`. Pages 50, 60, and 462 fail only on definitions. Evidence: `release_evidence/gold-benchmark-pre-stabilization-v1.json`. | Fix only the benchmark-proven canonical definition parsing defects, generate fresh predictions from a new real run, and require the exact-match regression gate to pass without changing frozen truth or thresholds. |
| R3 — Full-book E2E | IN_PROGRESS | Real PostgreSQL ProcessingRun `cfb68afa-6b9f-4992-b86d-0db27f950014` completed in 114.8 seconds after six named human OCR reviews. G0–G6 all passed; 1120/1120 pages produced 23,458 SourceBlocks, 3,401 SourceEntries, 3,401 AUTO_VERIFIED VocabularyEntries, 21,684 provenance records, and zero open reviews. | This is the pre-Gold baseline, not RC evidence. Complete R1/R2, fix any benchmark defects, rerun the same full-book workload, and record the required failure, duplicate, cross-page-unresolved, duration, peak-RAM, and disk metrics in `FULL_BOOK_RUN_REPORT.md`. |
| R4 — Dataset Publication | IN_PROGRESS | PostgreSQL GoldRelease `972d765a-6d3b-4d24-bf8d-33ad30c42a7a` v1 contains 3,401 records. Real artifacts exist: JSON 912,204 bytes (`d49ada6c…`), CSV 405,410 bytes (`a87178aa…`), and XLSX 308,118 bytes (`fb180356…`). | After Gold-driven parser stabilization, rebuild the release on the hardened image, verify JSON/CSV/XLSX/API count and field consistency, and prove sampled reverse provenance to page/document/source SHA256. |
| R5 — Production Deployment | IN_PROGRESS | The isolated Compose runtime currently reports API live version `0.1.0-alpha.4` and readiness checks `database=ok`, `redis=ok`, `storage=ok`. PostgreSQL, Redis, worker, API, and object storage run with persistent volumes, and migration `0007_gold_xlsx` completed. | Execute the documented workflow in a clean ordinary Ubuntu VM/VPS from clone through upload, processing, review, publish, and export without manual database/source edits or undocumented commands. |
| R6 — Recovery / Operations | IN_PROGRESS | Restarting the isolated Compose project preserved the real 1120 pages and 23,458 SourceBlocks. A forced worker exit (137) was recovered without volume loss; the same queued run then completed with six human review records intact. Human-reviewed OCR reuse/protection and terminal retry behavior have regression tests. | Execute and record the remaining failure matrix, then perform PostgreSQL plus object-artifact backup and restore into a clean environment. Verify counts, dataset version, provenance, human review state, upgrade, migration, and rollback. A successful backup alone is not `PASS`. |
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

Result: `READY_TO_FREEZE`; 30 annotations, 30 HUMAN_VERIFIED, publishing allowed. Frozen manifest SHA256: `d09d2782dea239613083f6ce938e260c97c1f87c0138ec378ba00a76e6e65360`.

### R3 full-book evidence commands and audited result

```bash
.venv/bin/python -m app.full_book_evidence_check_cli \
  release_evidence/full-book-audit-v1.json \
  --source-metadata gold_samples/source_document.json
```

Result: `PASS` for evidence integrity. The persisted workload has since completed, but must be rerun after the frozen Gold benchmark drives any required parser fixes.

Persisted runtime evidence:

- Document ID: `440419a6-79a5-4480-8f13-c20e576b70bb`
- DocumentVersion ID: `22f520e0-d554-4004-8c08-16dfc7c7d738`
- ProcessingRun ID: `cfb68afa-6b9f-4992-b86d-0db27f950014`
- G0: `PASS`
- G1–G6: `PASS`
- Pages: 1120
- SourceBlocks: 23,458
- Resolved / open review tasks: 6 / 0
- SourceEntries / VocabularyEntries / ProvenanceRecords / GoldReleases: 3,401 / 3,401 / 21,684 / 1
- Vocabulary verification: 3,401 `AUTO_VERIFIED`, 0 `HUMAN_VERIFIED`

### R5 runtime probes

```bash
curl --fail http://127.0.0.1:8766/health/live
curl --fail http://127.0.0.1:8766/health/ready
docker compose --env-file .env.gold-runtime -p vie-gold-runtime ps
```

Local runtime evidence is useful hardening evidence but is not a substitute for the required clean Ubuntu deployment.

## Release blockers in execution order

1. Fix the three benchmark-proven canonical definition failures without changing frozen Gold truth or thresholds.
2. Generate fresh predictions from a new real 1120-page run and pass the exact-match Gold regression gate.
3. Record the new full-book workload as final RC evidence, including failure, duplicate, cross-page-unresolved, duration, peak-RAM, and disk metrics.
4. Verify the resulting PostgreSQL dataset and JSON/CSV/XLSX/API outputs for consistency and reverse provenance.
5. Complete clean Ubuntu deployment plus verified backup/restore/upgrade/rollback before creating RC1.

## Final v0.1.0 release invariant

`G6 = PASS` and tag `v0.1.0` are forbidden until every R0–R7 gate above is `PASS`, the immutable RC commit/artifacts have passed the complete release workflow, and the required acceptance, benchmark, full-book, deployment, recovery, known-issues, image-digest, commit-SHA, schema-version, Gold-manifest-SHA256, and release-artifact-SHA256 evidence is recorded.
