# CT-200 interview study guide

## The project in one sentence

I built a traceable document pipeline, not just an LLM wrapper: generated QA
ideas remain linked to the exact PDF text and document version that produced
them, and are marked stale when that source changes.

## The end-to-end story

```text
PDF → extract a section tree → save immutable snapshots → select source text
→ generate validated QA ideas → ingest a new PDF version → detect stale output
```

## Decisions to defend

| Area | What I did | Why | Next improvement |
| --- | --- | --- | --- |
| PDF extraction | Used `pdfplumber` for selectable-text PDFs and Tesseract OCR as fallback. | It provides word positions, bold styling, and table cells. PyMuPDF could not run in this Windows environment. | Save coordinates and confidence for each extracted block. |
| Heading detection | Required both CT-200-style numbering and bold text. | Numbering alone would turn the clinical numbered list into sections. | Make the rules configurable for other manuals. |
| Tree building | Used a stack of open headings and preserved PDF order. | It keeps text under the correct open heading across page breaks and does not "fix" `3.4` appearing before `3.3`. | Add anomaly reporting for unusual structures. |
| Bad numbering | Kept both `nominal_level` and `depth`. | `2.1.1.1` has no `2.1.1` parent. I preserve the printed label without inventing a section. | Flag more numbering anomalies for review. |
| Tables/lists | Saved typed `text`, `list`, and `table` blocks. | This keeps useful structure instead of flattening everything to text. | Support figures and more table layouts. |
| Database split | SQLite owns the tree; MongoDB owns nested generation records. | Tree/version/selection data is relational; LLM records are nested documents retrieved by source and selection. | Add production backups, monitoring, and migrations. |
| Version matching | Matched on actual parent plus normalised heading. | Section numbers are presentation data and are not reliable identity keys. | Suggest fuzzy matches for reviewer approval. |
| LLM output | Prompted for JSON and validated with Pydantic. | A real LLM can return malformed, incomplete, or wrongly sourced output. | Use provider schema mode where available and forbid extra fields. |
| Duplicate requests | Returned existing output for the same selection and unchanged hashes. | Avoids duplicate provider cost and duplicate records. | Add cache-expiry policy if required. |
| Staleness | Compared saved body-text hashes with latest matching snapshots. | Gives a simple, auditable indication that a source changed. | Classify high-risk edits such as changed numbers or units. |

## Questions a recruiter may ask

### Why not use section numbers as the tree structure?

The source itself disproves that assumption. `2.1.1.1` appears without a
`2.1.1` parent, and `3.4` appears before `3.3`. I preserve visible numbering
for traceability, but use the actual extracted parent relationship for the
tree.

### Why store both `nominal_level` and `depth`?

`nominal_level` says what the PDF printed; `depth` says where the node really
sits in the extracted tree. This avoids turning a bad section number into a
bad parent-child relationship.

### How do you stop numbered body text becoming headings?

For native PDFs, a heading must be both numbered and bold. The clinical list
is numbered but not bold, so it is kept as a list block. OCR is less certain
because it does not preserve bold metadata, so its rule is deliberately more
conservative and CT-200-specific.

### Why SQLite and MongoDB?

SQLite fits document versions, nodes, parent links, and selections. A
generation is a nested record containing test cases, raw LLM responses,
errors, and source snapshots, so MongoDB is a natural fit for that access
pattern. This also follows the assignment's requested split.

### Why not overwrite v1 when v2 arrives?

Overwriting would lose the evidence behind an earlier generation. Each
ingestion creates immutable node snapshots, and selections keep snapshot node
IDs, so they still refer to the exact v1 wording after v2 exists.

### What happens when a heading is renamed?

The current matcher may treat it as a new logical section. That is deliberate:
creating a false-new section is safer than silently attaching history to the
wrong section. A production system would offer fuzzy-match suggestions for
human approval.

### Why does a typo fix mark a generation stale?

The current hash check is intentionally conservative. It cannot safely decide
whether a small wording change is harmless or changes a safety instruction.
The next step is change classification for numbers, units, comparisons, and
negation, while keeping human review for uncertain cases.

### What happens when the LLM returns invalid output?

Pydantic checks the JSON, required fields, three-to-five-case limit, and that
every source node ID was selected. The service sends one repair request. If it
still fails, it stores `generation_failed`, the raw responses, and the error;
it does not pretend a generation succeeded.

