# Source Media Report

Status: **IN_PROGRESS — waiting for human review.** Nothing in this report is a
release pass. Numbers marked *pre-review* come from the real 1120-page source
PDF processed by the committed pipeline; the PostgreSQL run that will back the
release is stopped at its Review Queue and has not reached the media stage yet.

Source PDF SHA256: `485771d63e747788d855d2ec033436239001f24a1d835d1e00a6ec9467c632fd`

## What counts as source media

Every raster image the publisher placed on a page. It is `SOURCE_MEDIA`: the
embedded stream is copied byte-for-byte out of the PDF, hashed, and stored
through the object storage adapter under `source-media/<document sha>/`.
PostgreSQL holds only metadata, relations and provenance. AI-generated imagery
would be `ENRICHMENT_MEDIA`, a separate namespace this pipeline never writes.

## How an image is bound to an entry

The book prints an illustration at the end of its entry, inside the band closed
by the horizontal rules between entries. `layout-band@1.0.0` binds an image
only when reading order and those rules agree:

| Situation | Result |
|---|---|
| Entry text above, rule between image and next headword | bound to that entry |
| Image at page top, entry text resumes below | bound to the entry continuing from the previous page |
| Image at page top, next headword below a rule | bound to the last entry of the previous page |
| Between a Word List title and its first entry | not vocabulary media (QR codes) |
| Covers ≥ 85 % of the page | not vocabulary media (page scan) |
| Anything else — no rules, rules on both sides, side-by-side entries, text overlapping the image, no entry context | `REVIEW_REQUIRED`, no entry assigned |

A human decision is never overwritten by a re-run, and a re-run never
duplicates media or changes a stored hash.

## Full book, pre-review

| Metric | Value |
|---|---|
| Pages scanned | 1120 / 1120 |
| Pages containing source media | 314 |
| Media detected / extracted / persisted | 374 / 374 / 374 |
| Bound to a SourceEntry and VocabularyEntry (auto) | 270 |
| Excluded as non-vocabulary | 101 (100 Word List QR codes on 50 title pages, 1 cover scan) |
| Unresolved, in the Review Queue | 3 (pages 5, 665, 816) |
| Missing media / missing artifact / missing SHA256 | 0 / 0 / 0 |
| Broken artifact / broken provenance | 0 / 0 |
| Entries with more than one image | 0 |

The three unresolved items are real and deliberate. Page 5 is a QR code in the
front matter, before any entry exists. Pages 665 and 816 each hold a single
illustration on an otherwise empty page with no separator rules, so the layout
cannot prove which entry owns it.

## Gold Sample, pre-review

12 of the 30 Gold pages contain source media, 15 images in total: 8 entry
illustrations (pages 30, 50, 90, 150, 180, 420, 458, 460), 6 Word List QR
codes (pages 82, 120, 463) and the cover (page 1). The other 18 pages must be
confirmed as `media_count = 0`. Pages 50 and 180 exercise the cross-page rule.

Human-verified so far: **0 / 30**. The Gold Source Media Fidelity Gate therefore
reports `FAIL` (`media_gold_not_human_verified`), as it must.

## What remains

1. Human media review of the 30 Gold pages (`http://127.0.0.1:8765/media`).
2. Human decisions on the run's Review Queue: 6 low-confidence OCR blocks, then
   the 3 unresolved images.
3. Regenerate media predictions and `release_evidence/source-media-full-book-v1.json`
   from the completed PostgreSQL run; freeze manifest 1.1; rerun every gate.
