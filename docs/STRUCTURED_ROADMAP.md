# Structured books roadmap

Goal: turn the engine from a vocabulary-book factory into a structured-data engine
for **books, textbooks and exam papers**. Office documents (invoices, forms,
contracts) are out of scope.

## Principle

Reading, structuring and checking are separate steps.

1. **Evidence**: OCR readers vote on what is printed and where. Evidence never
   decides structure.
2. **Claims**: a producer (rules, a local model, a paid vision model, or a person
   writing a page plan) proposes a structured page. Every producer writes the
   same document model.
3. **Checks**: a claim must agree with the evidence. Words no reader read
   ("invented") and printed lines the claim leaves out ("dropped") block it.
   Printed ink that no reader read at all ("unread ink") is routed to review.

## Layers

| Layer | What it holds |
|---|---|
| Evidence | Voted lines with page and box, the scan's hidden text layer, figure regions, unread-ink regions |
| Document model | One tree per page: sections, paragraphs, examples, tables, columns, panels, figures, exercises, items, word banks, answer keys, index entries, cross-references; each node points at the lines it came from |
| Producers | Rule templates per book profile, page plans, a local OCR/layout model, a paid vision model for hard pages only, with a per-book budget |
| Checks and review | Invented/dropped/unread-ink checks, coverage, schema validation, review queue, Gates |
| Outputs | Profile exporters (vocabulary, grammar textbook, exam paper) and generic JSON/Markdown/CSV/XLSX |

## Phases

### Phase 1: document model and checks inside the engine
- Unread-ink detection: find printed text regions on the page image that no
  voted line covers. Free, local, no model.
- The page document model (`vie-doc/1`) stored per run and page, with producer,
  version and check results.
- The page-plan compiler and checker move into the engine; existing structured
  pages can be imported.
- Grammar textbook exporter.

Acceptance: the engine reproduces the published grammar book byte for byte, and
flags every page where lines are known to have been missed (the remedial check of
2026-10-18 found them on 95, 131, 143 and 149, among others).

### Phase 2: local layout and a second kind of reader
- A local document model (GLM-OCR or similar) as a region reader and drafting
  producer; a layout detector for regions and reading order.

Acceptance: on 20 pages with known misses, every missed line is flagged and no
invented text gets through the checks.

### Phase 3: exam papers and schema-driven extraction
- An exam-paper profile: sections, questions, options, passages, answers,
  explanations, scores, each traceable to the page.
- A target schema supplied by the operator is filled with traced values.

Acceptance: a full exam paper exports with every question, option and answer
linked to its source lines.

### Phase 4: more book profiles
- Textbooks with large tables, dictionaries, readers. Each profile gets Gold
  samples, regression tests and a quality report.

## Reading layer: technical path (decided 2026-10-19)

Two kinds of reader check each other: PaddleOCR reads **lines** (where each
line is and what it says); GLM-OCR, a document model reached over the Z.ai API
(`layout_parsing`, model `glm-ocr`), reads **regions** (text, table, image and
formula areas with normalized boxes, text as Markdown, tables as HTML). They
fail in different ways, which is what makes the cross-check worth having.

| Reader | Level | Role |
|---|---|---|
| PaddleOCR (local) | line | defines the lines and their boxes |
| GLM-OCR (API) | region | second reading of every line, layout, tables, figures |
| PDF hidden text layer | word | third reading where a scan has one |
| macOS Vision (host helper) | line | optional extra vote |
| Vision model (paid) | line | arbitration of disputed lines only |

Steps per page:
1. Render (as now).
2. GLM-OCR regions, stored with the page (label, box, content).
3. PaddleOCR lines (as now).
4. Alignment: each line is placed in the region that contains it; inside a
   region the region's words are aligned to its lines in reading order (word
   sequence alignment), giving each line its GLM reading. Region boxes also
   replace the page-wide band used today, which mixes the two columns of a
   two-column page.
5. Vote character by character (as now, one more reading).
6. Gaps: region words aligned to no line become unread text (as the text
   layer does today, now also for scans without a layer); lines no region
   supports keep a single-reader status.
