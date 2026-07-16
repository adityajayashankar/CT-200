"""A deliberately CT-200-specific PDF hierarchy parser with OCR fallback."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Literal

import pdfplumber


HEADING_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)*\.?)\s+(?P<title>.+)$")
LIST_ITEM_RE = re.compile(r"^\d+\.\s+.+$")
ExtractionMode = Literal["auto", "native", "ocr"]


class OCRConfigurationError(RuntimeError):
    """Raised when an image-only PDF needs OCR but the OCR runtime is absent."""


@dataclass(frozen=True)
class OCRLine:
    top: float
    text: str
    height: float


class TesseractOCR:
    """Render PDF pages and recover positioned text with Tesseract.

    Imports are intentionally delayed: born-digital PDFs can still be parsed
    with their embedded text layer if OCR dependencies are not installed.
    """

    def __init__(self, path: str | Path) -> None:
        try:
            import pytesseract
            from PIL import Image

            # Fail at setup time with an actionable message, not after an
            # ingestion has silently produced an empty tree.
            pytesseract.get_tesseract_version()
        except (ImportError, OSError, RuntimeError) as exc:
            raise OCRConfigurationError(
                "OCR requires the Tesseract executable. Install it with "
                "'winget install -e --id UB-Mannheim.TesseractOCR', then restart the shell."
            ) from exc
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            raise OCRConfigurationError(
                "OCR also requires Poppler's pdftoppm renderer. Install it with "
                "'winget install -e --id oschwartz10612.Poppler', then restart the shell."
            )
        self._pytesseract = pytesseract
        self._image_type = Image
        self._path = str(path)
        self._pdftoppm = pdftoppm

    def line_records(self, page_number: int) -> list[OCRLine]:
        # 300 DPI gives Tesseract enough detail for the small numbered headings.
        # Poppler is used instead of PDFium/PyMuPDF because their native DLLs
        # are blocked by Windows Application Control in this environment.
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / "page"
            try:
                subprocess.run(
                    [
                        self._pdftoppm,
                        "-f",
                        str(page_number + 1),
                        "-l",
                        str(page_number + 1),
                        "-r",
                        "300",
                        "-png",
                        self._path,
                        str(prefix),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                raise OCRConfigurationError(f"Could not render page {page_number + 1} for OCR: {exc}") from exc
            image_path = next(Path(temporary).glob("page-*.png"), None)
            if image_path is None:
                raise OCRConfigurationError(f"Poppler did not produce an image for page {page_number + 1}")
            with self._image_type.open(image_path) as image:
                data = self._pytesseract.image_to_data(
                    image,
                    config="--oem 3 --psm 6",
                    output_type=self._pytesseract.Output.DICT,
                )
        lines: dict[tuple[int, int, int], list[tuple[str, float, float]]] = defaultdict(list)
        for index, word in enumerate(data["text"]):
            if not word.strip():
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                confidence = -1
            if confidence < 0:
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines[key].append((word.strip(), float(data["top"][index]), float(data["height"][index])))

        records = [
            OCRLine(
                top=min(top for _, top, _ in words),
                text=" ".join(word for word, _, _ in words),
                height=max(height for _, _, height in words),
            )
            for words in lines.values()
        ]
        return sorted(records, key=lambda record: record.top)


@dataclass
class ContentBlock:
    block_type: Literal["text", "list", "table", "tabular_text"]
    text: str = ""
    cells: list[list[str | None]] | None = None
    items: list[str] | None = None


@dataclass
class ParsedNode:
    uid: str
    number: str
    heading: str
    nominal_level: int
    depth: int
    numbering_gap: bool
    parent_uid: str | None
    blocks: list[ContentBlock] = field(default_factory=list)
    children: list["ParsedNode"] = field(default_factory=list)

    @property
    def body_text(self) -> str:
        parts: list[str] = []
        for block in self.blocks:
            if block.block_type == "table" and block.cells:
                parts.append("\n".join(" | ".join(cell or "" for cell in row) for row in block.cells))
            elif block.block_type == "list" and block.items:
                parts.append("\n".join(block.items))
            else:
                parts.append(block.text)
        return "\n".join(part for part in parts if part)


@dataclass
class ParsedDocument:
    source: str
    nodes: list[ParsedNode]
    title: str = ""

    def flatten(self) -> list[ParsedNode]:
        result: list[ParsedNode] = []

        def visit(node: ParsedNode) -> None:
            result.append(node)
            for child in node.children:
                visit(child)

        for node in self.nodes:
            visit(node)
        return result


def _line_records(page: pdfplumber.page.Page) -> list[tuple[float, str, bool]]:
    """Return visual lines, retaining boldness used for heading recognition."""
    words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=True)
    grouped: list[list[dict]] = []
    for word in words:
        if not grouped or abs(float(grouped[-1][0]["top"]) - float(word["top"])) > 1.0:
            grouped.append([word])
        else:
            grouped[-1].append(word)
    return [
        (
            float(words_on_line[0]["top"]),
            " ".join(word["text"] for word in words_on_line),
            all("Bold" in word["fontname"] for word in words_on_line),
        )
        for words_on_line in grouped
    ]


def _cover_title(page: pdfplumber.page.Page) -> str:
    """Extract the cover's large-font title, excluding the first section heading."""
    words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=True)
    grouped: list[list[dict]] = []
    for word in words:
        if not grouped or abs(float(grouped[-1][0]["top"]) - float(word["top"])) > 1.0:
            grouped.append([word])
        else:
            grouped[-1].append(word)
    title_lines = [
        " ".join(word["text"] for word in line)
        for line in grouped
        if float(line[0]["top"]) < 180 and all(float(word["size"]) >= 20 for word in line)
    ]
    return " ".join(title_lines)


