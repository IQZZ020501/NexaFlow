from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5
LAYOUTS = {"section", "bullets", "two_column", "icons", "table"}
TEMPLATES = {
    "minimal": {
        "background": "F8FAFC",
        "text": "0F172A",
        "primary": "2563EB",
        "font": "Arial",
    },
    "editorial": {
        "background": "F6F0E7",
        "text": "2C2420",
        "primary": "A33A3A",
        "font": "Georgia",
    },
    "bold": {
        "background": "111827",
        "text": "F9FAFB",
        "primary": "22D3EE",
        "font": "Arial",
    },
}
ICONS = {
    "bolt": MSO_SHAPE.LIGHTNING_BOLT,
    "cloud": MSO_SHAPE.CLOUD,
    "cycle": MSO_SHAPE.CIRCULAR_ARROW,
    "direction": MSO_SHAPE.RIGHT_ARROW,
    "focus": MSO_SHAPE.DIAMOND,
    "gear": MSO_SHAPE.GEAR_6,
    "growth": MSO_SHAPE.UP_ARROW,
    "heart": MSO_SHAPE.HEART,
    "star": MSO_SHAPE.STAR_5_POINT,
    "sun": MSO_SHAPE.SUN,
}


def _display_units(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        for character in value
    )


def _text(
    value: object,
    field: str,
    *,
    max_chars: int,
    max_units: int | None = None,
    optional: bool = False,
    single_line: bool = False,
) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    result = value.strip()
    if not result and not optional:
        raise ValueError(f"{field} is empty")
    if not result:
        return None
    if len(result) > max_chars:
        raise ValueError(f"{field} is too long")
    if single_line and ("\n" in result or "\r" in result):
        raise ValueError(f"{field} must be one line")
    if any(
        ord(character) < 32 and character not in {"\n", "\r", "\t"}
        for character in result
    ):
        raise ValueError(f"{field} contains control characters")
    if max_units is not None and _display_units(result) > max_units:
        raise ValueError(f"{field} is too wide for its slide layout")
    return result


def _text_list(
    value: object,
    field: str,
    *,
    maximum: int,
    item_units: int,
    total_units: int,
) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} must contain 1 to {maximum} items")
    items = [
        _text(
            item,
            f"{field}[{index}]",
            max_chars=240,
            max_units=item_units,
        )
        for index, item in enumerate(value)
    ]
    normalized = [item for item in items if item is not None]
    if sum(_display_units(item) for item in normalized) > total_units:
        raise ValueError(f"{field} contains too much text")
    return normalized


def _keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ValueError(f"{field} contains unsupported fields: {', '.join(unexpected)}")


