# Gold Sample Benchmark Contract v1.0

The benchmark is the release gate for the Vocabulary Ingestion Engine. A green unit-test suite is necessary but is not sufficient evidence that a scanned vocabulary book has been reproduced faithfully.

## Dataset gate

The Gold Sample manifest must contain exactly 30 human-verified pages and cover all required layout classes defined by `app.services.gold_sample.REQUIRED_LAYOUT_TAGS`.

Each sample must preserve document SHA-256, page number, rendered page SHA-256, layout tags, annotation schema version, reviewer identity/status, and the path to immutable ground truth.

## Layered evaluation

The benchmark intentionally reports three independent layers:

1. `OCR_BLOCK`: normalized recognized block text compared as a multiset. Reports precision, recall, F1, and exact match.
2. `ENTRY_SEGMENTATION`: `(lemma, raw_text)` entry boundaries compared as a multiset. This catches merges, splits, missing entries, and cross-page boundary drift even when OCR text itself is correct.
3. `CANONICAL_EXTRACTION`: canonical vocabulary fields are aligned by lemma and measured field-by-field. v1 measures lemma, display form, IPA, part of speech, and definition.

## Release rule

`PASS` currently means exact match at all three layers. Approximate F1/accuracy values are diagnostic metrics only and cannot turn a non-exact run into PASS.

This strict rule is deliberate for the first industrial baseline: the project goal is a reproducible, auditable database rather than an opaque OCR score. Future schema versions may introduce reviewed tolerances, but any relaxation must be explicit, versioned, and regression-tested.

## Interpretation

A failure must identify the layer that drifted. For example, OCR may remain exact while segmentation fails because one entry is missing; canonical extraction may fail because an IPA or definition differs even when OCR and boundaries are exact. This separation prevents downstream correctness from hiding upstream errors and provides a concrete repair target.

## Next integration

The next stage connects persisted processing runs and Gold Sample annotation JSON to this pure benchmark core, emits a machine-readable benchmark artifact, and makes the Gold Sample gate executable in CI once the 30-page human-verified dataset is populated.