def _heading(line: str, is_bold: bool) -> tuple[str, str, int] | None:
    match = HEADING_RE.match(line)
    if not match or not is_bold:
        return None
    number = match.group("number").rstrip(".")
    # Lists are regular text in this document; bold heading styling guards
    # against interpreting the numbered classification list as headings.
    return number, match.group("title"), len(number.split("."))


def _ocr_heading(line: str, line_height: float, median_height: float) -> tuple[str, str, int] | None:
    """CT-200 OCR heading rule when PDF font metadata is unavailable.

    Tesseract does not report bold font information. CT-200 headings are
    numbered and visually prominent, while the numbered clinical list uses a
    colon after its label. This conservative rule is only used for OCR pages.
    """
    match = HEADING_RE.match(line)
    if not match or ":" in match.group("title"):
        return None
    # Main headings are larger than prose. Subheadings share body size in this
    # manual, so their dotted numbering remains an additional CT-200 signal.
    number = match.group("number").rstrip(".")
    is_dotted_section = "." in number
    is_large_top_level = line_height >= median_height * 1.12
    if not (is_dotted_section or is_large_top_level):
        return None
    return number, match.group("title"), len(number.split("."))


def _ocr_cover_title(lines: list[OCRLine]) -> str:
    """Use pre-heading lines as a best-effort title for an image-only cover."""
    if not lines:
        return ""
    typical_height = median(line.height for line in lines)
    title_lines: list[str] = []
    for line in lines:
        if _ocr_heading(line.text, line.height, typical_height):
            break
        title_lines.append(line.text)
    return " ".join(title_lines)


def _real_tables(page: pdfplumber.page.Page) -> list[tuple[tuple[float, float, float, float], list[list[str | None]]]]:
    """Keep only the largest cell-boundary table in each overlapping region."""
    candidates = []
    for table in page.find_tables():
        rows = table.extract()
        if len(rows) < 2 or max((len(row) for row in rows), default=0) < 2:
            continue
        x0, top, x1, bottom = table.bbox
        candidates.append(((x0, top, x1, bottom), rows))
    candidates.sort(key=lambda item: (item[0][2] - item[0][0]) * (item[0][3] - item[0][1]), reverse=True)
    accepted: list[tuple[tuple[float, float, float, float], list[list[str | None]]]] = []
    for bbox, rows in candidates:
        x0, top, x1, bottom = bbox
        if any(x0 >= ax0 and top >= atop and x1 <= ax1 and bottom <= abottom for (ax0, atop, ax1, abottom), _ in accepted):
            continue
        accepted.append((bbox, rows))
    return accepted


def _in_table(top: float, tables: list[tuple[tuple[float, float, float, float], list[list[str | None]]]]) -> bool:
    return any(table_top - 1 <= top <= table_bottom + 1 for (_, table_top, _, table_bottom), _ in tables)


