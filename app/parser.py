"""A deliberately CT-200-specific PDF hierarchy parser.

The manual is born-digital.  We use pdfplumber here because this execution
environment blocks the PyMuPDF native extension under Application Control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pdfplumber


HEADING_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)*\.?)\s+(?P<title>.+)$")


@dataclass
class ContentBlock:
    block_type: Literal["text", "table", "tabular_text"]
    text: str = ""
    cells: list[list[str | None]] | None = None


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
            else:
                parts.append(block.text)
        return "\n".join(part for part in parts if part)


@dataclass
class ParsedDocument:
    source: str
    nodes: list[ParsedNode]

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


def _heading(line: str, is_bold: bool) -> tuple[str, str, int] | None:
    match = HEADING_RE.match(line)
    if not match or not is_bold:
        return None
    number = match.group("number").rstrip(".")
    # Lists are regular text in this document; bold heading styling guards
    # against interpreting the numbered classification list as headings.
    return number, match.group("title"), len(number.split("."))


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


def parse_ct200_pdf(path: str | Path) -> ParsedDocument:
    """Reconstruct the numbered CT-200 tree without normalizing anomalies."""
    roots: list[ParsedNode] = []
    stack: list[ParsedNode] = []
    current: ParsedNode | None = None
    sequence = 0

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = _real_tables(page)
            pending_tables = sorted(tables, key=lambda item: item[0][1])
            inserted: set[int] = set()
            for top, line, is_bold in _line_records(page):
                # A table can be followed immediately by a heading; flush it
                # before changing the current section in that case.
                if current:
                    for index, (bbox, cells) in enumerate(pending_tables):
                        if index not in inserted and top > bbox[3] + 1:
                            current.blocks.append(ContentBlock("table", cells=cells))
                            inserted.add(index)
                detected = _heading(line, is_bold)
                if detected:
                    number, title, level = detected
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
                        title,
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
                    if current.blocks and current.blocks[-1].block_type == "text":
                        current.blocks[-1].text += " " + line
                    else:
                        current.blocks.append(ContentBlock("text", text=line))
            if current:
                for index, (_, cells) in enumerate(pending_tables):
                    if index not in inserted:
                        current.blocks.append(ContentBlock("table", cells=cells))
    return ParsedDocument(str(path), roots)
