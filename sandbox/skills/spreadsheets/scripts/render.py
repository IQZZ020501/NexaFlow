from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


INVALID_SHEET_TITLE = re.compile(r"[\\/*?:\[\]]")


def _input() -> list[dict]:
    value = json.load(sys.stdin)
    workbook = value.get("workbook") if isinstance(value, dict) else None
    sheets = workbook.get("sheets") if isinstance(workbook, dict) else None
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= 16:
        raise ValueError("workbook.sheets must contain 1 to 16 sheets")
    names: set[str] = set()
    for sheet in sheets:
        if not isinstance(sheet, dict):
            raise ValueError("each sheet must be an object")
        name = sheet.get("name")
        rows = sheet.get("rows")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 31
            or INVALID_SHEET_TITLE.search(name)
            or name in names
        ):
            raise ValueError("sheet name is invalid or duplicated")
        if not isinstance(rows, list) or not rows or len(rows) > 2_000:
            raise ValueError("sheet rows must contain 1 to 2000 rows")
        if any(not isinstance(row, list) or len(row) > 64 for row in rows):
            raise ValueError("each workbook row must contain at most 64 cells")
        if any(
            value is not None
            and not isinstance(value, (str, int, float, bool))
            for row in rows
            for value in row
        ):
            raise ValueError("workbook cells must be JSON scalar values")
        normalized_name = name.casefold()
        if normalized_name in names:
            raise ValueError("sheet name is invalid or duplicated")
        names.add(normalized_name)
    return sheets


def _width(value: object) -> int:
    text = "" if value is None else str(value)
    wide = sum(2 if ord(character) > 127 else 1 for character in text)
    return min(max(wide + 2, 10), 40)


def _render(sheets: list[dict], output_path: Path) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for sheet_spec in sheets:
        sheet = workbook.create_sheet(sheet_spec["name"])
        rows = sheet_spec["rows"]
        for row in rows:
            sheet.append(row)
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = sheet_spec.get("freeze_panes") or (
            "A2" if len(rows) > 1 else None
        )
        if sheet_spec.get("auto_filter", True) and sheet.max_column:
            sheet.auto_filter.ref = sheet.dimensions
        for column_index in range(1, sheet.max_column + 1):
            width = max(
                _width(sheet.cell(row_index, column_index).value)
                for row_index in range(1, sheet.max_row + 1)
            )
            sheet.column_dimensions[get_column_letter(column_index)].width = width
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    workbook.active = 0
    workbook.save(output_path)


def main() -> None:
    output_path = Path(os.environ["NEXAFLOW_OUTPUT_PATH"])
    if output_path.suffix.lower() != ".xlsx":
        raise ValueError("spreadsheets Skill requires a .xlsx filename")
    sheets = _input()
    _render(sheets, output_path)
    verified = load_workbook(output_path, read_only=False, data_only=False)
    if verified.sheetnames != [sheet["name"] for sheet in sheets]:
        raise ValueError("generated XLSX sheet names do not match the request")
    if any(verified[name].max_row < 1 for name in verified.sheetnames):
        raise ValueError("generated XLSX contains an empty sheet")
    print(
        json.dumps(
            {
                "renderer": "spreadsheets",
                "sheets": len(verified.sheetnames),
                "rows": sum(verified[name].max_row for name in verified.sheetnames),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
