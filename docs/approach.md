# CT-200 approach

## Scope and extraction

This is a CT-200-specific backend, not a generic PDF parser. Manual
inspection established that the supplied six-page v1 and seven-page v2 PDFs
are born-digital. I therefore use `pdfplumber` word coordinates, fonts, and
cell-boundary detection; OCR is neither needed nor used. The original brief
prefers PyMuPDF for born-digital text, but PyMuPDF's native extension is
blocked by Windows Application Control in this workspace. `pdfplumber`
provides the layout evidence needed here without that blocked extension.

Headings require both a CT-200 numbering label and bold styling. Number
segments produce `nominal_level`, while `depth` is calculated from the actual
parent chain. This keeps an authoring gap visible without making downstream
tree consumers mistake it for a depth. The stack builder preserves visual
document order rather than sorting numbers; body lines remain with the open
node over a page boundary. Cell-bounded grids become `table` blocks. There
were no confirmed tab-aligned non-tables, but the parsing model has a
`tabular_text` block type so such content would not be falsely normalized as
a table.

## Structural inconsistencies (copied from inspection notes)

The skipped `2.1.1.1` level, visually out-of-order 3.4/3.3 siblings,
duplicate `Error Codes`, continuing page-boundary body text, and table
detector fragments are all structural inconsistencies with tests in the
parsing slice. The system preserves the document's supplied order and level
metadata, flags skipped parents through the missing relationship rather than
inventing content, and only makes table claims where cell boundaries support
them.

The raw text was also searched to confirm that `2.1.1` does not exist as a
separate heading: its only occurrence is the `2.1.1.1` prefix. That node is
attached to 2.1, has `nominal_level=4`, `depth=3`, and `numbering_gap=true`.

## Data model

SQLite owns relational, versioned data:

| Entity | Purpose |
| --- | --- |
| `documents` | Stable CT-200 document identity. |
| `document_versions` | Immutable ingestions with source path/hash and sequential version. |
| `logical_nodes` | Identity that spans document versions. |
| `nodes` | Per-version snapshots: actual parent snapshot, heading, numbering/depth metadata, blocks, body, and SHA-256 normalized-content hash. |
| `selections` / `selection_items` | Named sets whose items point to snapshot `nodes`, explicitly pinning a version. |

LLM generation records live in `generated_output.json`, a small document
store separate from SQLite. MongoDB would add a local service and operational
setup without benefiting this assignment's single-process, key-based access
pattern. Each JSON document embeds the generated payload, raw LLM responses,
failure reason, selection ID, exact source node IDs, logical IDs, document
IDs, and source hashes. This keeps traceability separate and portable. For a
multi-user production service I would replace it with MongoDB (or a durable
object/document store) with locking, migrations, and backups.

## Version matching

Matching is parent-aware normalized-heading matching. For a new parse,
parents are processed first; a node keeps a prior logical ID only if exactly
one prior node has the same matched actual parent logical ID and a
case/whitespace-normalized heading. Numbering is not an identity key, because
it is presentation metadata and `2.1.1.1` demonstrates it cannot define the
actual tree. A matching logical node with a new content hash is a changed
snapshot; an unmatched node gets a new logical node.

This deliberately fails closed for two identical-title siblings under one
parent: it creates a new logical node rather than guessing. Reordered repeated
sibling headings and substantial heading renames are therefore the first
known failure modes. The test suite deliberately exercises the duplicate
sibling ambiguity. A future real `2.1.1` would make the Battery Life node
re-parent, not silently remain matched through its nominal label.

## API and generation policy

FastAPI exposes ingestion, versioned top-level browsing, snapshot detail,
search, per-logical-node diff summaries, selections, generation, and
generation retrieval. All returned node IDs are per-version snapshots.

The generation prompt includes only selected node text and its snapshot IDs,
asks for three to five executable QA ideas, and requires source IDs in every
idea. Pydantic validates title, rationale, preconditions, steps, expected
result, source IDs, and the 3–5 count. Invalid JSON, an incomplete schema, or
an ID outside the selection receives one bounded repair attempt whose prompt
contains the validation error. A second invalid result or provider failure is
persisted as `generation_failed`, retaining raw responses/error rather than
fabricating output.

Generation is idempotent by a fingerprint of selection ID plus its sorted
snapshot node IDs/content hashes. A repeat request returns the prior record;
`force_regenerate=true` creates a new record. This avoids paid duplicate LLM
calls while still allowing intentional fresh ideas.

## Staleness and its limits

At retrieval, every stored `(logical node, document, content hash)` is
compared with the latest snapshot for that logical node. A changed hash or a
missing latest snapshot marks the record stale and exposes a human-readable
reason. The API does not auto-regenerate stale cases.

Hash comparison treats a one-word edit exactly like a changed clinical
threshold. That is conservative and acceptable for this small regulated
document exercise: it produces review work, not an unsafe false-fresh result.
With more time, numeric/clinical-entity extraction and severity-ranked diffs
could prioritize threshold changes while retaining the hash as the audit
baseline.

## What failed or remains unsupported

The initial parser would have conflated nominal numbering with tree depth; the
explicit `nominal_level`/`depth` split fixes that. Initial table detection also
returned nested fragments of genuine tables, so the parser keeps only the
largest containing cell-bounded region. Image-only/scanned PDFs and figures
are not handled; this parser would need an explicit OCR/figure pipeline before
claiming support. The supplied PDFs contain no figures/captions.

## Decision log

1. **Most likely silent wrong result:** a layout/extraction change may make a
   text list or table-detector fragment look like a valid table. Known tables,
   duplicate headings, skipped levels, ordering, and page-boundary flow have
   targeted tests; a production implementation should retain page-region
   provenance and route low-confidence layouts to human review.
2. **Simplicity over correctness:** the JSON generated-output store is simple
   and sufficient for this local assignment, but it would break first under
   concurrent writers, multi-instance deployment, or operational backup and
   audit requirements. MongoDB/document storage with transactional controls is
   the next upgrade.
3. **Unhandled input:** genuinely scanned/image-only PDFs are unsupported.
   The system does not silently invent OCR text; parsing fails until an OCR
   pipeline with review controls is added.

## With more time

I would add provenance coordinates to every body block, an explicit
low-confidence/unsupported parse result, semantic similarity proposals for
renamed nodes reviewed by a user, MongoDB-backed generation records, and
severity-aware clinical-number diffs.
