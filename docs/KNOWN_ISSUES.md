# Known Issues

## Open

- **`v0.1.0-rc1` is superseded.** It was cut on evidence now known to be wrong
  (3,401 entries, no source media). The tag is left untouched.
- **262 automatic media bindings are not individually human-checked.** They use
  the rule that was correct on all 8 Gold illustrations.
- **One Gold media overlay (page 1) records its reviewer as `wangsanqaing`.**

## Fixed in this cycle

- **139 entries were silently merged into their predecessors.** A headword
  printed alone on a bold line (several pronunciations, or none printed) did not
  match the headword rule. The book has 3,540 entries, not 3,401. Gold page 300
  (`contrast` inside `tunnel`) and page 750 (`bow` inside `renew`) had been
  human-verified with the same error, so the exact-match regression could not
  see it.
- **Second pronunciations and senses were dropped.** Only the first of each
  reached the database. All are now stored with provenance.

- **A reviewed run could resume only once.** The third pass re-extracted native
  blocks already referenced by entries, failed on a foreign key, and left the
  run stuck in `RUNNING`.

## Accepted limitations in v0.1.0

- The Gold benchmark compares the first pronunciation, part of speech and
  definition of an entry. Additional ones are stored and exported but not
  benchmarked.
- 75 entries have no IPA because the book prints none for them.
- Source media detection covers embedded raster images. This book has no vector
  illustrations; a book that draws them as vector paths would need a renderer.
- Image captions are not OCR-checked against the bound lemma. Association rests
  on layout geometry plus human review of the Gold pages.
- Media association assumes single-column entries. Side-by-side entries are
  detected and sent to review rather than bound.
