# Decision log

This is a record of the decisions I made while building the project, including
where I chose a narrower solution and what I would revisit in a production
system. The hardest part was PDF parsing: it is easy to produce a tree that
looks plausible while quietly putting text under the wrong heading.

## Source inspection and parsing

I started by inspecting both supplied PDFs rather than trying to write a
generic PDF parser first. That made the awkward cases visible early: a skipped
heading number, out-of-order section numbers, repeated heading text, a table
with detector fragments inside it, and text that continues onto the next page.

I used `pdfplumber` for born-digital pages. The brief suggested PyMuPDF, but
its native extension was blocked by Windows Application Control in this
environment. `pdfplumber` gave me the information I needed: words, positions,
font styling, and table cell boundaries. I did not use OCR for these supplied
files because their text is selectable; image-only pages use Tesseract as a
fallback.

My heading rule is intentionally CT-200-specific: a line needs both a
CT-200-style number and bold styling to become a heading. I made that choice
because the manual also has a numbered clinical-classification list. Treating
every number as a heading would create a convincing-looking but incorrect
tree.

The clearest example is `2.1.1.1`, which appears without a separate `2.1.1`
heading. I keep the visible label as `nominal_level=4`, but attach it below
the closest real parent, `2.1`, giving it `depth=3`. I also set
`numbering_gap=true`. Inventing the missing heading would make the data look
tidier, but it would not reflect the PDF.

The main limitation is that this is not a general solution for arbitrary PDF
layouts. OCR has no reliable bold-font metadata, and a different manual could
need different heading rules. With more time, I would save page coordinates
and confidence for every extracted block, then route uncertain pages to human
review.

## Version matching and the tree database

SQLite owns the document tree because parent-child relationships, document
versions, and selections are naturally relational. Each ingestion creates new
immutable node snapshots rather than overwriting the previous version.

For version matching, I use the already-matched real parent plus a
case-insensitive, whitespace-normalised heading. I deliberately do not use
the section number as an identity key: the skipped `2.1.1` level shows that a
number is presentation information, not always a trustworthy tree path.

This is deliberately simple matching. It can fail when a heading is renamed,
or when two siblings under the same parent have the same normalised heading
and their order changes. In that ambiguous case, the system creates a new
logical node rather than guessing. That can create a false “new section”, but
I think it is safer than connecting a section to the wrong history. A more
advanced version could suggest fuzzy matches to a reviewer, but should not
silently accept them.

## LLM output and staleness

MongoDB stores generated test-case documents because a generation is a nested
record that is retrieved by selection or source node. SQLite remains the
source of truth for the versioned document tree. I would add backups,
monitoring, and managed secrets before calling this a production setup.

I do not assume an LLM will return valid JSON just because the prompt asks for
it. The API validates the response with Pydantic: it needs three to five test
cases, the required fields, and source node IDs that belong to the selection.
If validation fails, the API sends one repair request with the error. If that
also fails, it saves a `generation_failed` result with the raw responses and
error. It does not invent test cases to hide a provider failure.

A saved generation keeps the exact source node snapshots, their logical IDs,
and content hashes. When a later version is ingested, retrieval compares the
saved hashes with the latest matching snapshots. A changed or missing source
makes the generation stale.

This is intentionally conservative. Fixing `hte` to `the` changes the hash in
the same way as changing `40 mmHg` to `50 mmHg`. For a medical-device manual,
I would rather ask for an unnecessary review than automatically claim an old
test case is still safe. Given more time, I would add diff classification for
numbers, units, comparison operators, and negation, then label likely typo
changes as low risk while keeping a human approval step.

## Validation I ran

The parser tests cover the cases I found during manual inspection: the skipped
numbering level, source-order siblings, repeated `Error Codes` headings,
cross-page text, the real table, the cover title, and the wrapped list item.
Versioning tests cover safe matching and changed hashes. API tests cover
browsing, selections, invalid LLM output, the one-retry policy, and stale
generation retrieval.

The real LLM provider is tested separately through an opt-in smoke script.
The regular test suite uses deterministic test doubles so it stays repeatable
and does not require credentials or spend provider quota.

## Short answers I would give in review

**What is most likely to be wrong without raising an error?** PDF layout
extraction. A list item or small table fragment can look structurally valid,
so I use manual checks of the supplied PDFs and regression tests for the cases
I found.

**Where did I keep it simple?** Version matching. Parent plus normalised
heading is easy to understand, but renamed headings and reordered duplicate
siblings can become false new sections. In production, that would be the first
area I would add reviewer-assisted matching to.

**What input is not handled?** Figures and captions are not extracted as
separate content. Selectable caption text may remain in body text, but the
figure itself is not understood or represented.
