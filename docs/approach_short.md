# CT-200 Document Intelligence System: short approach

## In one sentence

The system turns the supplied CT-200 PDF into a versioned section tree, then
uses selected section text to generate traceable QA test ideas.

## End-to-end flow

```text
PDF
  → extract headings, text, lists, and tables
  → save a versioned section tree
  → select exact section snapshots
  → generate and validate QA test ideas
  → compare them with later PDF versions
```

## 1. Parse the PDF

The supplied manuals have selectable text, so the parser normally uses
`pdfplumber` for text position, bold styling, and table cells. Image-only
pages use Tesseract OCR instead. `pdfplumber` was chosen because PyMuPDF could
not run in this Windows environment.

### How headings become a tree

A line is a heading only if it is both:

- CT-200-style numbered, such as `3.2` or `2.1.1.1`; and
- bold in the PDF.

This avoids turning the numbered clinical-classification list into sections.
The parser keeps a stack of open headings. A new heading is added below the
closest real parent that is still open. Text remains under the current heading
until another heading is found, even when a page break occurs.

The PDF's order is preserved. For example, `3.4` stays before `3.3` because
that is how it appears in the manual.

### Numbering is not the same as depth

`nominal_level` is based on the visible number. `depth` is the actual position
in the extracted tree.

```text
2.1 General Specifications          depth 2
└── 2.1.1.1 Battery Life...          nominal level 4, depth 3
```

There is no real `2.1.1` heading in the PDF, so the parser does not invent
one. It records `numbering_gap=true` instead.

### Other extracted content

- Normal paragraphs become `text` blocks.
- The clinical classification becomes a five-item `list` block.
- A grid becomes a `table` block only when cell boundaries are detected.
- Smaller table fragments inside a real table are discarded.
- The unnumbered cover title is saved as document metadata.

## 2. Store and browse the result

SQLite stores the document tree, versions, nodes, and selections. Every PDF
ingestion creates a new set of immutable snapshots; it never overwrites the
previous version. MongoDB stores the nested LLM generation records.

The API supports:

- listing top-level sections for a version;
- reading one node, its children, full text, and content hash;
- searching headings and body text; and
- viewing whether a node changed between versions, with a short diff.

## 3. Match sections across versions

The matcher uses the already-matched real parent plus a case-insensitive,
whitespace-normalised heading. It does not use section number as an identity
key, because the PDF itself has a numbering gap.

If two possible matches are indistinguishable, the system creates a new
logical node rather than guessing. This may over-report a new section, but it
avoids connecting history to the wrong section.

## 4. Generate QA ideas safely

A user selection contains exact node snapshots, so a later PDF upload cannot
silently change the text being sent to the LLM. The prompt receives only the
selected text and requests three to five JSON test cases. Each case needs a
title, rationale, preconditions, steps, expected result, and source node IDs.

Pydantic validates the response. Invalid JSON, missing fields, a wrong number
of cases, or unselected source IDs trigger one repair attempt. If it still
fails, the system saves `generation_failed`, the raw responses, and the error.
It does not make up a successful result.

Submitting the same selection with unchanged text returns the earlier result
instead of calling the LLM again. `force_regenerate=true` is available when a
new result is deliberately needed.

## 5. Flag stale generated results

Each generation saves the source node IDs and body-text hashes. When it is
retrieved later, the service compares those hashes with the latest matching
node snapshots:

- missing source node → stale;
- changed source hash → stale; and
- unchanged hash → still current.

The response explains the reason and the node API can show a short text diff.
This is deliberately conservative: a typo fix and a changed pressure
threshold both mark a result stale. For this type of manual, asking for review
is safer than automatically approving an older test case.

## Limits

The parser is tuned to the supplied CT-200 layout. A very different layout or
a poor scan could make a heading, list, or table harder to classify. Figures
are not extracted as structured content. With more time, I would add
per-block coordinates and confidence scores, then flag uncertain extraction
and version matches for manual review.