### Why only one retry?

One retry often fixes JSON formatting errors. More retries create unbounded
cost and latency, so after the second failure the system saves an auditable
failure record.

### What happens if the same selection is submitted twice?

The request is idempotent when the selection and source hashes are unchanged:
the API returns the earlier result instead of calling the provider again.
`force_regenerate=true` is the explicit way to request a fresh result.

## Weak points to volunteer

- The parser is tuned to CT-200, not every possible PDF layout.
- OCR heading detection is weaker because bold font data is unavailable.
- Large heading renames and reordered duplicate siblings cannot be matched
  safely by the current exact matcher.
- Hash staleness over-flags harmless wording changes.
- Figures are not extracted as structured content.
- There is no authentication, rate limiting, background job queue,
  monitoring, backup policy, or production migration tooling.
- Search uses SQL `ILIKE`, which is fine for this manual but not a large
  corpus.
- Selecting a parent node does not automatically include every descendant's
  text; a production UI should make this an explicit choice.
- The content hash is based on body text. If heading-only changes matter for a
  selection, heading and typed-block data should also be included in the hash.

## Code walkthrough order

Do not walk through every file. Tell the product story using these files.

1. `app/parser.py` — `parse_ct200_pdf`, `_heading`, `_append_body_line`, and
   `_real_tables`. Explain the heading stack, the bold-and-numbered rule, the
   `2.1.1.1` gap, the wrapped list item, and table fragments.
2. `app/ingestion.py` — `ingest_pdf`. Explain immutable snapshots,
   normalised content hashes, and how parsed nodes become database nodes.
3. `app/matching.py` — `match_nodes`. Explain unique parent-aware heading
   matching and why ambiguous duplicate siblings become new logical nodes.
4. `app/services.py` — `_validate_generation`, `generate`, `staleness`, and
   `diff_for_node`. Explain validation, one retry, failure persistence,
   idempotency, and stale-result detection.
5. `tests/test_api.py` — `test_browse_selection_generation_and_staleness_flow`.
   This shows the full product path: ingest v1, browse, select, generate,
   deduplicate, ingest v2, show a diff, and mark the old result stale.

## Best single test to show

Show `test_browse_selection_generation_and_staleness_flow` in
`tests/test_api.py`. It demonstrates the complete system rather than testing
one isolated function.

## Closing answer

> I focused on traceability rather than treating the LLM as the product. Every
> generated test case remains linked to the exact document snapshot that
> produced it, and the system can later explain when that evidence changed.

---

# Detailed interview script

This section is intentionally more specific than the project README. Use it
to prepare for follow-up questions. Do not memorise it word for word; explain
the decisions in your own words.

## 1. Start with the problem, not the tools

### A good 45-second introduction

> The task is not only to extract text and ask an LLM for test cases. The
> difficult part is preserving the chain of evidence. A test case needs to be
> traceable to the exact section text that produced it, even after a newer PDF
> is uploaded. I therefore separated the problem into PDF structure,
> versioned snapshots, validated LLM output, and stale-result detection.
>
> I inspected the supplied CT-200 PDFs first and built rules around the real
> irregularities I found. That is why the parser preserves source order, keeps
> a numbering gap rather than inventing a parent heading, preserves typed
> lists/tables, and keeps old versions immutable.

### If they ask, "Why not use RAG?"

> RAG is useful for open-ended question answering, but it would not solve the
> central traceability problem here by itself. I need a stable tree, exact
> source snapshots, version identity, and a way to tell whether a generation
> was based on text that later changed. Retrieval can be added later, but I
> first needed a trustworthy document model.

## 2. PDF parsing: exact choices and trade-offs

### Why did you inspect the PDF manually first?

> PDF extraction is layout recovery, not normal text parsing. The same visual
> page can contain headings, body text, lists, and tables, while a PDF often
> stores them as positioned words rather than semantic elements. Manual
> inspection exposed the cases the parser needed to handle: the missing
> `2.1.1` parent, `3.4` before `3.3`, duplicate `Error Codes` headings,
> cross-page body text, a wrapped list item, and nested table detections. I
> turned each important finding into a regression test.

