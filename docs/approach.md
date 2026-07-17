Exit code: 0
Wall time: 0.2 seconds
Output:
# CT-200 Document Intelligence System: Approach

## 1. What this project does

The CT-200 manual is a PDF for a fictional home blood-pressure monitor. This
project turns that manual into a structured, searchable tree of sections. A
user can select one or more sections and ask an LLM to suggest QA test cases
based on the selected text.

The important part is traceability. A generated test case remains connected to
the exact section text and document version that produced it. If the manual is
uploaded again with changed text, the system can tell the user that the older
test case needs review.

The flow is:

```text
CT-200 PDF
  -> extract text, headings, lists, and tables
  -> build and save a section tree
  -> select version-pinned sections
  -> generate validated QA ideas with an LLM
  -> re-ingest a new manual version
  -> show whether earlier generated ideas are stale
```

This is intentionally a parser for the supplied CT-200 manuals, not a
generic solution for every possible PDF.

## 2. Reading and parsing the PDF

### Chosen approach

The extraction pipeline is hybrid. It first checks whether each PDF page has
an embedded text layer. For born-digital pages it uses `pdfplumber`, which
provides word positions, fonts, and table cell boundaries. For image-only or
scanned pages it renders the page at 300 DPI with Poppler and uses Tesseract
OCR to recover positioned text. This avoids needlessly OCRing clean digital
text while still supporting the OCR input path required by the assignment.

The assignment suggests PyMuPDF for born-digital PDFs, but its native
extension was blocked by Windows Application Control in this environment.
`pdfplumber` provides the layout evidence needed here instead.

For every page, the parser produces positioned lines. Native pages include
font information; OCR pages use Tesseract's word boxes and confidence values.
The parser groups them into visual lines, then decides whether each line is a
heading or body content.

### How the hierarchy is built

A line becomes a section heading only when both of these are true:

1. It starts with CT-200-style numbering, such as `3.2` or `2.1.1.1`.
2. It is bold in the PDF.

This rule matters because the manual also contains numbered list items. A
number alone is not enough to prove that text is a heading.

The parser uses a stack of currently open headings. When it sees a new
heading, it removes headings at the same or deeper numbered level, then adds
the new heading below the closest real heading still open. Normal body text
is attached to the current heading, even if it continues on the next page.
The parser preserves the order seen in the PDF instead of sorting section
numbers into an idealised order.

Each saved node has both `nominal_level` and `depth`:

- `nominal_level` is the number of parts in the visible label. For example,
  `2.1.1.1` has nominal level 4.
- `depth` is its real depth in the extracted tree.

Keeping these separate prevents a bad section number from silently becoming a
bad parent-child relationship.

### Tables, lists, and document title

The parser stores body content as typed blocks instead of flattening all text
into one string:

- Normal prose is a `text` block.
- Numbered clinical classifications are a `list` block.
- A grid is a `table` block only when `pdfplumber` detects cell boundaries.

When table detection returns overlapping fragments, the parser keeps the
largest cell-bounded table and discards contained fragments. The cover title
is stored as document metadata rather than being lost before the first
numbered heading.

## 3. CT-200 irregularities and how they are handled

The PDF was inspected manually before writing the final extraction logic. The
following table records the non-standard cases found in it.

| Finding in the manual | Handling in this project |
| --- | --- |
| The cover has a large title before section 1. | Save it as the document title. |
| `2.1.1.1` appears without a separate `2.1.1` heading. | Attach it to the closest real parent (`2.1`), mark `numbering_gap=true`, and do not invent a missing section. |
| Section 3 contains siblings in the visual order `3.1`, `3.2`, `3.4`, `3.3`. | Preserve the source order exactly. |
| `Error Codes` appears twice under different parents. | Create two different nodes; the heading text is not treated as a globally unique ID. |
| Text in section 3.1 continues across a page boundary. | Keep it in the open section until another heading is found. |
| A specification grid is a real table, while detector output can also contain smaller fragments. | Keep the real cell-bounded table and remove contained fragments. |
| The clinical classification content is a numbered list, including one wrapped final item. | Store it as five list entries, joining the continuation line to the final entry. |

## 4. Debugging and validation

My first concern was not whether the result looked neat, but whether it could
silently put text under the wrong section. I used manual inspection of the
PDF, extracted-text checks, and focused automated tests to verify the tree.

The early parser logic exposed several weaknesses:

- Treating the numbering label as the actual tree depth would have created an
  incorrect hierarchy for `2.1.1.1`.
- Table detection produced nested fragments for a genuine table.
- The cover title was omitted because it has no section number.
- The wrapped final list item was flattened into normal text instead of being
  kept as list item 5.

The fixes were to separate visible numbering from real depth, filter contained
table regions, add explicit cover-title extraction, and preserve list blocks.

The test suite includes explicit regression tests for duplicate headings,
the skipped numbering level, out-of-order siblings, cross-page text, the
real table, the cover title, and the numbered list. It also tests versioning,
LLM retry behaviour, and the complete v1-to-v2 stale-generation flow.

## 5. Data model and storage choices

SQLite stores the structured, relational data. MongoDB stores LLM generation
records. This follows the assignment's requested split: relational data is
kept in SQLite while nested generated test-case documents are kept in a
document database.

