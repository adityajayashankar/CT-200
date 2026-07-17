Exit code: 0
Wall time: 0.2 seconds
Output:
# CT-200 Document Intelligence System: approach

## What it does

The service turns the supplied CT-200 PDF into a searchable section tree. A
user can select saved section snapshots and ask an LLM for three to five QA
test ideas. The source text and document version remain attached to every
generation, so later document changes can be identified.

This is intentionally built for the supplied CT-200 manuals, not as a general
PDF understanding product.

## Parsing the PDF

The manuals are born-digital, so the normal path uses `pdfplumber` for text
positions, font styling, and table cells. I used it instead of PyMuPDF because
PyMuPDF's native extension was blocked by Windows Application Control in this
workspace. Image-only pages fall back to Tesseract OCR at 300 DPI.

A heading must have both CT-200-style numbering and bold text. This prevents
the numbered clinical-classification list from being mistaken for sections.
The parser keeps a stack of open headings. New headings close headings at the
same or deeper numbered level, then attach below the closest real parent still
open. Body text stays with the current heading across page breaks. The order
in the PDF is preserved; section numbers are not sorted.

`nominal_level` and `depth` are kept separate. `2.1.1.1`, for example, has a
four-part visible label but appears directly below `2.1`, with no real
`2.1.1` parent. It is saved as `nominal_level=4`, `depth=3`, and
`numbering_gap=true`. The parser does not invent missing headings.

Content is saved as typed blocks: normal text, numbered lists, and tables.
Only tables with cell boundaries are treated as tables; smaller detector
fragments contained inside a real table are discarded. The unnumbered cover
title is stored as document metadata.

## Known CT-200 cases

| PDF case | Result |
| --- | --- |
| Cover title before section 1 | Saved as the document title. |
| Missing `2.1.1` before `2.1.1.1` | Attached below `2.1`; gap flagged. |
| `3.4` appears before `3.3` | Kept in that source order. |
| Two `Error Codes` headings | Stored as separate nodes under their real parents. |
| Text continues onto the next page | Kept in the open section. |
| A list item wraps onto another line | Joined to the same list item. |

## Storage and versioning

SQLite stores the document tree, versions, nodes, and user selections. Every
ingestion creates immutable node snapshots; it does not overwrite the previous
manual. MongoDB stores nested generation records.

Nodes are matched between versions using the already-matched real parent and a
case-insensitive, whitespace-normalised heading. Section numbers are not used
as identity. If the match is ambiguous, for example duplicate sibling headings
that were reordered, the system creates a new logical node rather than
guessing.

The API can list top-level sections, get one node with its children and full
text, search headings/body text, and show a node's version history with a
short diff.

## LLM generation

A selection stores node snapshot IDs, not just the latest logical IDs. The
generation prompt receives only the selected body text and asks for three to
five JSON test cases with title, rationale, preconditions, steps, expected
result, and source node IDs.

Pydantic validates the response. Invalid JSON, missing fields, an invalid case
count, or source IDs outside the selection trigger one repair request. If that
also fails, the result is saved as `generation_failed` with the raw responses
and error. The system does not fabricate a successful result.

The same selection with unchanged source hashes returns the previous result to
avoid duplicate provider calls. `force_regenerate=true` is available when a
new result is wanted intentionally.

## Staleness and limits

Each generation saves the logical node IDs and body-text hashes of its source
snapshots. At retrieval time, the service finds the latest snapshot for every
logical node. A missing node or different hash makes the generation stale and
returns a readable reason plus a short diff.

This is conservative: fixing a typo is treated the same as changing a pressure
threshold. For this medical-device-style document, that is safer than silently
approving an old test case. A production version should classify diffs for
numbers, units, comparisons, and negation, then send uncertain cases for human
review.

The main limitation is PDF layout. A new manual layout or poor scan could make
a line, list, or table harder to classify correctly. Figures are not extracted
as structured content. More time would go into block-level coordinates,
confidence scores, and a human-review path for uncertain extraction or
version matches.