### Why `pdfplumber` rather than PyMuPDF?

> The brief suggested PyMuPDF, but its native extension was blocked by Windows
> Application Control in this environment. I did not replace it blindly:
> `pdfplumber` provides the capabilities I needed for this PDF—word position,
> font name/size, and table-cell boundaries. I recorded the deviation and its
> reason instead of claiming it was a product preference.

### Why not OCR every PDF?

> OCR introduces avoidable transcription and layout errors when a text layer
> already exists. In `auto` mode, the parser uses embedded PDF text when it is
> present and only falls back to OCR for image-only pages. This keeps the
> normal CT-200 path more accurate while still supporting scans.

### How does the native parser decide a heading?

> It first matches a CT-200-style label such as `3.2` or `2.1.1.1`, then
> requires every word on that line to use a bold font. Both checks matter.
> Numbering alone would turn the numbered clinical classification list into
> headings; bold alone would be too broad. This is intentionally a
> document-specific rule, not a claim that it works for all PDFs.

### What happens on an OCR page, where bold information is missing?

> The OCR path uses a separate, more conservative rule. It accepts dotted
> numbers as subsection signals or accepts a top-level numbered heading only
> when it is materially taller than the median text line. It rejects labels
> containing a colon because the CT-200 numbered list uses that shape. It is a
> best-effort fallback and I would not overstate its reliability.

### Explain the heading-stack algorithm without code

> I read lines in PDF order and keep the headings that are currently open. A
> new heading closes headings at the same or deeper nominal number level, then
> becomes a child of the closest remaining real heading. Later body text stays
> attached to that current heading until another heading appears. Because I do
> not sort section labels, `3.4` remains before `3.3` exactly as printed.

### Explain the `2.1.1.1` case precisely

> The PDF contains `2.1.1.1 Battery Life Under Typical Use`, but no standalone
> `2.1.1` heading. I save the visible label as `nominal_level=4`, pop no real
> `2.1` parent, attach the node under that parent, and save `depth=3` with
> `numbering_gap=true`. Inventing `2.1.1` would make the tree neat but would
> create content that was never in the source.

### How are tables handled, and why is that not a generic table solution?

> I only create a `table` block when `pdfplumber` finds actual cell boundaries
> and at least two rows and columns. It can return small enclosed fragments
> inside a larger real table, so I sort candidate tables by area and discard a
> candidate contained within one already accepted. That works for the supplied
> grids. It does not claim to infer every visually aligned table in arbitrary
> PDFs.

### How are lists and wrapped items handled?

> A line matching a numbered-list pattern starts or extends a `list` block.
> If the following non-heading line arrives while the current block is a list,
> it is joined to the last list item. This preserves the wrapped fifth
> classification item instead of flattening it into a paragraph.

### Questions that expose parser weakness

**"What if a heading contains mixed bold and regular text?"**

> The native rule currently requires all words to be bold, so it could miss
> that heading. That is a deliberate conservative false-negative bias for this
> manual. A general parser would use style clustering, indentation, spacing,
> and layout features rather than one font rule.

**"What if a table and ordinary text share the same vertical area?"**

> The current table exclusion uses table positions and is designed around the
> CT-200 layout. A more general solution would use the full bounding box and
> preserve line-level provenance, so it can distinguish side-by-side content.

**"Why is this the biggest silent-risk area?"**

> A parser can produce a tree that looks believable while placing text under a
> wrong heading, and no exception will be raised. The current tests cover the
> irregularities I observed, but they do not prove correctness for all PDF
> layouts. The first production improvement would be confidence and review
> signals, not simply another parsing heuristic.

## 3. The data model and why snapshots matter

### Explain the database model

```text
Document
  └── DocumentVersion (v1, v2, ...)
        └── Node snapshot (one section in one version)
              └── parent_node_id (the tree within that version)

LogicalNode
  └── links snapshots that are safely recognised as the same section over time

Selection
  └── SelectionItem → a specific Node snapshot, not merely a LogicalNode
```

### Why have both `Node` and `LogicalNode`?

> A node is a version-specific snapshot: its body text, hash, parent snapshot,
> and position may change in v2. A logical node is the stable concept used to
> connect snapshots that are safely identified as the same section. Without
> this split, I would either overwrite history or be unable to compare a v1
> source to its v2 counterpart.