def _column(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    _keys(value, {"heading", "bullets"}, field)
    return {
        "heading": _text(
            value.get("heading"),
            f"{field}.heading",
            max_chars=60,
            max_units=36,
            single_line=True,
        ),
        "bullets": _text_list(
            value.get("bullets"),
            f"{field}.bullets",
            maximum=5,
            item_units=100,
            total_units=320,
        ),
    }


def _icon_items(value: object, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4:
        raise ValueError(f"{field} must contain 2 to 4 items")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        name = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{name} must be an object")
        _keys(item, {"icon", "title", "body"}, name)
        icon = item.get("icon")
        if icon not in ICONS:
            raise ValueError(f"{name}.icon is unsupported")
        result.append(
            {
                "icon": icon,
                "title": _text(
                    item.get("title"),
                    f"{name}.title",
                    max_chars=48,
                    max_units=28,
                    single_line=True,
                ),
                "body": _text(
                    item.get("body"),
                    f"{name}.body",
                    max_chars=180,
                    max_units=90,
                ),
            }
        )
    return result


def _table(value: object, field: str) -> dict[str, list]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    _keys(value, {"headers", "rows"}, field)
    headers = _text_list(
        value.get("headers"),
        f"{field}.headers",
        maximum=5,
        item_units=32,
        total_units=140,
    )
    if len(headers) < 2:
        raise ValueError(f"{field}.headers must contain 2 to 5 items")
    rows = value.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 7:
        raise ValueError(f"{field}.rows must contain 1 to 7 rows")
    normalized_rows: list[list[str]] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(headers):
            raise ValueError(f"{field}.rows[{row_index}] must match the headers")
        normalized_row: list[str] = []
        for column_index, cell in enumerate(row):
            cell_name = f"{field}.rows[{row_index}][{column_index}]"
            if cell is None:
                normalized = ""
            elif isinstance(cell, bool):
                normalized = str(cell)
            elif isinstance(cell, (int, float)) and not isinstance(cell, bool):
                if isinstance(cell, float) and not math.isfinite(cell):
                    raise ValueError(f"{cell_name} must be finite")
                normalized = str(cell)
            else:
                normalized = _text(
                    cell,
                    cell_name,
                    max_chars=100,
                    max_units=50,
                    optional=True,
                ) or ""
            normalized_row.append(normalized)
        normalized_rows.append(normalized_row)
    return {"headers": headers, "rows": normalized_rows}


def _brand(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("presentation.brand must be an object")
    _keys(
        value,
        {"primary_color", "background_color", "text_color", "font_family"},
        "presentation.brand",
    )
    result: dict[str, str] = {}
    for key in ("primary_color", "background_color", "text_color"):
        color = value.get(key)
        if not isinstance(color, str) or HEX_COLOR.fullmatch(color) is None:
            raise ValueError(f"presentation.brand.{key} must be a #RRGGBB color")
        result[key] = color[1:].upper()
    font = _text(
        value.get("font_family"),
        "presentation.brand.font_family",
        max_chars=64,
        max_units=64,
        single_line=True,
    )
    result["font_family"] = font or "Arial"
    return result


def _slide(value: object, index: int) -> dict[str, Any]:
    field = f"presentation.slides[{index}]"
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    _keys(
        value,
        {
            "layout",
            "title",
            "subtitle",
            "bullets",
            "left",
            "right",
            "items",
            "table",
            "notes",
        },
        field,
    )
    layout = value.get("layout")
    if layout not in LAYOUTS:
        raise ValueError(f"{field}.layout is unsupported")
    allowed_fields = {
        "section": {"subtitle"},
        "bullets": {"bullets"},
        "two_column": {"left", "right"},
        "icons": {"items"},
        "table": {"table"},
    }[layout]
    for content_field in {"subtitle", "bullets", "left", "right", "items", "table"}:
        if content_field in value and content_field not in allowed_fields:
            raise ValueError(f"{field}.{content_field} does not match layout {layout}")
    result: dict[str, Any] = {
        "layout": layout,
        "title": _text(
            value.get("title"),
            f"{field}.title",
            max_chars=90,
            # Keep the 36pt header on one line; the fixed-height title box cannot
            # safely accommodate wrapped text above the divider.
            max_units=30,
            single_line=True,
        ),
        "notes": _text(
            value.get("notes"),
            f"{field}.notes",
            max_chars=4_000,
            optional=True,
        ),
    }
    if layout == "section":
        result["subtitle"] = _text(
            value.get("subtitle"),
            f"{field}.subtitle",
            max_chars=240,
            max_units=140,
            optional=True,
        )
    elif layout == "bullets":
        result["bullets"] = _text_list(
            value.get("bullets"),
            f"{field}.bullets",
            maximum=6,
            item_units=150,
            total_units=520,
        )
    elif layout == "two_column":
        result["left"] = _column(value.get("left"), f"{field}.left")
        result["right"] = _column(value.get("right"), f"{field}.right")
    elif layout == "icons":
        result["items"] = _icon_items(value.get("items"), f"{field}.items")
    else:
        result["table"] = _table(value.get("table"), f"{field}.table")
    return result


def _input() -> dict[str, Any]:
    value = json.load(sys.stdin)
    presentation = value.get("presentation") if isinstance(value, dict) else None
    if not isinstance(presentation, dict):
        raise ValueError("presentation must be an object")
    _keys(
        presentation,
        {"title", "subtitle", "template", "brand", "footer", "slides"},
        "presentation",
    )
    template = presentation.get("template", "minimal")
    if template not in TEMPLATES:
        raise ValueError("presentation.template is unsupported")
    slides = presentation.get("slides")
    if not isinstance(slides, list) or not 1 <= len(slides) <= 30:
        raise ValueError("presentation.slides must contain 1 to 30 slides")
    return {
        "title": _text(
            presentation.get("title"),
            "presentation.title",
            max_chars=120,
            max_units=78,
        ),
        "subtitle": _text(
            presentation.get("subtitle"),
            "presentation.subtitle",
            max_chars=240,
            max_units=130,
            optional=True,
        ),
        "template": template,
        "brand": _brand(presentation.get("brand")),
        "footer": _text(
            presentation.get("footer"),
            "presentation.footer",
            max_chars=100,
            max_units=80,
            optional=True,
            single_line=True,
        ),
        "slides": [_slide(slide, index) for index, slide in enumerate(slides)],
    }


def _tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _mix(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    second_weight: float,
) -> tuple[int, int, int]:
    return tuple(
        round(a * (1 - second_weight) + b * second_weight)
        for a, b in zip(first, second, strict=True)
    )


def _luminance(color: tuple[int, int, int]) -> float:
    channels = []
    for value in color:
        channel = value / 255
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _style(presentation: dict[str, Any]) -> dict[str, Any]:
    template = TEMPLATES[presentation["template"]]
    background = _tuple(template["background"])
    text = _tuple(template["text"])
    primary = _tuple(template["primary"])
    font = template["font"]
    if brand := presentation["brand"]:
        background = _tuple(brand["background_color"])
        text = _tuple(brand["text_color"])
        primary = _tuple(brand["primary_color"])
        font = brand["font_family"]
    if _contrast(background, text) < 4.5:
        raise ValueError("presentation brand text and background need 4.5:1 contrast")
    if _contrast(background, primary) < 1.8:
        raise ValueError("presentation brand primary color must contrast with the background")
    black = (0, 0, 0)
    white = (255, 255, 255)
    primary_text = white if _contrast(primary, white) >= _contrast(primary, black) else black
    return {
        "background": background,
        "text": text,
        "primary": primary,
        "primary_text": primary_text,
        "muted": _mix(text, background, 0.55),
        "surface": _mix(background, text, 0.06),
        "alternate": _mix(background, primary, 0.08),
        "font": font,
        "template": presentation["template"],
    }


def _rgb(color: tuple[int, int, int]) -> RGBColor:
    return RGBColor(*color)


def _background(slide, color: tuple[int, int, int]) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(color)


def _rect(slide, left: float, top: float, width: float, height: float, color):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()
    return shape


def _text_box(
    slide,
    text: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    size: float,
    color: tuple[int, int, int],
    font: str,
    bold: bool = False,
    alignment=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
):
    shape = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    frame.vertical_anchor = anchor
    paragraph = frame.paragraphs[0]
    paragraph.alignment = alignment
    paragraph.space_after = Pt(0)
    run = paragraph.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = _rgb(color)
    return shape


def _bullets(
    slide,
    items: list[str],
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    size: float,
    color: tuple[int, int, int],
    font: str,
) -> None:
    shape = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    for index, item in enumerate(items):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(10 if size >= 20 else 7)
        paragraph.line_spacing = 1.08
        run = paragraph.add_run()
        run.text = f"• {item}"
        run.font.name = font
        run.font.size = Pt(size)
        run.font.color.rgb = _rgb(color)


def _footer(slide, footer: str | None, slide_number: int, style: dict[str, Any]) -> None:
    if footer:
        _text_box(
            slide,
            footer,
            0.8,
            7.08,
            10.8,
            0.22,
            size=10,
            color=style["muted"],
            font=style["font"],
        )
    _text_box(
        slide,
        str(slide_number),
        12.0,
        7.05,
        0.5,
        0.24,
        size=10,
        color=style["muted"],
        font=style["font"],
        alignment=PP_ALIGN.RIGHT,
    )


def _header(slide, title: str, style: dict[str, Any]) -> float:
    template = style["template"]
    if template == "bold":
        _rect(slide, 0, 0, 0.18, SLIDE_HEIGHT, style["primary"])
        left, top = 0.75, 0.58
    elif template == "editorial":
        _rect(slide, 0.8, 0.42, 1.35, 0.05, style["primary"])
        left, top = 0.8, 0.72
    else:
        left, top = 0.8, 0.55
    _text_box(
        slide,
        title,
        left,
        top,
        11.75,
        0.7,
        size=36,
        color=style["text"],
        font=style["font"],
        bold=True,
    )
    if template != "editorial":
        _rect(slide, left, 1.42, 11.75, 0.05, style["primary"])
    return 1.78


def _notes(slide, notes: str | None) -> None:
    if notes:
        frame = slide.notes_slide.notes_text_frame
        frame.clear()
        frame.text = notes


def _cover(slide, presentation: dict[str, Any], style: dict[str, Any]) -> None:
    _background(slide, style["background"])
    template = style["template"]
    if template == "editorial":
        _rect(slide, 1.2, 1.25, 10.9, 0.06, style["primary"])
        _text_box(
            slide,
            presentation["title"],
            1.1,
            2.0,
            11.1,
            1.7,
            size=52,
            color=style["text"],
            font=style["font"],
            bold=True,
            alignment=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        subtitle_top = 4.15
    elif template == "bold":
        _rect(slide, 0, 0, 1.15, SLIDE_HEIGHT, style["primary"])
        _text_box(
            slide,
            presentation["title"],
            1.75,
            1.6,
            10.4,
            2.0,
            size=54,
            color=style["text"],
            font=style["font"],
            bold=True,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        subtitle_top = 4.05
    else:
        _rect(slide, 0.85, 1.1, 0.12, 4.8, style["primary"])
        _text_box(
            slide,
            presentation["title"],
            1.35,
            1.55,
            10.8,
            2.0,
            size=52,
            color=style["text"],
            font=style["font"],
            bold=True,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        subtitle_top = 4.0
    if presentation["subtitle"]:
        _text_box(
            slide,
            presentation["subtitle"],
            1.35,
            subtitle_top,
            10.6,
            0.9,
            size=24,
            color=style["muted"],
            font=style["font"],
            alignment=PP_ALIGN.CENTER if template == "editorial" else PP_ALIGN.LEFT,
        )


def _section_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> None:
    _background(slide, style["background"])
    if style["template"] == "bold":
        _rect(slide, 0, 2.05, SLIDE_WIDTH, 2.9, style["primary"])
        title_color = style["primary_text"]
        muted = _mix(style["primary_text"], style["primary"], 0.35)
    else:
        _rect(slide, 4.85, 1.65, 3.65, 0.07, style["primary"])
        title_color = style["text"]
        muted = style["muted"]
    _text_box(
        slide,
        spec["title"],
        1.05,
        2.35,
        11.2,
        1.15,
        size=46,
        color=title_color,
        font=style["font"],
        bold=True,
        alignment=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    if spec["subtitle"]:
        _text_box(
            slide,
            spec["subtitle"],
            1.5,
            3.75,
            10.3,
            0.8,
            size=24,
            color=muted,
            font=style["font"],
            alignment=PP_ALIGN.CENTER,
        )


def _bullet_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> None:
    _background(slide, style["background"])
    top = _header(slide, spec["title"], style)
    total = sum(_display_units(item) for item in spec["bullets"])
    size = 24 if len(spec["bullets"]) <= 4 and total <= 320 else 20
    _bullets(
        slide,
        spec["bullets"],
        1.0,
        top,
        11.1,
        4.95,
        size=size,
        color=style["text"],
        font=style["font"],
    )


def _two_column_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> None:
    _background(slide, style["background"])
    top = _header(slide, spec["title"], style)
    _rect(slide, 6.63, top, 0.035, 4.75, style["muted"])
    for left, column in ((0.95, spec["left"]), (6.9, spec["right"])):
        _text_box(
            slide,
            column["heading"],
            left,
            top,
            5.45,
            0.55,
            size=24,
            color=style["primary"],
            font=style["font"],
            bold=True,
        )
        _bullets(
            slide,
            column["bullets"],
            left,
            top + 0.75,
            5.35,
            3.9,
            size=18,
            color=style["text"],
            font=style["font"],
        )


def _icons_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> None:
    _background(slide, style["background"])
    top = _header(slide, spec["title"], style)
    items = spec["items"]
    gap = 0.32
    width = (11.45 - gap * (len(items) - 1)) / len(items)
    for index, item in enumerate(items):
        left = 0.95 + index * (width + gap)
        icon = slide.shapes.add_shape(
            ICONS[item["icon"]],
            Inches(left + width / 2 - 0.34),
            Inches(top + 0.25),
            Inches(0.68),
            Inches(0.68),
        )
        icon.fill.solid()
        icon.fill.fore_color.rgb = _rgb(style["primary"])
        icon.line.fill.background()
        _text_box(
            slide,
            item["title"],
            left,
            top + 1.2,
            width,
            0.55,
            size=24,
            color=style["text"],
            font=style["font"],
            bold=True,
            alignment=PP_ALIGN.CENTER,
        )
        _text_box(
            slide,
            item["body"],
            left,
            top + 1.95,
            width,
            2.2,
            size=17,
            color=style["muted"],
            font=style["font"],
            alignment=PP_ALIGN.CENTER,
        )


def _table_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> None:
    _background(slide, style["background"])
    top = _header(slide, spec["title"], style)
    headers = spec["table"]["headers"]
    rows = spec["table"]["rows"]
    shape = slide.shapes.add_table(
        len(rows) + 1,
        len(headers),
        Inches(0.8),
        Inches(top),
        Inches(11.75),
        Inches(4.95),
    )
    table = shape.table
    table.first_row = True
    table.horz_banding = False
    for column in table.columns:
        column.width = Inches(11.75 / len(headers))
    row_height = 4.95 / (len(rows) + 1)
    for row in table.rows:
        row.height = Inches(row_height)
    values = [headers, *rows]
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            cell = table.cell(row_index, column_index)
            cell.text = value
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.08)
            cell.margin_top = Inches(0.04)
            cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(
                style["primary"]
                if row_index == 0
                else style["alternate"] if row_index % 2 == 0 else style["surface"]
            )
            for paragraph in cell.text_frame.paragraphs:
                paragraph.alignment = PP_ALIGN.LEFT
                for run in paragraph.runs:
                    run.font.name = style["font"]
                    run.font.size = Pt(16)
                    run.font.bold = row_index == 0
                    run.font.color.rgb = _rgb(
                        style["primary_text"] if row_index == 0 else style["text"]
                    )


def _verify(path: Path, expected_slides: int, expected_notes: list[str | None]) -> None:
    presentation = Presentation(path)
    if len(presentation.slides) != expected_slides:
        raise ValueError("generated PPTX slide count does not match the request")
    tolerance = Inches(0.01)
    for index, slide in enumerate(presentation.slides):
        visible_text = "".join(
            shape.text for shape in slide.shapes if hasattr(shape, "text")
        ).strip()
        if not visible_text:
            raise ValueError(f"generated PPTX slide {index + 1} is empty")
        for shape in slide.shapes:
            if (
                shape.left < -tolerance
                or shape.top < -tolerance
                or shape.left + shape.width > presentation.slide_width + tolerance
                or shape.top + shape.height > presentation.slide_height + tolerance
            ):
                raise ValueError(f"generated PPTX slide {index + 1} exceeds the canvas")
    for index, notes in enumerate(expected_notes, start=1):
        if notes and notes not in presentation.slides[index].notes_slide.notes_text_frame.text:
            raise ValueError(f"generated PPTX slide {index + 1} lost its speaker notes")


def _render(presentation: dict[str, Any], output_path: Path) -> int:
    style = _style(presentation)
    deck = Presentation()
    deck.slide_width = Inches(SLIDE_WIDTH)
    deck.slide_height = Inches(SLIDE_HEIGHT)
    deck.core_properties.title = presentation["title"]
    blank = deck.slide_layouts[6]

    cover = deck.slides.add_slide(blank)
    _cover(cover, presentation, style)
    for index, spec in enumerate(presentation["slides"], start=2):
        slide = deck.slides.add_slide(blank)
        {
            "section": _section_slide,
            "bullets": _bullet_slide,
            "two_column": _two_column_slide,
            "icons": _icons_slide,
            "table": _table_slide,
        }[spec["layout"]](slide, spec, style)
        _notes(slide, spec["notes"])
        _footer(slide, presentation["footer"], index, style)
    deck.save(output_path)
    _verify(
        output_path,
        len(presentation["slides"]) + 1,
        [slide["notes"] for slide in presentation["slides"]],
    )
    return len(deck.slides)


def main() -> None:
    output_path = Path(os.environ["NEXAFLOW_OUTPUT_PATH"])
    if output_path.suffix.lower() != ".pptx":
        raise ValueError("pptx Skill requires a .pptx filename")
    presentation = _input()
    slides = _render(presentation, output_path)
    print(
        json.dumps(
            {
                "renderer": "pptx",
                "slides": slides,
                "template": presentation["template"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
