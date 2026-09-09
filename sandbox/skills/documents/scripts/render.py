from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from io import BytesIO
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
BULLET = re.compile(r"^[-*]\s+(.+)$")
NUMBERED = re.compile(r"^\d+[.)]\s+(.+)$")
INLINE = re.compile(r"(\*\*.+?\*\*|`.+?`|\*.+?\*)")
REPORT_STYLE = "report"
FORMAL_LEGAL_STYLE = "formal_legal"
MAX_REFERENCE_DOCX_BYTES = 5 * 1024 * 1024
MAX_REFERENCE_DOCX_BASE64_CHARS = ((MAX_REFERENCE_DOCX_BYTES + 2) // 3) * 4
MAX_CONTENT_CHARS = 200_000

_LEGAL_TITLE_MARKERS = (
    "申请书",
    "起诉状",
    "答辩状",
    "上诉状",
    "反诉状",
    "仲裁申请",
    "调解书",
    "判决书",
    "裁定书",
    "授权委托书",
    "公函",
    "声明书",
)
_LEGAL_SECTION_MARKERS = (
    "仲裁请求",
    "诉讼请求",
    "事实与理由",
    "事实和理由",
    "证据",
    "申请人",
    "被申请人",
    "原告",
    "被告",
)
_ARBITRATION_FEE_REQUEST = re.compile(
    r"(?:仲裁(?:费用|费)|仲裁收费)[^\n。；]{0,120}"
    r"(?:由|应由|要求[^\n。；]{0,30}由)[^\n。；]{0,40}"
    r"被申请人[^\n。；]{0,20}承担"
)
_ARBITRATION_FEE_FREE = re.compile(
    r"(?:劳动仲裁|仲裁)[^\n。；]{0,20}"
    r"(?:不收费|无需收费|不需要收费|免收(?:费|费用)?)"
)

PAGE_WIDTH_CM = 21.0
PAGE_HEIGHT_CM = 29.7
TABLE_USABLE_DXA = 9071  # A4 width 21cm minus 2.5cm side margins
TABLE_INDENT_DXA = 120
CELL_MARGIN_DXA = 120


def _resolve_cjk_font(*, formal: bool = False) -> str | None:
    """Return the platform CJK family without probing from an isolated child."""
    configured = os.environ.get("NEXAFLOW_CJK_FONT", "").strip()
    if configured:
        return configured
    if formal:
        return {
            "linux": "Noto Serif CJK SC",
            "darwin": "Songti SC",
        }.get(sys.platform)
    return {
        "linux": "Noto Serif CJK SC",
        "darwin": "Songti SC",
    }.get(sys.platform)


CJK_FONT = _resolve_cjk_font()
FORMAL_CJK_FONT = _resolve_cjk_font(formal=True)


def _display_units(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        for character in value
    )


def _looks_formal_legal(content: str) -> bool:
    """Recognize an unstyled legal document without changing ordinary reports."""
    normalized = re.sub(r"\s+", "", content)
    first_heading = next(
        (
            match.group(2)
            for line in content.splitlines()
            if (match := HEADING.match(line.strip())) and len(match.group(1)) == 1
        ),
        "",
    )
    if any(marker in first_heading for marker in _LEGAL_TITLE_MARKERS):
        return True
    matches = sum(marker in normalized for marker in _LEGAL_SECTION_MARKERS)
    return matches >= 3 and any(marker in normalized for marker in _LEGAL_TITLE_MARKERS)


def _validate_content_consistency(content: str) -> None:
    if _ARBITRATION_FEE_REQUEST.search(content) and _ARBITRATION_FEE_FREE.search(
        content
    ):
        raise ValueError(
            "formal_legal content contains conflicting arbitration fee statements: "
            "an arbitration-fee payment request conflicts with a statement that "
            "labor arbitration is free"
        )


def _decode_reference_docx(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("reference_docx_base64 must be a non-empty base64 string")
    if len(value) > MAX_REFERENCE_DOCX_BASE64_CHARS:
        raise ValueError("reference DOCX exceeds the 5 MiB limit")
    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("reference_docx_base64 is not valid base64") from exc
    if not content or len(content) > MAX_REFERENCE_DOCX_BYTES:
        raise ValueError("reference DOCX exceeds the 5 MiB limit")
    try:
        Document(BytesIO(content))
    except Exception as exc:
        raise ValueError("reference_docx_base64 is not a valid DOCX") from exc
    return content


def _input() -> tuple[str, str, bytes | None]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict) or not isinstance(value.get("content"), str):
        raise ValueError("documents content must be a string")
    content = value["content"].strip()
    if not content:
        raise ValueError("documents content is empty")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError("documents content exceeds the 200000 character limit")
    requested_style = value.get("style")
    style = (
        (FORMAL_LEGAL_STYLE if _looks_formal_legal(content) else REPORT_STYLE)
        if requested_style is None
        else requested_style
    )
    if not isinstance(style, str) or style not in {REPORT_STYLE, FORMAL_LEGAL_STYLE}:
        raise ValueError("documents style must be report or formal_legal")
    _validate_content_consistency(content)
    return content, style, _decode_reference_docx(value.get("reference_docx_base64"))


def _set_east_asia_font(target, font: str | None = CJK_FONT) -> None:
    if not font:
        return
    r_pr = target._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, r_fonts)
    r_fonts.set(qn("w:eastAsia"), font)


