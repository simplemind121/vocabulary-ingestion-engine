# G6 production release Gate

G6 is an aggregate release decision, not a synonym for green unit tests. A tag
or manual Release Gate run can pass only when all of the following evidence is
valid for the same source, code, commit, and production image:

1. Exactly 30 Gold Sample v1 pages are explicitly `HUMAN_VERIFIED` and the
   deterministic frozen manifest matches their canonical JSON.
2. The real machine predictions exactly match those annotations at OCR block,
   entry segmentation, and canonical field layers. The benchmark report is
   bound to the frozen manifest SHA-256.
3. The source-bound 1120-page audit has complete page representation, every
   candidate parses, and every redacted review item is covered by explicit human
   verification. Its private report hash and audited pipeline source hash must
   match.
4. The production Compose topology passes image build, migrations, API and
   worker readiness, object storage, real Tesseract OCR, backup, destructive
   pollution, exact restore, and a real queued G0-G6 pipeline. The evidence is
   bound to the Git SHA and Docker image digest. Authenticated operational
   metrics must also report the completed run and persisted release.

The final decision is produced by `python -m app.g6_release_cli`. It is
fail-closed and emits `g6-release-report.json`. The GitHub Release Gate workflow
runs the production and Gold tracks independently, then permits the aggregate
job only after both succeed.

5. Every Gold page carries a human-verified source media overlay, the machine
   media predictions match it exactly, and the frozen manifest (dataset 1.1)
   binds both text and media ground truth.
6. The 1120-page source media pass is complete: every detected image is stored,
   hashed and traceable, with no unresolved, unbound or missing item, and its
   evidence is bound to the current media pipeline source hash.

## Current acceptance status

See `G6_ACCEPTANCE_REPORT.md`.
