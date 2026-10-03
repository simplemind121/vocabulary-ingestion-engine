# Source Media Report

Status: **PASS on the release run.** Numbers below come from PostgreSQL run
`a5ba88aa-2b04-4208-a8e8-cf9a70692c93` and the human-verified Gold overlay.

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

## Full book

| Metric | Value |
|---|---|
| Pages scanned | 1120 / 1120 |
| Pages containing source media | 314 |
| Media detected / extracted / persisted | 374 / 374 / 374 |
| Bound to a SourceEntry and VocabularyEntry | 272 (270 by layout, 2 by human review) |
| Excluded as non-vocabulary | 102 (100 Word List QR codes on 50 title pages, cover scan, front-matter QR) |
| Unbound / unresolved / open reviews | 0 / 0 / 0 |
| Missing media / missing artifact / missing SHA256 | 0 / 0 / 0 |
| Broken artifact / broken provenance | 0 / 0 |
| Entries with more than one image | 0 |
| SHA256 over the ordered media hashes | `19485b40f8a12f4039462d4e3bf87416b8ffd6e41eacdcf3b52356e8e8410b82` |

Three items could not be proven by layout and were decided by reviewer
`wangsanqiang`: page 5 (front-matter QR code) is not vocabulary media; the lone
illustrations on pages 665 and 816 belong to `evolve` and `insert`.

All 374 stored objects were read back through the API and matched their
recorded SHA256. Per-item hashes, roles and lemmas are in
`release_evidence/source-media-full-book-v1.json`; the images themselves are not
committed.

## Gold Sample

12 of the 30 Gold pages contain source media, 15 images: 8 entry illustrations
(pages 30, 50, 90, 150, 180, 420, 458, 460), 6 Word List QR codes (pages 82,
120, 463) and the cover (page 1). The other 18 pages are verified as
`media_count = 0`. Pages 50 and 180 exercise the cross-page rule.

Human-verified: 30 / 30 pages, 15 / 15 items approved, 15 / 15 machine
associations correct. Gold Source Media Fidelity Gate: `PASS`.

## Association quality

Of 272 entry illustrations, 270 were bound by the layout rule and 2 by a human.
The human-reviewed Gold sample covers 8 of the 270 automatic bindings, all
correct. The remaining 262 rest on the same rule and are not individually
human-checked; captions inside the images are not OCR-verified against the
lemma (see `KNOWN_ISSUES.md`).
