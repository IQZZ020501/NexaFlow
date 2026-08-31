from __future__ import annotations

import html
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pymupdf


HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
BULLET = re.compile(r"^[-*]\s+(.+)$")
NUMBERED = re.compile(r"^\d+[.)]\s+(.+)$")


def _input() -> str:
    value = json.load(sys.stdin)
    if not isinstance(value, dict) or not isinstance(value.get("content"), str):
        raise ValueError("pdf content must be a string")
    content = value["content"].strip()
    if not content:
        raise ValueError("pdf content is empty")
    return content


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    return escaped


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _html(content: str) -> str:
    lines = content.splitlines()
    parts: list[str] = []
    list_kind: str | None = None

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is not None:
            parts.append(f"</{list_kind}>")
            list_kind = None

    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            close_list()
            index += 1
            continue
        if (
            "|" in line
            and index + 1 < len(lines)
            and _is_separator(lines[index + 1].strip())
        ):
            close_list()
            rows = [_cells(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_cells(lines[index]))
                index += 1
            parts.append("<table><thead><tr>")
            parts.extend(f"<th>{_inline(cell)}</th>" for cell in rows[0])
            parts.append("</tr></thead><tbody>")
            for row in rows[1:]:
                parts.append("<tr>")
                parts.extend(f"<td>{_inline(cell)}</td>" for cell in row)
                parts.append("</tr>")
            parts.append("</tbody></table>")
            continue
        heading = HEADING.match(line)
        if heading:
            close_list()
            level = len(heading.group(1))
            parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif match := BULLET.match(line):
            if list_kind != "ul":
                close_list()
                list_kind = "ul"
                parts.append("<ul>")
            parts.append(f"<li>{_inline(match.group(1))}</li>")
        elif match := NUMBERED.match(line):
            if list_kind != "ol":
                close_list()
                list_kind = "ol"
                parts.append("<ol>")
            parts.append(f"<li>{_inline(match.group(1))}</li>")
        elif line.startswith("> "):
            close_list()
            parts.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        else:
            close_list()
            parts.append(f"<p>{_inline(line)}</p>")
        index += 1
    close_list()
    return "".join(parts)


def _render(content: str, output_path: Path) -> int:
    css = """
        body { font-family: "Noto Sans CJK SC", "PingFang SC", sans-serif; font-size: 10.5pt; line-height: 1.45; color: #202124; }
        h1 { font-size: 22pt; color: #1f4e79; margin: 0 0 12pt 0; }
        h2 { font-size: 16pt; color: #1f4e79; margin: 14pt 0 6pt 0; }
        h3 { font-size: 13pt; color: #2f5597; margin: 10pt 0 4pt 0; }
        h1, h2, h3 { break-after: avoid; }
        p { margin: 0 0 7pt 0; }
        li { margin-bottom: 3pt; }
        blockquote { margin: 8pt 18pt; padding: 6pt 10pt; background: #eef4f8; }
        table { width: 100%; border-collapse: collapse; margin: 8pt 0 12pt 0; }
        thead { display: table-header-group; }
        tr { break-inside: avoid; }
        th, td { border: 0.6pt solid #9aa7b2; padding: 5pt; vertical-align: top; }
        th { background: #d9eaf7; font-weight: bold; }
        code { font-family: monospace; background: #f3f4f5; }
    """
    story = pymupdf.Story(html=_html(content), user_css=css)
    page_rect = pymupdf.paper_rect("a4")
    content_rect = pymupdf.Rect(54, 54, page_rect.width - 54, page_rect.height - 54)
    writer = pymupdf.DocumentWriter(str(output_path))
    more = True
    pages = 0
    while more:
        if pages >= 100:
            raise ValueError("PDF exceeds the 100 page Skill limit")
        device = writer.begin_page(page_rect)
        more, _filled = story.place(content_rect)
        story.draw(device)
        writer.end_page()
        pages += 1
    writer.close()
    return pages


def _add_page_numbers(output_path: Path) -> None:
    document = pymupdf.open(output_path)
    try:
        for index, page in enumerate(document, start=1):
            page.insert_text(
                (page.rect.width - 60, page.rect.height - 24),
                str(index),
                fontname="helv",
                fontsize=8,
                color=(0.35, 0.35, 0.35),
            )
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, suffix=".pdf", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            temporary_path.unlink()
            document.save(temporary_path)
        finally:
            document.close()
        temporary_path.replace(output_path)
    except BaseException:
        document.close()
        raise


def main() -> None:
    output_path = Path(os.environ["NEXAFLOW_OUTPUT_PATH"])
    if output_path.suffix.lower() != ".pdf":
        raise ValueError("pdf Skill requires a .pdf filename")
    pages = _render(_input(), output_path)
    _add_page_numbers(output_path)
    with pymupdf.open(output_path) as document:
        extracted = "".join(page.get_text() for page in document).strip()
        page_text = [page.get_text().strip() for page in document]
        page_rects = [page.rect for page in document]
        a4 = pymupdf.paper_rect("a4")
        if (
            document.page_count != pages
            or not extracted
            or any(not text for text in page_text)
            or any(
                abs(rect.width - a4.width) > 1 or abs(rect.height - a4.height) > 1
                for rect in page_rects
            )
        ):
            raise ValueError("generated PDF failed structural verification")
    print(json.dumps({"renderer": "pdf", "pages": pages}, separators=(",", ":")))


if __name__ == "__main__":
    main()
