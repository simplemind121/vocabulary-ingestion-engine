# Gold Benchmark Report

Gold Sample Dataset v1, manifest dataset version 1.1 (text + source media).

Manifest SHA256: `cbe2e7303cc96b647a3e6d961d72b2f361f4d8497ba5da0191283d816492e31e`
(`gold_samples/manifest_v1_1.json`). The text-only manifest `c24afe5e…f9d5` is
superseded and no longer passes the release Gate.

## Text

| Item | Value |
|---|---|
| Pages `HUMAN_VERIFIED` | 30 / 30 |
| Predictions | PostgreSQL run `a5ba88aa-2b04-4208-a8e8-cf9a70692c93` |
| OCR block F1 | 1.0 |
| Entry segmentation F1 | 1.0 |
| Canonical field accuracy | 1.0 |
| Exact-match pages | 30 / 30 |
| Gate | `PASS` |

Pages 300 and 750 were re-reviewed in this cycle: their earlier verified
annotations had merged `contrast` into `tunnel` and `bow` into `renew`. The
other 28 annotations are byte-identical to the previous freeze.

## Source media

| Item | Value |
|---|---|
| Gold pages checked | 30 / 30 |
| Pages with media / verified as zero media | 12 / 18 |
| Expected = detected = extracted = verified | 15 |
| Correct entry association | 15 / 15 |
| Unbound / unresolved / missing SHA256 | 0 / 0 / 0 |
| Human decisions | 15 × `APPROVE` |
| Gate | `PASS` |

The 15 items are 8 entry illustrations (pages 30, 50, 90, 150, 180, 420, 458,
460), 6 Word List QR codes (pages 82, 120, 463) and the cover (page 1).

The overlay for page 1 records its reviewer as `wangsanqaing`; the other 29
record `wangsanqiang`. It is a human sign-off and was left as entered.

Evidence: `release_evidence/gold-readiness-v1.json`,
`release_evidence/gold-benchmark-v1.json`, `release_evidence/gold-source-media-v1.json`.