def _append_body_line(node: ParsedNode, line: str) -> None:
    if LIST_ITEM_RE.match(line):
        if node.blocks and node.blocks[-1].block_type == "list":
            node.blocks[-1].items = (node.blocks[-1].items or []) + [line]
        else:
            node.blocks.append(ContentBlock("list", items=[line]))
    elif node.blocks and node.blocks[-1].block_type == "list":
        # The final hypertensive-crisis item wraps onto a continuation line.
        node.blocks[-1].items[-1] += " " + line
    elif node.blocks and node.blocks[-1].block_type == "text":
        node.blocks[-1].text += " " + line
    else:
        node.blocks.append(ContentBlock("text", text=line))


def parse_ct200_pdf(path: str | Path, extraction_mode: ExtractionMode = "auto") -> ParsedDocument:
    """Reconstruct the CT-200 tree using native text, OCR, or automatic choice.

    ``auto`` uses the PDF text layer when present and OCR for image-only pages.
    ``ocr`` forces Tesseract for every page, which is useful for validating the
    OCR path against the supplied manual. ``native`` requires embedded text.
    """
    if extraction_mode not in {"auto", "native", "ocr"}:
        raise ValueError("extraction_mode must be one of: auto, native, ocr")
    roots: list[ParsedNode] = []
    stack: list[ParsedNode] = []
    current: ParsedNode | None = None
    sequence = 0
    title = ""
    ocr: TesseractOCR | None = None

    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages):
            native_lines = _line_records(page)
            use_ocr = extraction_mode == "ocr" or (extraction_mode == "auto" and not native_lines)
            if extraction_mode == "native" and not native_lines:
                raise OCRConfigurationError(
                    f"Page {page_number + 1} has no embedded text. Use extraction_mode='auto' or 'ocr'."
                )
            if use_ocr:
                if ocr is None:
                    ocr = TesseractOCR(path)
                ocr_lines = ocr.line_records(page_number)
                lines = [(line.top, line.text, line.height) for line in ocr_lines]
                typical_height = median(line.height for line in ocr_lines) if ocr_lines else 1.0
                if page_number == 0:
                    title = _ocr_cover_title(ocr_lines)
            else:
                lines = [(top, line, is_bold) for top, line, is_bold in native_lines]
                typical_height = 0.0
                if page_number == 0:
                    title = _cover_title(page)
            tables = _real_tables(page)
            pending_tables = sorted(tables, key=lambda item: item[0][1])
            inserted: set[int] = set()
            for top, line, line_height in lines:
                # A table can be followed immediately by a heading; flush it
                # before changing the current section in that case.
                if current:
                    for index, (bbox, cells) in enumerate(pending_tables):
                        if index not in inserted and top > bbox[3] + 1:
                            current.blocks.append(ContentBlock("table", cells=cells))
                            inserted.add(index)
                detected = _ocr_heading(line, line_height, typical_height) if use_ocr else _heading(line, bool(line_height))
                if detected:
                    number, heading_title, level = detected
                    sequence += 1
                    while stack and stack[-1].nominal_level >= level:
                        stack.pop()
                    # A number can skip a level (2.1 -> 2.1.1.1).  It is
                    # attached to the closest real ancestor, never to an
                    # invented placeholder section.
                    parent = stack[-1] if stack else None
                    depth = (parent.depth + 1) if parent else 1
                    expected_parent_number = ".".join(number.split(".")[:-1])
                    numbering_gap = bool(parent and parent.number != expected_parent_number)
                    node = ParsedNode(
                        f"parsed-{sequence}",
                        number,
                        heading_title,
                        level,
                        depth,
                        numbering_gap,
                        parent.uid if parent else None,
                    )
                    if parent:
                        parent.children.append(node)
                    else:
                        roots.append(node)
                    stack.append(node)
                    current = node
                    continue

                if current is None:
                    continue  # cover title and pre-section whitespace
                if not _in_table(top, pending_tables):
                    _append_body_line(current, line)
            if current:
                for index, (_, cells) in enumerate(pending_tables):
                    if index not in inserted:
                        current.blocks.append(ContentBlock("table", cells=cells))
    return ParsedDocument(str(path), roots, title)
