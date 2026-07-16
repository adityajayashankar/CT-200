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
- **Known unhandled input:** image-only/scanned pages are not handled. The
  parser fails at extraction rather than silently pretending OCR text is
  authoritative; CT-200's supplied PDFs do not need OCR.

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
