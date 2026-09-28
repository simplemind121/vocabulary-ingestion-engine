# Gold Sample Dataset v1

This directory is the regression benchmark contract for Vocabulary Ingestion Engine.

## Purpose

The benchmark measures whether OCR, layout, segmentation, structured extraction, validation, review routing, provenance, and Gold publication preserve the source faithfully.

## Dataset policy

- Source PDFs are not committed unless redistribution rights are explicitly established.
- `manifest.yaml` records source identity and benchmark scope.
- Ground truth is human-verifiable SOURCE DATA only.
- ENRICHMENT DATA is forbidden in source ground truth.
- Every asserted source field requires page/region provenance.
- Ambiguous content is marked for review rather than guessed.

## Gold Sample v1 composition

Batch A contains the first 10-page scanned vocabulary sample. Additional batches will expand the benchmark toward the planned ~30-page coverage, including double-column, cross-page entries, tables/images, skew, low contrast, and other difficult layouts.

## Required regression dimensions

1. Page representation / silent page loss
2. OCR character and token fidelity
3. Entry boundary precision/recall
4. Required-field extraction
5. IPA preservation
6. Chinese definition preservation
7. Example/mnemonic/derivative/collocation classification
8. Field-level provenance completeness
9. Review routing for uncertainty
10. Gold invariant: unresolved records = 0

A parser/OCR/model upgrade is not accepted merely because aggregate output looks better. P0 regressions in source integrity, traceability, schema validity, or unresolved-record handling block promotion.
