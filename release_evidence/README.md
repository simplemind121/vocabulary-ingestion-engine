# Release evidence

This directory contains copyright-safe, machine-checkable evidence for the G6
release Gate. Source PDFs, rendered pages, OCR excerpts, and the complete
full-book audit remain under ignored `data-private/` storage.

`full-book-audit-v1.json` binds the published summary to:

- the confirmed source document SHA-256 and page count;
- the SHA-256 of the private complete audit report;
- the SHA-256 of every extraction, segmentation, and parsing source file used by
  the audit;
- redacted Review Queue identities without copyrighted source excerpts.

Any change to the audited pipeline makes CI fail until the real 1120-page audit
is rerun and this evidence is regenerated:

```bash
python -m app.full_book_audit_cli /private/path/source.pdf \
  --output data-private/full-book-audit.json
python -m app.full_book_evidence_cli data-private/full-book-audit.json \
  --output release_evidence/full-book-audit-v1.json
python -m app.full_book_evidence_check_cli \
  release_evidence/full-book-audit-v1.json \
  --source-metadata gold_samples/source_document.json
```

Redacted review items remain blocking until their pages have explicit valid
`HUMAN_VERIFIED` Gold annotations. Regeneration cannot mark a review resolved.