def _set_font(
    run,
    *,
    size: float | None = None,
    bold: bool | None = None,
    formal: bool = False,
    template_run=None,
) -> None:
    if template_run is not None:
        if template_run._r.rPr is not None:
            existing = run._r.rPr
            if existing is not None:
                run._r.remove(existing)
            run._r.insert(0, deepcopy(template_run._r.rPr))
    else:
        run.font.name = "Times New Roman" if formal else "Arial"
        _set_east_asia_font(run, FORMAL_CJK_FONT if formal else CJK_FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def _add_inline(
    paragraph,
    text: str,
    *,
    formal: bool = False,
    template_run=None,
) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            _set_font(run, bold=True, formal=formal, template_run=template_run)
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            if template_run is None:
                run.font.name = "Courier New"
                _set_east_asia_font(run, FORMAL_CJK_FONT if formal else CJK_FONT)
            else:
                _set_font(run, formal=formal, template_run=template_run)
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            _set_font(run, formal=formal, template_run=template_run)
            run.italic = True
        else:
            run = paragraph.add_run(part)
            _set_font(run, formal=formal, template_run=template_run)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _copy_paragraph_format(target, source) -> None:
    """Copy the layout-bearing paragraph properties from a reference DOCX."""
    target.style = source.style.name
    source_format = source.paragraph_format
    target_format = target.paragraph_format
    for name in (
        "alignment",
        "left_indent",
        "right_indent",
        "first_line_indent",
        "space_before",
        "space_after",
        "line_spacing",
        "keep_with_next",
        "keep_together",
        "page_break_before",
        "widow_control",
    ):
        value = getattr(source_format, name)
        if value is not None:
            setattr(target_format, name, value)


def _reference_templates(document: Document) -> dict[str, object]:
    paragraphs = [
        paragraph for paragraph in document.paragraphs if paragraph.text.strip()
    ]
    title = paragraphs[0] if paragraphs else None
    body = paragraphs[1] if len(paragraphs) > 1 else title
    signature = next(
        (
            paragraph
            for paragraph in paragraphs
            if paragraph.alignment == WD_ALIGN_PARAGRAPH.RIGHT
            or any(
                keyword in paragraph.text for keyword in ("申请人", "落款", "日期")
            )
        ),
        body,
    )
    return {"title": title, "body": body, "signature": signature}


def _clear_document_body(document: Document) -> None:
    body = document._element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def _shade(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def _table_column_widths(rows: list[list[str]], count: int) -> list[int]:
    natural = []
    for column_index in range(count):
        units = max(
            _display_units(str(row[column_index]))
            for row in rows
            if column_index < len(row)
        )
        natural.append(min(max(units * 110 + 240, 900), 3600))
    total = sum(natural)
    scale = TABLE_USABLE_DXA / total
    widths = [max(int(value * scale), 1) for value in natural]
    widths[-1] += TABLE_USABLE_DXA - sum(widths)
    return widths


def _apply_table_geometry(table, rows: list[list[str]], count: int) -> None:
    widths = _table_column_widths(rows, count)
    total = sum(widths)
    tbl_pr = table._tbl.tblPr

    def insert(element) -> None:
        lookup = tbl_pr.find(qn("w:tblLook"))
        if lookup is not None:
            lookup.addprevious(element)
        else:
            tbl_pr.append(element)

    table.autofit = False
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        insert(tbl_w)
    tbl_w.set(qn("w:w"), str(total))
    tbl_w.set(qn("w:type"), "dxa")
    for element in tbl_pr.findall(qn("w:tblInd")):
        tbl_pr.remove(element)
    tbl_ind = OxmlElement("w:tblInd")
    tbl_ind.set(qn("w:w"), str(TABLE_INDENT_DXA))
    tbl_ind.set(qn("w:type"), "dxa")
    insert(tbl_ind)
    for element in tbl_pr.findall(qn("w:tblLayout")):
        tbl_pr.remove(element)
    tbl_layout = OxmlElement("w:tblLayout")
    tbl_layout.set(qn("w:type"), "fixed")
    insert(tbl_layout)
    for element in tbl_pr.findall(qn("w:tblCellMar")):
        tbl_pr.remove(element)
    cell_mar = OxmlElement("w:tblCellMar")
    for side in ("top", "bottom", "start", "end"):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(CELL_MARGIN_DXA))
        node.set(qn("w:type"), "dxa")
        cell_mar.append(node)
    insert(cell_mar)
    grid = table._tbl.find(qn("w:tblGrid"))
    for grid_col, column_width in zip(grid.findall(qn("w:gridCol")), widths):
        grid_col.set(qn("w:w"), str(column_width))
    for row_index, row in enumerate(table.rows):
        row_properties = row._tr.get_or_add_trPr()
        if row_index == 0:
            row_properties.append(OxmlElement("w:tblHeader"))
        cant_split = OxmlElement("w:cantSplit")
        row_properties.append(cant_split)
        for column_index, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                shading = tc_pr.find(qn("w:shd"))
                if shading is not None:
                    shading.addprevious(tc_w)
                else:
                    tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths[column_index]))
            tc_w.set(qn("w:type"), "dxa")
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _add_table(
    document: Document,
    rows: list[list[str]],
    *,
    formal: bool = False,
    template_paragraph=None,
) -> None:
    width = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=width)
    table.style = "Table Grid"
    for row_index, values in enumerate(rows):
        for column_index in range(width):
            text = values[column_index] if column_index < len(values) else ""
            cell = table.cell(row_index, column_index)
            cell.text = ""
            if template_paragraph is not None:
                _copy_paragraph_format(cell.paragraphs[0], template_paragraph)
            _add_inline(
                cell.paragraphs[0],
                text,
                formal=formal,
                template_run=(
                    template_paragraph.runs[0]
                    if template_paragraph and template_paragraph.runs
                    else None
                ),
            )
            if formal:
                cell.paragraphs[0].paragraph_format.first_line_indent = Pt(0)
            if row_index == 0:
                _shade(cell, "E7E6E6" if formal else "D9EAF7")
                for run in cell.paragraphs[0].runs:
                    run.bold = True
    _apply_table_geometry(table, rows, width)


