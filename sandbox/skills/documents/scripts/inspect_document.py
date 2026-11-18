"""Batch DOCX inspection with physical cell indices and source-hash cache invalidation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 24000


def _cm(length):
    return length.cm if length is not None else None


def _text(element, limit=240):
    text = "".join(node.text or "" for node in element.iter(qn("w:t")))
    return {"text": text[:limit], "text_characters": len(text)}


def _paragraph(paragraph, index):
    formatting = paragraph.paragraph_format
    return {
        "paragraph": index,
        **_text(paragraph._p),
        "style": paragraph.style.name,
        "alignment": int(paragraph.alignment)
        if paragraph.alignment is not None
        else None,
        "first_line_indent_pt": formatting.first_line_indent.pt
        if formatting.first_line_indent is not None
        else None,
        "fonts": sorted({run.font.name for run in paragraph.runs if run.font.name})[:8],
        "font_sizes_pt": sorted(
            {run.font.size.pt for run in paragraph.runs if run.font.size}
        )[:8],
    }


def inspect_document(
    path: Path,
    *,
    tables: list[int] | None = None,
    row_start=0,
    row_limit=40,
    cache: Path | None = None,
) -> dict:
    path = Path(path)
    if path.suffix.lower() != ".docx" or not 0 < path.stat().st_size <= 5 * 1024 * 1024:
        raise ValueError("Input must be a DOCX file no larger than 5 MiB.")
    if (
        row_start < 0
        or not 1 <= row_limit <= 100
        or (
            tables is not None
            and (not tables or any(type(i) is not int or i < 0 for i in tables))
        )
    ):
        raise ValueError("Invalid table or row selection.")
    if cache is not None and cache.resolve() == path.resolve():
        raise ValueError("The cache must not replace the source document.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    selection = {"tables": tables, "row_start": row_start, "row_limit": row_limit}
    cache_key = {
        "schema_version": SCHEMA_VERSION,
        "source_sha256": digest,
        "file": path.name,
        "selection": selection,
    }
    if (
        cache is not None
        and cache.is_file()
        and cache.stat().st_size <= MAX_REPORT_BYTES * 2
    ):
        try:
            stored = json.loads(cache.read_text(encoding="utf-8"))
            report = stored["report"]
            if (
                stored["key"] == cache_key
                and report["source_sha256"] == digest
                and len(json.dumps(report, ensure_ascii=False).encode())
                <= MAX_REPORT_BYTES
            ):
                return report
        except (ValueError, KeyError, TypeError, UnicodeError):
            pass
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 4096
            or sum(item.file_size for item in entries) > 64 * 1024 * 1024
        ):
            raise ValueError("Document package is too large to inspect.")
        if archive.testzip() is not None:
            raise ValueError("Document ZIP integrity check failed.")
        parts = [item.filename for item in entries]
    document = Document(path)
    selected = (
        list(range(len(document.tables)))
        if tables is None
        else list(dict.fromkeys(tables))
    )
    if any(index >= len(document.tables) for index in selected):
        raise ValueError("Selected table does not exist.")
    report = {
        **cache_key,
        "file": path.name,
        "paragraph_count": len(document.paragraphs),
        "table_count": len(document.tables),
        "sections": [
            {
                "page_width_cm": _cm(section.page_width),
                "page_height_cm": _cm(section.page_height),
                "left_margin_cm": _cm(section.left_margin),
                "right_margin_cm": _cm(section.right_margin),
            }
            for section in list(document.sections)[:8]
        ],
        "package": {
            "zip_integrity": "passed",
            "entries": len(parts),
            "media_parts": sum(p.startswith("word/media/") for p in parts),
        },
        "paragraphs": [],
        "tables": [],
        "truncated": False,
        "warnings": [
            "Indices are zero-based. cell is a physical w:tc index, not python-docx row.cells; grid_column includes merged spans and omitted leading cells. Nested table text is included in its parent cell; inspect nested XML when editing it."
        ],
    }
    # Reserve overhead for counts and table/row containers; model output stays
    # below bash's limit. A narrow selection can retrieve any omitted cells.
    remaining = 16000

    def append(items, item):
        nonlocal remaining
        cost = len(json.dumps(item, ensure_ascii=False).encode()) + 2
        if cost > remaining:
            report["truncated"] = True
            return False
        items.append(item)
        remaining -= cost
        return True

    for index, paragraph in enumerate(document.paragraphs if tables is None else []):
        if paragraph.text.strip() and not append(
            report["paragraphs"], _paragraph(paragraph, index)
        ):
            break
    for index in selected:
        table = document.tables[index]
        item = {
            "table": index,
            "row_count": len(table.rows),
            "grid_columns": len(table.columns),
            "rows": [],
        }
        if not append(report["tables"], item):
            break
        for row_index in range(row_start, min(len(table.rows), row_start + row_limit)):
            row = table.rows[row_index]
            raw_cells = row._tr.findall(qn("w:tc"))
            row_item = {"row": row_index, "cell_count": len(raw_cells), "cells": []}
            if not append(item["rows"], row_item):
                break
            before = row._tr.find(qn("w:trPr") + "/" + qn("w:gridBefore"))
            column = int(before.get(qn("w:val"), "0")) if before is not None else 0
            for cell_index, cell in enumerate(raw_cells):
                span = cell.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                merge = cell.find(qn("w:tcPr") + "/" + qn("w:vMerge"))
                width = cell.find(qn("w:tcPr") + "/" + qn("w:tcW"))
                grid_span = int(span.get(qn("w:val"), "1")) if span is not None else 1
                paragraphs = cell.findall(qn("w:p"))
                cell_item = {
                    "cell": cell_index,
                    "grid_column": column,
                    "grid_span": grid_span,
                    "vertical_merge": merge.get(qn("w:val"), "continue")
                    if merge is not None
                    else None,
                    "width_twips": width.get(qn("w:w")) if width is not None else None,
                    **_text(cell, 160),
                    "paragraph_count": len(paragraphs),
                    "style": Paragraph(paragraphs[0], table).style.name
                    if paragraphs
                    else None,
                }
                if not append(row_item["cells"], cell_item):
                    break
                column += grid_span
            if len(row_item["cells"]) < len(raw_cells):
                break
        if row_start + len(item["rows"]) < len(table.rows):
            report["truncated"] = True
    if len(json.dumps(report, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
        raise ValueError(
            "Inspection is too large; narrow the --tables and --row-limit selection."
        )
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=cache.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(
                    {"key": cache_key, "report": report}, stream, ensure_ascii=False
                )
                stream.close()
                os.replace(temporary, cache)
            finally:
                temporary.unlink(missing_ok=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--tables", type=int, nargs="+")
    parser.add_argument("--row-start", type=int, default=0)
    parser.add_argument("--row-limit", type=int, default=40)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            inspect_document(
                args.document,
                tables=args.tables,
                row_start=args.row_start,
                row_limit=args.row_limit,
                cache=args.cache,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
