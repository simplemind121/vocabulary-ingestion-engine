# Gold Sample Dataset v1

This directory defines the regression contract for the first 30-page human-verified corpus.

The repository may contain manifests and derived ground-truth annotations that are legally safe to publish. Copyrighted source PDFs and page images MUST NOT be committed unless redistribution rights are confirmed.

## Required coverage

The 30 selected pages MUST collectively cover:

- normal vocabulary pages
- double-column layout
- IPA-dense content
- pages containing images
- special/nonstandard layout
- entries at page header/footer boundaries
- cross-page entries
- tables
- index pages
- OCR-hard pages

## Acceptance contract

Every manifest page requires:

- immutable source document SHA-256
- source page number
- page-image SHA-256
- layout tags
- ground-truth annotation path
- annotation review status
- reviewer identity or stable reviewer pseudonym
- annotation schema version

A page is benchmark-eligible only when `review_status` is `HUMAN_VERIFIED`.

No benchmark score may be described as Gold Sample Dataset v1 unless all 30 pages pass manifest validation.