### Why does a selection store snapshot IDs?

> A user selected v1 wording, not a moving target. Storing only a logical ID
> would make an old selection silently resolve to the latest wording after v2
> is ingested. Snapshot IDs preserve what was actually sent to the LLM.

### Why hash normalised body text?

> The code collapses whitespace before calculating SHA-256. That avoids
> marking a section changed just because extraction produced different runs of
> spaces or line wrapping. The hash is used as an exact, reproducible change
> signal; it is not intended to say whether a change is important.

### What is the limitation of hashing only `body_text`?

> A heading-only change is not reflected in this hash, and tables/lists are
> represented only through their text rendering in `body_text`. If headings or
> block structure are meaningful source evidence, I should hash a canonical
> representation containing the heading, body, and typed blocks. That is a
> concrete improvement I would make before relying on this at larger scale.

### Why choose SQLite?

> The core operations are relational: versions belong to documents, node
> snapshots belong to a version, nodes point to parents, and selections point
> to snapshots. SQLite is small, easy to run for the assignment, and supports
> those relationships cleanly. For multi-user production I would move to a
> managed relational database such as PostgreSQL.

### Why choose MongoDB for generations?

> A generation record is retrieved as one nested unit: selection ID,
> fingerprint, test cases, raw provider outputs, errors, and a list of source
> snapshots. MongoDB stores that natural document shape and has indexes for
> selection and source node/logical-node retrieval. The split also follows the
> assignment requirement.

### Questions that expose data-model weakness

**"What happens if the same exact PDF is ingested twice?"**

> The file is SHA-256 hashed before parsing. If its source hash matches the
> latest version, ingestion returns that existing version instead of creating
> a duplicate. It is idempotent for identical bytes.

**"What if a semantically identical PDF has different metadata or bytes?"**

> It becomes a new version because source-file idempotency is byte-based. The
> section-level hashes and matcher then still reveal whether its content is
> unchanged. A production system could add a document-level canonical-content
> fingerprint if duplicate uploads became a problem.

**"What if two API users ingest different v2 files at the same time?"**

> The current local SQLite implementation does not add a concurrency control
> layer around version allocation, so that is a production limitation. I
> would use database transactions and a unique version allocation strategy in
> PostgreSQL, with retry on conflict.

## 4. Matching v1 to v2

### Explain the matching algorithm

> The parser returns nodes in parent-first order. For each incoming node, the
> matcher first obtains the matched logical identity of its actual parent. It
> then searches the previous version for nodes under that same logical parent
> whose headings match after lowercasing and normalising whitespace. One match
> preserves logical identity; no match creates a new logical node; more than
> one match is ambiguous and is deliberately not linked.

### Why not match by section number too?

> Numbers look useful but are unreliable in this source because of the missing
> `2.1.1` level. A heading can also be renumbered without being a different
> requirement. Parent plus heading is a better starting identity, while the
> source number remains visible metadata.

### Why not fuzzy match automatically?

> Fuzzy matching is useful for suggestions, but automatic fuzzy matching is
> dangerous when preserving history. It could connect a renamed or similar
> section to the wrong old requirement, which would make a stale check look
> trustworthy when it is not. I would use fuzzy scores to propose matches to a
> reviewer, not silently accept them.

### Questions that expose matching weakness

**"What if `Cuff Inflation Sequence` becomes `Inflation Sequence`?"**

> The current exact-normalised-heading matcher will likely create a new
> logical node. It is a false-new result, but not a false-history result. The
> next step is reviewer-approved fuzzy matching.

**"What if two siblings have the same heading?"**

> If there is exactly one matching heading under the matched parent, the
> identity is preserved. If there are duplicates under the same parent, the
> matcher refuses to choose and records a new logical node. Duplicate headings
> under different parents are safe because the parent identity disambiguates
> them; this is why both `Error Codes` nodes can be separate and correct.

**"Why only match against the immediately previous version?"**

> Each version carries forward logical IDs from its predecessor, so matching
> against the latest version keeps the chain simple. It does mean a section
> that disappears and later returns is treated as new; historical resurrection
> is a reasonable future enhancement, but not safe to guess automatically.

## 5. API design

### What is exposed and why?

