from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
BULLET = re.compile(r"^[-*]\s+(.+)$")
NUMBERED = re.compile(r"^\d+[.)]\s+(.+)$")
INLINE = re.compile(r"(\*\*.+?\*\*|`.+?`|\*.+?\*)")


def _input() -> str:
    value = json.load(sys.stdin)
    if not isinstance(value, dict) or not isinstance(value.get("content"), str):
        raise ValueError("documents content must be a string")
    content = value["content"].strip()
    if not content:
        raise ValueError("documents content is empty")
    return content


def _set_font(run, *, size: float | None = None, bold: bool | None = None) -> None:
    run.font.name = "Arial"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def _add_inline(paragraph, text: str) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            _set_font(run, bold=True)
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Courier New"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            _set_font(run)
            run.italic = True
        else:
            run = paragraph.add_run(part)
            _set_font(run)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _shade(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def _add_table(document: Document, rows: list[list[str]]) -> None:
    width = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=width)
    table.style = "Table Grid"
    for row_index, values in enumerate(rows):
        for column_index in range(width):
            text = values[column_index] if column_index < len(values) else ""
            cell = table.cell(row_index, column_index)
            cell.text = ""
            _add_inline(cell.paragraphs[0], text)
            if row_index == 0:
                _shade(cell, "D9EAF7")
                for run in cell.paragraphs[0].runs:
                    run.bold = True


def _configure(document: Document) -> None:
    section = document.sections[0]
    section.start_type = WD_SECTION.NEW_PAGE
    section.top_margin = Cm(2.4)
    section.bottom_margin = Cm(2.4)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)

    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.15
    for level, size in ((1, 18), (2, 15), (3, 13)):
        style = document.styles[f"Heading {level}"]
        style.font.name = "Arial"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(31, 78, 121)


def _render(content: str, output_path: Path) -> None:
    document = Document()
    _configure(document)
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if (
            "|" in line
            and index + 1 < len(lines)
            and _is_separator(lines[index + 1].strip())
        ):
            rows = [_cells(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_cells(lines[index]))
                index += 1
            _add_table(document, rows)
            continue
        heading = HEADING.match(line)
        if heading:
            paragraph = document.add_heading(level=len(heading.group(1)))
            _add_inline(paragraph, heading.group(2))
        elif match := BULLET.match(line):
            paragraph = document.add_paragraph(style="List Bullet")
            _add_inline(paragraph, match.group(1))
        elif match := NUMBERED.match(line):
            paragraph = document.add_paragraph(style="List Number")
            _add_inline(paragraph, match.group(1))
        elif line.startswith("> "):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Cm(0.7)
            _add_inline(paragraph, line[2:])
            for run in paragraph.runs:
                run.italic = True
        else:
            paragraph = document.add_paragraph()
            _add_inline(paragraph, line)
        index += 1
    document.save(output_path)


def main() -> None:
    output_path = Path(os.environ["NEXAFLOW_OUTPUT_PATH"])
    if output_path.suffix.lower() != ".docx":
        raise ValueError("documents Skill requires a .docx filename")
    _render(_input(), output_path)
    verified = Document(output_path)
    text = "".join(paragraph.text for paragraph in verified.paragraphs).strip()
    table_text = "".join(
        cell.text for table in verified.tables for row in table.rows for cell in row.cells
    ).strip()
    if not text and not table_text:
        raise ValueError("generated DOCX is empty")
    print(
        json.dumps(
            {
                "renderer": "documents",
                "paragraphs": len(verified.paragraphs),
                "tables": len(verified.tables),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