def _add_page_number_footer(section) -> None:
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    _set_font(run, size=9)
    run.font.color.rgb = RGBColor(89, 89, 89)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instruction, end):
        run._r.append(element)


def _configure(document: Document, *, formal: bool = False) -> None:
    section = document.sections[0]
    section.start_type = WD_SECTION.NEW_PAGE
    section.page_width = Cm(PAGE_WIDTH_CM)
    section.page_height = Cm(PAGE_HEIGHT_CM)
    section.top_margin = Cm(2.4)
    section.bottom_margin = Cm(2.4)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)
    if not formal:
        _add_page_number_footer(section)

    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman" if formal else "Arial"
    _set_east_asia_font(normal, FORMAL_CJK_FONT if formal else CJK_FONT)
    normal.font.size = Pt(12 if formal else 11)
    normal.paragraph_format.space_after = Pt(0 if formal else 7)
    normal.paragraph_format.line_spacing = 1.4 if formal else 1.15
    normal.paragraph_format.first_line_indent = Pt(24) if formal else None
    normal.paragraph_format.widow_control = True
    for level, size in ((1, 18), (2, 15), (3, 13)):
        style = document.styles[f"Heading {level}"]
        style.font.name = "Arial"
        _set_east_asia_font(style)
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(31, 78, 121)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.keep_together = True