| Endpoint group | What it proves |
| --- | --- |
| Ingest | A document becomes versioned snapshots. |
| Sections | Root browsing with a version parameter; latest is the default. |
| Node detail | Full text, typed blocks, parent snapshot, and immediate children. |
| Search | Heading and body-text discovery in one chosen version. |
| Changes | Version history and a short unified diff. |
| Selections | Exact source snapshots are saved before generation. |
| Generations | Validated QA output can be retrieved by selection or current logical section. |

### Why do search results not return full text?

> Search returns summaries so discovery remains lightweight. The caller then
> requests a specific node for its full text, typed blocks, and children. This
> also makes the API easier to browse in Swagger.

### Why return immediate children rather than the whole tree?

> It keeps responses predictable and avoids returning an entire large manual
> for a single node request. A client can browse recursively. If the product
> needed one full-tree view, I would add a dedicated endpoint rather than make
> every node response potentially huge.

### API gaps to acknowledge

- No user authentication or authorisation.
- No rate limiting or request-size limits.
- Search is `ILIKE` on SQLite text, not full-text search.
- Ingestion and generation happen synchronously; large PDFs or slow providers
  would need a job queue and status endpoints.
- MongoDB configuration is required at application startup in the current
  production configuration. Separating read-only PDF browsing from generation
  availability would make the API more resilient.

## 6. LLM generation: reliability, security, and cost

### What exactly is sent to the LLM?

> Only selected source nodes are put into the prompt. For each one, the prompt
> contains the snapshot node ID, section number/heading, and body text. It
> explicitly asks for three to five executable QA cases and tells the model to
> cite selected source IDs only and not invent clinical claims.

### Why include source node IDs in every test case?

> It makes each generated case traceable to source evidence. The validator
> rejects an ID that is not in the selection, so the model cannot cite an
> arbitrary section from the same document.

### What does validation actually check?

> Pydantic parses the JSON and requires three to five test cases. Every test
> case needs a non-empty title, rationale, preconditions, steps, expected
> result, and at least one source node ID. Code then checks that every cited
> node ID belongs to the saved selection.

### Important honesty point: is it a fully strict schema?

> It validates required fields, types, counts, and source membership. Pydantic
> currently accepts unknown extra JSON fields because the models do not set
> `extra="forbid"`. That does not weaken traceability, but if the requirement
> is an exact output contract, I would enable `extra="forbid"` and test it.

### Why store raw responses, including failed ones?

> A failed generation should be debuggable and auditable. Keeping raw output
> plus the validation/provider error lets us distinguish a provider failure,
> invalid JSON, missing fields, or invalid citations. It is particularly useful
> when changing models or prompts.

### Why temperature 0.2?

> The goal is concrete, source-grounded QA ideas, not creative writing. A low
> temperature reduces formatting and content variation. It does not guarantee
> correctness, which is why structured validation and source-ID checks remain
> necessary.

### What does one repair attempt do?

> When the first response fails Pydantic or source-ID validation, the next
> prompt includes the exact validation error and asks for corrected JSON only.
> It is deliberately bounded at two attempts. A provider or network exception
> is not retried in the current version; it is saved as an auditable failed
> generation.

### Questions that expose LLM weakness

**"Can the LLM still hallucinate a medically unsafe test case?"**

> Yes. Schema validation proves shape and source-ID membership, not factual
> correctness of every sentence. The prompt constrains the model to selected
> text, but a human still needs to review QA ideas in a medical-device context.
> A stronger system would add claim-to-source checks, safety rules, and an
> approval workflow.

**"Is the LLM output deterministic?"**

> No. The production request uses a low temperature to reduce variation, but
> LLMs remain non-deterministic. The system handles that through validation,
> raw-response storage, and an idempotency policy that reuses the earlier
> output for the same selection unless the caller explicitly forces a new one.

**"Why call an external provider at all?"**

> The assignment asks for LLM-powered generation and permits any compatible
> provider. I isolated it behind a small `LLMClient` interface, so tests use a
> deterministic fake and the live client can point to Groq, OpenRouter, or a
> compatible endpoint through environment variables.

**"How would you protect sensitive manuals?"**

> This prototype sends selected text to the configured external provider, so
> production use would need data classification, provider agreements, access
> controls, encryption, retention rules, audit logs, and possibly a private or
> self-hosted model. I would not claim this setup is appropriate for sensitive
> real medical-device documentation without those controls.

