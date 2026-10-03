# G6 Acceptance Report

Candidate: `v0.1.0-rc2`. The aggregate G6 decision is produced by the
tag-triggered Release Gate (`python -m app.g6_release_cli --require-pass`) on
the tagged commit and its production image; this report lists the evidence that
Gate consumes.

| Evidence | Source | State |
|---|---|---|
| Source identity | `gold_samples/source_document.json` | 1120 pages, SHA256 `485771d6…32fd` |
| Gold text | `gold_samples/annotations/` | 30/30 `HUMAN_VERIFIED` |
| Gold source media | `gold_samples/media_annotations/` | 30/30 `HUMAN_VERIFIED`, 15 items |
| Frozen manifest 1.1 | `gold_samples/manifest_v1_1.json` | `cbe2e7303cc96b647a3e6d961d72b2f361f4d8497ba5da0191283d816492e31e` |
| Text regression | `benchmarks/gold_sample_v1/predictions/` | 30/30 exact match |
| Media regression | `benchmarks/gold_sample_v1/media_predictions/` | 15/15 correct |
| Full-book text audit | `release_evidence/full-book-audit-v1.json` | 3,540 / 3,540 parsed, bound to the pipeline hash |
| Full-book source media | `release_evidence/source-media-full-book-v1.json` | 374 / 374, 0 unresolved, bound to the media pipeline hash |
| Production smoke | Release Gate artifact | built per commit |

G6 fails closed if any of these is missing, stale for the code, or inconsistent
with the others. Related reports: `FULL_BOOK_RUN_REPORT.md`,
`GOLD_BENCHMARK_REPORT.md`, `SOURCE_MEDIA_REPORT.md`, `KNOWN_ISSUES.md`.
