# Running decision log

## 2026-07-16 — source inspection and parsing prototype

- **Extractor:** I chose `pdfplumber` word/layout extraction and its
  cell-boundary table detector. The brief prefers PyMuPDF for born-digital
  text, but its native extension cannot load because of a Windows Application
  Control policy in this workspace. `pdfplumber` supplies the needed font,
  coordinate, and table evidence without OCR.
- **Heading classifier:** CT-200's numbered, bold visual headings are
  recognized only when both properties are present. This prevents the regular
  numbered clinical classification list from becoming false structural nodes.
- **Missing level:** `2.1.1.1` is persisted as level 4 but attached to 2.1,
  the closest actual ancestor. I verified the raw text has no separate
  `2.1.1` heading. Creating one would silently change the manual. The model
  therefore separates `nominal_level=4` from actual `depth=3` and marks a
  queryable `numbering_gap`; no consumer may infer depth from numbering.
- **Most likely silent failure:** an extraction/layout change could turn a
  text list or a nested detector artifact into a seemingly valid table. Tests
  assert the known real table and the parser keeps no schema for regions
  without cell evidence. A production system should retain page-region
  provenance and send low-confidence layouts to review.
- **OCR fallback:** image-only/scanned pages use Tesseract OCR when it is
  installed. The parser fails with an actionable setup error, rather than an
  empty tree, if OCR is required but Tesseract is unavailable. OCR heading
  detection is necessarily lower confidence because font-weight metadata is
  not present in OCR output; low-quality scans should be reviewed.

## 2026-07-16 — version identity

- **Matching strategy:** Node identity is a hybrid of the actual matched
  parent chain and a whitespace/case-normalized heading. Numbering is not an
  identity key: it is presentation data and the known `2.1.1.1` gap proves
  that it cannot safely describe the tree. A content-hash difference under a
  matched identity records a changed snapshot, rather than creating a new
  logical node.
- **Deliberate failure mode:** two same-normalized-title siblings under the
  same parent cannot be safely distinguished by this matcher, particularly if
  they are reordered. The matcher refuses to preserve either identity in that
  ambiguous case and creates a new logical node; a test covers this. This
  favors visible false-new nodes over silently assigning changed content to
  the wrong historical logical node.

## 2026-07-16 — generated output and staleness

- **Generated-output store:** MongoDB stores generated output because each
  result is a nested document retrieved by selection or source node. Indexed
  fields support those retrieval paths while SQLite continues to own the
  versioned relational tree. Production work would add backups, monitoring,
  and managed-secret handling.
- **Invalid LLM output:** The API makes one repair retry with Pydantic's
  validation error. It then stores `generation_failed`, raw responses, and an
  error; it never invents a fallback case.
- **Staleness:** Hash change is deliberately conservative. It cannot say
  whether a wording edit is clinically material, so either wording or a
  changed threshold makes a result stale and requires review.

## 2026-07-16 — coverage correction

- **Regression-first correction:** A pair of commits records tests that first
  failed because the cover title was omitted and the clinical classification
  list was flattened, followed by the parser/persistence fix. This is genuine
  current debugging history, not a reconstructed claim about an earlier
  parser version.
- **Live provider verification:** Integration tests use deterministic LLM
  doubles to be repeatable. A separate opt-in smoke script runs against the
  configured real provider when credentials are supplied; it is intentionally
  not run without user authorization or an API key.
