# CT-200 source-document inspection notes

## Method and document type

I inspected every page of `ct200_manual.pdf` (six pages) and checked the
corresponding seven-page v2 as a comparison. Both are born-digital PDFs: their
text is directly selectable/extractable, their content uses embedded Nimbus
Sans fonts, and no page needs OCR. In this environment the PyMuPDF native
extension is blocked by Windows Application Control, so the implementation
uses `pdfplumber` for word positions and cell-boundary tables. This is an
environment-driven deviation from the preferred PyMuPDF extractor, not a
claim that OCR is needed.

## Numbering and hierarchy

Top-level sections use `1.` through `8.` in 16.5pt bold; ordinary
subsections normally use `n.n` in 12.87pt bold. The number segment count is
usually a useful level signal, but it breaks at `2.1.1.1 Battery Life Under
Typical Use` on page 2. It is 11pt bold and jumps directly from `2.1`, with
no `2.1.1` node. The parser must retain level four and attach it to the
closest actual ancestor (`2.1`) rather than manufacturing a heading that is
not in the manual.

Numbering is not presentation order: page 3 prints `3.4 Auto Shutoff` before
`3.3 Result Display and Classification`. These must be siblings in document
order, not sorted into numerical order. Lists are numbered as well (the five
classification entries under 3.3), but are 11pt regular rather than bold and
must remain body content, not headings.

Heading text is not unique. `Error Codes` occurs at 4.2 (under Alarms and
Safety Behavior) and 7.1 (under Troubleshooting). They are distinct nodes
with different parents, despite having identical text.

## Tables, captions, and flow

The General Specifications grid (page 2) and Error Codes grid (page 4) are
real tables: pdfplumber finds enclosing cell boundaries and yields coherent
rows/columns. They are stored as `table` blocks. The extractor also reports
small enclosed fragments inside those grids; those are nested detection
artifacts and must not become separate tables.

No figures or figure captions appear in either provided version. The numbered
classification entries under 3.3 are an indented list, not a table. There is
no visual cell boundary around them, so they stay text/list content. The
source contains no confirmed tab-aligned-but-not-a-table region; the parser
has a distinct `tabular_text` representation reserved for such a case rather
than guessing a table schema.

Several sections deliberately continue with no visual section separator. 3.1
starts at the bottom of page 2 and continues at the top of page 3; 4.3 and
6.1 similarly continue over a page break (and v2 splits 4.3, 6.1, and 8.1).
The open node must retain subsequent body lines until an actual heading is
encountered. Section 3.3 also has its paragraph immediately followed by an
indented list; it is one subsection, not a set of child headings.

## Structural inconsistencies and preservation policy

The skipped `2.1.1.1` level, visually out-of-order 3.4/3.3 siblings,
duplicate `Error Codes`, continuing page-boundary body text, and table
detector fragments are all structural inconsistencies with tests in the
parsing slice. The system preserves the document's supplied order and level
metadata, flags skipped parents through the missing relationship rather than
inventing content, and only makes table claims where cell boundaries support
them.
