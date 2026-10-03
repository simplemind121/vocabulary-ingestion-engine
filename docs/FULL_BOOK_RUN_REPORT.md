# Full-book Run Report

Source: 雅思词汇词根+联想记忆法：乱序版, 1120 pages,
SHA256 `485771d63e747788d855d2ec033436239001f24a1d835d1e00a6ec9467c632fd`.

Run on the production Compose topology (PostgreSQL, Redis, worker, API,
S3-compatible object storage, Tesseract), schema `0008_source_media`.

| Item | Value |
|---|---|
| ProcessingRun | `a5ba88aa-2b04-4208-a8e8-cf9a70692c93` |
| Final status | `COMPLETED` |
| Gates | G0, G1, G2, G3, G3_MEDIA, G4, G5, G6 all `PASS` |
| Pages | 1120 / 1120 |
| SourceBlocks | 23,458 |
| SourceEntries / VocabularyEntries | 3,540 / 3,540 |
| Cross-page entries | 577 |
| ProvenanceRecords | 23,134 |
| Vocabulary verification | 3,540 `AUTO_VERIFIED` |
| Duplicate lemmas | 0 |
| Review tasks resolved / open | 9 / 0 |
| GoldRelease | `66055ec7-d539-401b-bc92-ecad2235e9f6`, v1, schema 1.1, 3,540 records |

## Human review during the run

All nine decisions were made by reviewer `wangsanqiang` in the web Review UI.

- 6 low-confidence OCR blocks: pages 1 (×3), 972, 1096 accepted with corrected
  text; page 665 discarded as noise.
- 3 source media associations: page 5 marked not vocabulary media; page 665
  bound to `evolve`; page 816 bound to `insert`.

## Source media

| Metric | Value |
|---|---|
| Pages scanned | 1120 / 1120 |
| Pages containing source media | 314 |
| Detected / extracted / persisted | 374 / 374 / 374 |
| Bound to SourceEntry and VocabularyEntry | 272 (270 automatic, 2 human) |
| Excluded as non-vocabulary | 102 (100 Word List QR codes, cover scan, front-matter QR) |
| Unbound / unresolved / missing | 0 / 0 / 0 |
| Broken artifact / broken provenance | 0 / 0 |

Every one of the 374 stored objects was fetched back through the API and its
SHA256 matched the recorded hash. Evidence: `release_evidence/source-media-full-book-v1.json`.

## Published dataset

| Format | Bytes | SHA256 |
|---|---|---|
| JSON | 2,656,606 | `1f746429550a6880cf2740d7d5bc106bf1fd43d6c9b3651fb837b91e4687dda4` |
| CSV | 522,621 | `2cc93a325a5d46888c18fa8f7a3c5591fdbf3b6caaa01595335edd72dac3f289` |
| XLSX | 410,469 | `383dc7b23b3e4b79ab64b0aedb8ab7bf586e2102dd1d21d3edcc2057a709266e` |

The API dataset equals the downloaded JSON; CSV equals XLSX row for row; JSON and
CSV agree on id, lemma, definitions and source media for all 3,540 records.
272 records carry source media, 66 carry more than one pronunciation, 75 have
no IPA because the book prints none, and all 3,540 carry their source entry and
source pages.

## Incident during the run

The third resume of the run failed with a foreign key violation and left the
run in `RUNNING`: a hybrid run re-extracted native blocks that entries already
referenced. No data was changed (the transaction rolled back). The defect was
fixed, covered by tests, deployed, the run status was reset to `FAILED` by an
operator SQL update, and the run was queued again and completed. The runtime
database was backed up before the schema upgrade.
