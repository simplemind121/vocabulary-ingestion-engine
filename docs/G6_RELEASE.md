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

## Current source acceptance status

The latest source-bound audit represents all 1120 pages: 1119 through the native
text layer and the scanned cover through Tesseract. It contains 23,458 source
blocks, 3,401 parsed candidates, and 569 cross-page candidates. Three
low-confidence OCR blocks on source page 1 remain in the redacted Review Queue.
They are not silently accepted; the source-page Gold sign-off must resolve them.

The production topology smoke test passes locally. The G6 Gate remains blocked
until the real 30-page corpus is signed by a human and the resulting exact-match
benchmark succeeds.
