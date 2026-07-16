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
  the closest actual ancestor. Creating a synthetic `2.1.1` would silently
  change the manual.
- **Most likely silent failure:** an extraction/layout change could turn a
  text list or a nested detector artifact into a seemingly valid table. Tests
  assert the known real table and the parser keeps no schema for regions
  without cell evidence. A production system should retain page-region
  provenance and send low-confidence layouts to review.
- **Known unhandled input:** image-only/scanned pages are not handled. The
  parser fails at extraction rather than silently pretending OCR text is
  authoritative; CT-200's supplied PDFs do not need OCR.