| Data | Where it is stored | Why |
| --- | --- | --- |
| Document identity and title | `documents` table | One stable record for CT-200. |
| Each uploaded manual | `document_versions` table | Version 1 and version 2 both remain available. |
| Cross-version section identity | `logical_nodes` table | Links the same conceptual section between versions. |
| Extracted section snapshot | `nodes` table | Stores parent, heading, text, typed blocks, position, and content hash for one version. |
| Named user selection | `selections` and `selection_items` tables | Stores exact node snapshots, so the selection is version-pinned. |
| LLM result | MongoDB `generations` collection | Fits nested test-case documents and supports indexed retrieval by selection and source node. |

Each MongoDB generation document stores the selection ID, source node IDs, logical node
IDs, document IDs, source content hashes, raw LLM responses, status, and any
error. That information makes a generated result traceable and auditable.

The runtime flow was verified with the supplied CT-200 manual: ingestion
returned all eight top-level sections, a selection was created for section 3.2
(`Cuff Inflation Sequence`), and a real provider returned three validated test
cases. The completed generation document appeared in the MongoDB `ct200`
database's `generations` collection with its source snapshot and content hash.

## 6. Versioning and matching sections between manuals

Re-ingesting a PDF does not overwrite the old version. It creates a new set
of immutable node snapshots.

To decide whether a new section is the same logical section as one in the
previous version, the matcher uses:

1. The already-matched logical identity of the actual parent.
2. A case-insensitive, whitespace-normalised heading.
3. Exactly one matching candidate under that parent.

Section numbering is deliberately not the identity key. It is presentation
information, and the missing `2.1.1` level shows that the numbers cannot
always be trusted to represent the real hierarchy.

If one unique parent-and-heading match exists, the new snapshot keeps the old
logical node ID. A different SHA-256 hash of its normalised body text means
the content changed. If no safe match exists, a new logical node is created.

This matcher deliberately fails safely for duplicate sibling headings. If two
old siblings have the same normalised heading under the same parent, it does
not guess which one matches the new node. It creates a new logical node
instead. This can create false "new" nodes, but it avoids silently connecting
history to the wrong section.

Known limits are reordered repeated sibling headings and substantial heading
renames. A future version containing a real `2.1.1` heading would re-parent
the existing Battery Life section instead of incorrectly preserving the old
path.

## 7. APIs, selections, and generated QA ideas

The FastAPI service provides endpoints to ingest a document, browse top-level
sections by version, read one node and its children, search headings/body
text, view a node's change summary, create selections, generate QA ideas, and
retrieve past generations.

A selection stores node snapshot IDs, not just the latest logical node IDs.
For example, a selection created from section 3.2 in version 1 still points
to the version 1 wording after version 2 is ingested. This is the foundation
of reliable traceability.

For generation, the prompt includes only the selected section text and its
snapshot IDs. It asks for exactly three to five concrete test-case ideas in
JSON. Every idea must have a title, rationale, preconditions, steps, expected
result, and one or more source node IDs from the selection. The prompt also
instructs the model not to invent clinical claims beyond the manual.

Pydantic validates the response. If JSON is invalid, the schema is incomplete,
or a test case cites an unselected node, the service sends one repair request
that includes the validation error. If the retry still fails, or the provider
fails, the result is saved as `generation_failed` with raw responses and the
error. The system never fabricates test cases to make a failed request look
successful.

The same selection and unchanged source content return the earlier generation
instead of calling the LLM again. This idempotency rule avoids accidental
duplicate provider cost. `force_regenerate=true` is available when a user
intentionally wants a fresh result.

## 8. Staleness / impact detection

Each generation saves the content hash of every source node. When a user later
retrieves it, the service finds the latest snapshot for each logical node and
compares hashes.

- If a source node is missing in the latest version, the generation is stale.
- If its current hash differs from the saved hash, the generation is stale.
- The retrieval response includes readable reasons, such as `3.2 Cuff
  Inflation Sequence content changed`.

The node changes endpoint also returns a short unified text diff when a node
has changed across versions.

This is intentionally conservative: a spelling change and a changed safety
threshold both mark the result stale. The system cannot safely infer that a
small text change is unimportant in a medical-device manual. It asks for
human review rather than claiming the generated test remains valid. It does
not auto-regenerate stale test cases because that is outside the assignment
scope.

## 9. Decision log

### What is most likely to silently give wrong results?

PDF layout extraction is the highest risk. A layout change could make a list
or a table-detector fragment look valid while placing content in the wrong
structure. The focused parser tests catch known cases. In a production system,
I would also store page coordinates for every block, assign extraction
confidence, and send uncertain layouts to a human reviewer.

### Where did I choose simplicity over production-level correctness?

I use SQLite for the document tree and MongoDB for nested LLM generation
records. The remaining simplification is running both with local development
defaults rather than production backups, monitoring, and access controls.
The first production gaps would be backup/restore policy, secret management,
and operational monitoring rather than the generation-record data model.

### What input is not handled?

OCR is supported for image-only or scanned text pages when Tesseract is
installed. OCR cannot reliably provide font-weight metadata, so scanned-page
heading detection uses CT-200-specific numbering, text size, and list-label
rules; low-quality scans still need review. Figures and captions are not
extracted because the supplied CT-200 manuals do not contain them.

## 10. What I would improve with more time

- Add page-coordinate provenance to every text, list, and table block.
- Return explicit per-block OCR confidence and a low-confidence parsing
  result, rather than relying only on extraction behaviour.
- Suggest possible matches for renamed headings, but require user review
  before linking their version history.
- Add MongoDB backups, monitoring, and a managed secret store for production.
- Highlight changes to clinical numbers and thresholds separately from simple
  wording changes, while retaining hash comparison as the audit baseline.
