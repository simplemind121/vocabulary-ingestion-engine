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

Human-verified entry-bearing pages (`NORMAL`, `BOUNDARY_ENTRY`, or
`CROSS_PAGE_ENTRY`) require non-empty entries and vocabulary. A verified table,
index, front-matter, or image-only page may truthfully contain zero entries; it
must still contain reviewed source blocks and must never be padded with invented
vocabulary merely to satisfy the gate.

A page is benchmark-eligible only when `review_status` is `HUMAN_VERIFIED`.

No benchmark score may be described as Gold Sample Dataset v1 unless all 30 pages pass manifest validation.

## Build the private review packet

After the confirmed source PDF has been ingested and its processing run contains
the 30 selected pages, build the side-by-side reviewer packet with:

```bash
python -m app.gold_review_packet_cli RUN_ID
```

For the confirmed source PDF, the same packet can be produced without rendering
all 1120 pages into the database first:

```bash
python -m app.gold_review_packet_cli --pdf /private/path/source.pdf
```

The default output is `data-private/gold-review-packet-v1/index.html`. It copies
the 30 copyrighted page renders into that ignored private directory, verifies
every render against the frozen SHA-256 registry, and shows the source page next
to the machine annotation plus automatic review flags. All emitted annotations
remain `DRAFT`; this command cannot assign a reviewer or create
`HUMAN_VERIFIED` ground truth.