7. Disputes go to the existing arbitration, with the GLM reading as a candidate.
8. Later, structure drafting: the region labels, Markdown and table HTML draft a
   page tree that then passes the same checks.

Engineering:
- `GlmOcrReader`: one request per page image (base64 PNG); the raw response is
  cached per document hash and page, so a page is paid for once; retries with
  backoff, bounded concurrency, timeouts.
- Budget: a run declares a token or cost limit; when it is reached the reader
  abstains on the remaining pages. Usage is recorded per page.
- The key lives in the runtime environment (`VIE_GLM_OCR_API_KEY`), stored
  through the hidden-input helper, never printed or logged.
- Sending pages to an external service is opt-in per document.

Evaluation: the 399 hand-structured pages of the grammar book are the Gold set.
Each reader is measured against them (word recall and precision, lines
recovered that PaddleOCR missed, text no page contains), plus cost and time per
page. Pilot first: 20 pages with known misses, 10 ordinary pages, 10 pages of a
Chinese-English word book. Adopt if at least 95% of the known misses are
recovered, no invented text survives the checks, and a book costs under $1.

Reinforcements (review of 2026-10-19 against current practice):
1. **Recover, not only report.** Unread text becomes a proposed line: its region
   is cropped and read again by the line reader, the readings are voted, and a
   confirmed line joins the page like any other.
2. **Held-out evaluation.** The Gold pages are split once: every fifth unit
   (and every fifth other page) is held out and never looked at while tuning.
   Metrics follow common practice: character error rate and normalized edit
   distance for text, TEDS for tables, edit distance of reading order, IoU for
   figure boxes; word precision and recall stay as order-free measures.
3. **Weighted voting.** Each reader's reliability is measured on the
   development pages by kind of text (words, digits, punctuation) and used to
   weigh its vote, so two readers that differ do not always end in a dispute.
4. **Swappable document models.** GLM-OCR sits behind a document-model reader
   interface (PaddleOCR-VL, MinerU and others can take its place); the model
   version and a hash of every response are recorded, and a version change
   reruns the Gold regression.
5. **Formatting and hard content are measured.** Bold, italic and underline
   are treated as readings too; IPA, handwritten answers and symbols are scored
   separately.
6. **Character-level provenance** for exam papers: each field points at a line
   and a character span.
7. **PaddleOCR-VL as primary reader** is evaluated early, on rented GPU time if
   needed.

Order: (1) evaluation harness, held-out split and per-reader baseline;
document-model reader interface with version records; recovery of unread lines.
(2) GLM-OCR reader with cache and budget, then the pilot. (3) Region alignment,
weighted voting. (4) Layout: figures, tables, reading order. (5) Structure
drafting, measured on the exam-paper profile.

### GLM-OCR pilot (2026-10-20, 30 grammar pages)

| Pages | GLM-OCR word P / R | Voted lines word P / R |
|---|---|---|
| 20 with known misses | 0.990 / 0.948 | 0.969 / 0.927 |
| 10 ordinary | 0.998 / 0.952 | 0.972 / 0.963 |

- Of the 791 Gold words the voted lines miss on these pages, GLM-OCR read 752 (95%).
- 81,889 tokens for 30 pages (about 2,700 per page; a whole book well under $0.10); 3 to 15 seconds a page.
- Boxes come in pixels of the image sent, not fractions as documented (handled).
- A region often holds several printed lines run together without line breaks:
  word alignment to lines is required, splitting on line breaks is not enough.
- Pictures are not read: text inside an illustration (speech bubbles) comes back
  as an empty image region, also when the picture is sent on its own. Bubbles
  stay with the text layer and line recovery.

## Paid vision model

Allowed for hard pages only: pages whose checks fail after the free readers, or
that the operator selects. Each run declares a budget in advance and stops when
it is reached; token usage and cost are recorded per page. Keys stay in the
runtime environment and are never printed.

## Data

Book content stays out of this public repository. Fixtures in tests are
synthetic.