## 7. Staleness: what it proves and what it does not

### Explain retrieval-time staleness step by step

1. When generation succeeds or fails, save the selection ID and each source
   snapshot's node ID, logical node ID, document ID, and content hash.
2. On retrieval, find the latest snapshot with each saved logical node ID in
   the same document.
3. If it is missing, mark the generation stale.
4. If its normalised body-text hash differs, mark the generation stale.
5. Return readable reasons, such as `3.2 Cuff Inflation Sequence content
   changed`, and expose a short unified diff through the changes endpoint.

### Why check at retrieval time instead of mutating old generations on ingest?

> Retrieval-time checking means I do not need to update every historical
> generation whenever a new PDF arrives. The old generation stays immutable,
> and its current status is calculated against the latest document state. This
> keeps the audit record clean and handles a user retrieving an old result
> after several newer versions.

### What does `stale: false` mean?

> It means the saved source hashes match the latest safely matched snapshots.
> It does not mean the generated test case is clinically approved or that the
> entire document is unchanged. It is a source-evidence status, not a safety
> certification.

### Why not automatically regenerate when stale?

> A new generation would be a new suggestion, not proof that the old test case
> remains valid. Auto-regeneration could hide a meaningful change and create a
> new provider cost. The current system asks for deliberate review or a new
> explicit generation request.

### Staleness limitations to state plainly

- Any body-text hash change is treated equally; typo fixes are over-flagged.
- Heading-only changes are not included in the current content hash.
- If a renamed heading cannot be matched, it may appear missing/new rather
  than changed.
- The diff is a short text diff, not a semantic risk assessment.
- The system does not determine whether a specific generated test case is
  affected by a specific changed sentence.

## 8. Testing: what was actually verified

### Parser tests prove these cases

- duplicate `Error Codes` headings remain distinct and have different parents;
- `2.1.1.1` keeps nominal level 4 but real depth 3 and a numbering gap;
- `3.4` remains before `3.3`;
- cross-page text remains under section `3.1`;
- the genuine specification grid remains a table;
- the cover title is retained;
- the clinical list remains five list items; and
- forced OCR does not convert the numbered classification list into headings.

### Versioning tests prove these cases

- v2 keeps the logical ID of the matching Battery Life section;
- changed body text gets a different content hash;
- a genuinely new v2 section gets a new logical ID; and
- ambiguous duplicate siblings are not guessed.

### API tests prove the full path

- ingest v1;
- browse root sections and search for `Cuff Inflation`;
- retrieve full node text;
- save a version-pinned selection;
- generate three valid test cases;
- repeat the same request without a second provider call;
- ingest v2;
- return a diff and `stale=true`; and
- preserve selection v1 snapshot IDs after v2 exists.

### What tests do not prove

> They do not prove the parser works for arbitrary PDFs, a real LLM is always
> safe, MongoDB survives outages, or the application is secure for production.
> The regular suite uses fakes for repeatability. The separate live smoke test
> makes one real provider call only when credentials are configured.

## 9. Suggested live demo order

1. Run `python -m pytest -q` and say the suite covers the actual irregularities
   found in the supplied PDF plus the end-to-end versioning flow.
2. Run `python scripts/demo_flow.py` to show v1 generation becomes stale after
   v2 without spending an LLM request.
3. In Swagger, show `GET /documents/ct200/sections` and explain why every
   root section has `depth=1`.
4. Use `GET /nodes/search` for `Cuff Inflation`, then `GET /nodes/{node_id}`
   to show full text, hash, and children.
5. In code, open `tests/test_api.py` first; then open the corresponding
   functions in `app/services.py`.

## 10. If asked, "What would you do with one more week?"

> I would focus on safe generalisation, not add more prompt wording. First, I
> would store coordinates and confidence for every extracted block and build a
> review workflow for uncertain PDF structure. Second, I would add
> reviewer-approved fuzzy matching for renamed headings. Third, I would make
> staleness more useful by classifying diffs—especially numbers, units,
> comparisons, and negation—while retaining the exact hashes and immutable
> snapshots as the audit baseline. Finally, I would add authentication,
> background jobs, monitoring, backups, and production database migrations.