def _render(
    content: str,
    output_path: Path,
    style: str = REPORT_STYLE,
    reference_docx: bytes | None = None,
) -> None:
    formal = style == FORMAL_LEGAL_STYLE
    document = Document(BytesIO(reference_docx)) if reference_docx else Document()
    templates = _reference_templates(document) if reference_docx else {}
    if reference_docx:
        _clear_document_body(document)
    else:
        _configure(document, formal=formal)
    lines = content.splitlines()
    index = 0
    first_h1 = True
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if formal and line == "---":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.first_line_indent = Pt(0)
            paragraph.add_run().add_break(WD_BREAK.PAGE)
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
            _add_table(
                document,
                rows,
                formal=formal,
                template_paragraph=templates.get("body"),
            )
            continue
        heading = HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            paragraph = (
                document.add_paragraph()
                if formal
                else document.add_heading(level=level)
            )
            template = templates.get("title" if level == 1 and first_h1 else "body")
            if template is not None:
                _copy_paragraph_format(paragraph, template)
            _add_inline(
                paragraph,
                heading.group(2),
                formal=formal,
                template_run=(template.runs[0] if template and template.runs else None),
            )
            if formal:
                if template is None:
                    paragraph.paragraph_format.first_line_indent = Pt(0)
                    paragraph.paragraph_format.keep_with_next = True
                    paragraph.paragraph_format.keep_together = True
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.size = Pt({1: 18, 2: 14, 3: 12}[level])
                        run.font.color.rgb = RGBColor(0, 0, 0)
                if level == 1 and first_h1:
                    if template is None:
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    first_h1 = False
        elif match := BULLET.match(line):
            paragraph = document.add_paragraph(
                style="Normal" if formal else "List Bullet"
            )
            template = templates.get("body")
            if template is not None:
                _copy_paragraph_format(paragraph, template)
            _add_inline(
                paragraph,
                line if formal else match.group(1),
                formal=formal,
                template_run=(template.runs[0] if template and template.runs else None),
            )
            if formal:
                if template is None:
                    paragraph.paragraph_format.first_line_indent = Pt(0)
        elif match := NUMBERED.match(line):
            paragraph = document.add_paragraph(
                style="Normal" if formal else "List Number"
            )
            template = templates.get("body")
            if template is not None:
                _copy_paragraph_format(paragraph, template)
            _add_inline(
                paragraph,
                line if formal else match.group(1),
                formal=formal,
                template_run=(template.runs[0] if template and template.runs else None),
            )
            if formal:
                if template is None:
                    paragraph.paragraph_format.first_line_indent = Pt(0)
        elif line.startswith("> "):
            paragraph = document.add_paragraph()
            template = templates.get("signature")
            if template is not None:
                _copy_paragraph_format(paragraph, template)
            else:
                paragraph.paragraph_format.first_line_indent = Pt(0)
            _add_inline(
                paragraph,
                line[2:],
                formal=formal,
                template_run=(template.runs[0] if template and template.runs else None),
            )
            if formal:
                if template is None:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            else:
                paragraph.paragraph_format.left_indent = Cm(0.7)
                for run in paragraph.runs:
                    run.italic = True
        else:
            paragraph = document.add_paragraph()
            template = templates.get("body")
            if template is not None:
                _copy_paragraph_format(paragraph, template)
            _add_inline(
                paragraph,
                line,
                formal=formal,
                template_run=(template.runs[0] if template and template.runs else None),
            )
        index += 1
    document.save(output_path)


def _verify_layout(
    document: Document, content: str, style: str, has_reference: bool
) -> None:
    formal = style == FORMAL_LEGAL_STYLE
    paragraphs = [
        paragraph for paragraph in document.paragraphs if paragraph.text.strip()
    ]
    if not paragraphs:
        raise ValueError("generated DOCX contains no non-empty paragraphs")
    if formal:
        if any(
            paragraph.style.name.startswith(("Heading", "List"))
            for paragraph in document.paragraphs
        ):
            raise ValueError(
                "formal_legal output must use unified body paragraph styles"
            )
        title = paragraphs[0]
        if not has_reference and title.alignment != WD_ALIGN_PARAGRAPH.CENTER:
            raise ValueError("formal_legal title must be centered")
        if not has_reference and any(
            run.font.color.rgb not in (None, RGBColor(0, 0, 0)) for run in title.runs
        ):
            raise ValueError("formal_legal title must be black")
        signature_lines = [
            line[2:]
            for line in content.splitlines()
            if line.startswith("> ")
        ]
        paragraph_map = {paragraph.text: paragraph for paragraph in document.paragraphs}
        if any(
            paragraph_map.get(line) is None
            or paragraph_map[line].alignment != WD_ALIGN_PARAGRAPH.RIGHT
            for line in signature_lines
        ) and not has_reference:
            raise ValueError("formal_legal signature/date lines must be right aligned")
        expected_breaks = sum(line.strip() == "---" for line in content.splitlines())
        actual_breaks = sum(
            1
            for paragraph in document.paragraphs
            for run in paragraph.runs
            for break_node in run._r.findall(qn("w:br"))
            if break_node.get(qn("w:type")) == "page"
        )
        if actual_breaks != expected_breaks:
            raise ValueError("formal_legal page-break markers were not preserved")
    section = document.sections[0]
    if section.page_width is None or section.page_height is None:
        raise ValueError("generated DOCX has no usable page geometry")


def main() -> None:
    output_path = Path(os.environ["NEXAFLOW_OUTPUT_PATH"])
    if output_path.suffix.lower() != ".docx":
        raise ValueError("documents Skill requires a .docx filename")
    content, style, reference_docx = _input()
    _render(content, output_path, style, reference_docx)
    verified = Document(output_path)
    _verify_layout(verified, content, style, reference_docx is not None)
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
