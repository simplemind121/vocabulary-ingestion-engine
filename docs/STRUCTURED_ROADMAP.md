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

## Paid vision model

Allowed for hard pages only: pages whose checks fail after the free readers, or
that the operator selects. Each run declares a budget in advance and stops when
it is reached; token usage and cost are recorded per page. Keys stay in the
runtime environment and are never printed.

## Data

Book content stays out of this public repository. Fixtures in tests are
synthetic.
