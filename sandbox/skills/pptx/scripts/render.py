from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5
LAYOUTS = {
    "section",
    "bullets",
    "two_column",
    "icons",
    "table",
    "hero",
    "stats",
    "steps",
    "quote",
}
# Codex Grid-style design tokens: white canvas, black type, light gray
# structural panels, thin rules, one deliberate accent. Editorial and bold
# keep the same layout system with their own neutral palette.
TEMPLATES = {
    "minimal": {
        "background": "FFFFFF",
        "text": "000000",
        "primary": "3D8DFF",
        "panel": "F2F2F2",
        "rule": "B8BCC4",
        "font": "Arial",
        "heading_font": "Arial",
        "title_size": 35,
        "body_size": 18,
        "corner_radius": 0.0,
        "cover_accent_width": 0.18,
        "title_alignment": "left",
    },
    "editorial": {
        "background": "F6F0E7",
        "text": "2C2420",
        "primary": "A33A3A",
        "panel": "ECE4D8",
        "rule": "C9BBA8",
        "font": "Georgia",
        "heading_font": "Georgia",
        "title_size": 35,
        "body_size": 18,
        "corner_radius": 0.04,
        "cover_accent_width": 0.18,
        "title_alignment": "left",
    },
    "bold": {
        "background": "111827",
        "text": "F9FAFB",
        "primary": "22D3EE",
        "panel": "1F2937",
        "rule": "374151",
        "font": "Arial",
        "heading_font": "Arial",
        "title_size": 35,
        "body_size": 18,
        "corner_radius": 0.02,
        "cover_accent_width": 1.15,
        "title_alignment": "left",
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

# Grid geometry (1280x720 px frame => 13.333 x 7.5 in): 41.33px margins.
MARGIN = 0.43
CONTENT_WIDTH = 12.47
TITLE_TOP = 0.38
TITLE_HEIGHT = 1.15
TITLE_SIZE = 35
CONTENT_TOP = 1.78
COVER_TITLE_TOP = 1.9
COVER_TITLE_HEIGHT = 2.72
COVER_TITLE_SIZE = 60
SUBTITLE_TOP = 5.19
PAGE_NUMBER_LEFT = 12.34
PAGE_NUMBER_TOP = 6.87
CHROME_SIZE = 10
COLUMN_GAP = 0.75
TABLE_HEIGHT = 4.95
TABLE_MIN_ROW_HEIGHT = 0.42

_FONT_SUCCESSORS = (
    qn("a:cs"),
    qn("a:sym"),
    qn("a:hlinkClick"),
    qn("a:hlinkMouseOver"),
    qn("a:rtl"),
    qn("a:extLst"),
)
_TABLE_GRID_STYLE = "{5940675A-B579-460E-94D1-54222C63F5DA}"
_THEME_COLOR_FIELDS = {
    "background_color": "background",
    "text_color": "text",
    "accent_color": "primary",
    "panel_color": "panel",
    "muted_text_color": "muted",
    "rule_color": "rule",
}


def _resolve_cjk_font() -> str | None:
    """Return the platform CJK family without probing from an isolated child."""
    configured = os.environ.get("NEXAFLOW_CJK_FONT", "").strip()
    if configured:
        return configured
    return {
        "linux": "Noto Serif CJK SC",
        "darwin": "Songti SC",
    }.get(sys.platform)


CJK_FONT = _resolve_cjk_font()


def _set_run_font(run, font: str) -> None:
    run.font.name = font
    if not CJK_FONT:
        return
    r_pr = run._r.get_or_add_rPr()
    east = r_pr.find(qn("a:ea"))
    if east is None:
        east = r_pr.makeelement(qn("a:ea"), {})
        for successor in _FONT_SUCCESSORS:
            anchor = r_pr.find(successor)
            if anchor is not None:
                anchor.addprevious(east)
                break
        else:
            r_pr.append(east)
    east.set("typeface", CJK_FONT)


def _set_theme_cjk_font(deck) -> None:
    if not CJK_FONT:
        return
    theme_part = next(
        (
            part
            for part in deck.part.package.iter_parts()
            if str(part.partname) == "/ppt/theme/theme1.xml"
        ),
        None,
    )
    if theme_part is None:
        return
    root = etree.fromstring(theme_part.blob)
    drawingml = "http://schemas.openxmlformats.org/drawingml/2006/main"
    font_scheme = root.find(f"{{{drawingml}}}themeElements/{{{drawingml}}}fontScheme")
    if font_scheme is None:
        return
    for group_name in ("majorFont", "minorFont"):
        group = font_scheme.find(f"{{{drawingml}}}{group_name}")
        if group is None:
            continue
        east_asia = group.find(f"{{{drawingml}}}ea")
        if east_asia is None:
            east_asia = etree.SubElement(group, f"{{{drawingml}}}ea")
        east_asia.set("typeface", CJK_FONT)
        for font in group.findall(f"{{{drawingml}}}font"):
            if font.get("script") == "Hans":
                font.set("typeface", CJK_FONT)
                break
    theme_part._blob = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def _display_units(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        for character in value
    )


def _estimate_text_width(text: str, size: float) -> float:
    """Estimated rendered width in inches for a font size in points."""
    total = 0.0
    for character in text:
        if unicodedata.east_asian_width(character) in {"W", "F", "A"}:
            total += size
        elif character in "ilI.,:;'|!()[]{} ":
            total += size * 0.3
        else:
            total += size * 0.55
    return total / 72.0 * 1.06


def _estimate_text_height(
    text: str,
    size: float,
    width: float,
    *,
    line_spacing: float = 1.12,
    paragraph_gap: float = 0.0,
) -> float:
    """Conservative text height estimate in inches for a fixed text box."""
    if width <= 0:
        return float("inf")
    lines = text.splitlines() or [""]
    line_count = sum(
        max(1, math.ceil(_estimate_text_width(line, size) / width)) for line in lines
    )
    line_height = size / 72.0 * 1.25 * line_spacing
    return line_count * line_height + max(0, len(lines) - 1) * paragraph_gap


def _require_text_fit(
    text: str,
    size: float,
    width: float,
    height: float,
    field: str,
    *,
    paragraph_gap: float = 0.0,
) -> None:
    estimated = _estimate_text_height(
        text, size, width, paragraph_gap=paragraph_gap
    )
    if estimated > height * 1.04:
        raise ValueError(f"{field} does not fit its text box")


def _fit_size(text: str, max_size: float, width: float, min_size: float = 20) -> float:
    size = max_size
    while size > min_size and _estimate_text_width(text, size) > width:
        size -= 2
    return size


def _fit_multiline_size(
    text: str,
    max_size: float,
    width: float,
    height: float,
    min_size: float = 14,
) -> float:
    size = max_size
    while size > min_size and _estimate_text_height(text, size, width) > height:
        size -= 1
    return size


def _fit_text_size(
    text: str,
    max_size: float,
    width: float,
    height: float,
    *,
    min_size: float,
    single_line: bool = False,
) -> float:
    """Use the layout's readable floor before declaring text impossible."""
    size = (
        _fit_size(text, max_size, width, min_size=min_size)
        if single_line
        else max_size
    )
    return _fit_multiline_size(text, size, width, height, min_size=min_size)


def _require_fit(text: str, size: float, width: float, field: str) -> None:
    if _estimate_text_width(text, size) > width:
        raise ValueError(f"{field} is too wide for its text box")


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


def _stats_items(value: object, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4:
        raise ValueError(f"{field} must contain 2 to 4 items")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        name = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{name} must be an object")
        _keys(item, {"value", "label"}, name)
        raw = item.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise ValueError(f"{name}.value must be a string or number")
        value_text = str(raw).strip()
        if not value_text or len(value_text) > 24:
            raise ValueError(f"{name}.value is invalid")
        result.append(
            {
                "value": value_text,
                "label": _text(
                    item.get("label"),
                    f"{name}.label",
                    max_chars=40,
                ),
            }
        )
    return result


def _steps_items(value: object, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 5:
        raise ValueError(f"{field} must contain 2 to 5 items")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        name = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{name} must be an object")
        _keys(item, {"title", "body"}, name)
        result.append(
            {
                "title": _text(
                    item.get("title"),
                    f"{name}.title",
                    max_chars=60,
                    single_line=True,
                ),
                "body": _text(
                    item.get("body"),
                    f"{name}.body",
                    max_chars=160,
                    max_units=80,
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


def _optional_color(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or HEX_COLOR.fullmatch(value) is None:
        raise ValueError(f"{field} must be a #RRGGBB color")
    return value[1:].upper()


def _optional_number(
    value: object,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
    return result


def _theme(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("presentation.theme must be an object")
    allowed = {
        "background_color",
        "text_color",
        "accent_color",
        "panel_color",
        "muted_text_color",
        "rule_color",
        "font_family",
        "heading_font_family",
        "cover_title_size",
        "slide_title_size",
        "body_size",
        "panel_radius",
        "cover_accent_width",
        "title_alignment",
    }
    _keys(value, allowed, "presentation.theme")
    result: dict[str, Any] = {}
    for key in (
        "background_color",
        "text_color",
        "accent_color",
        "panel_color",
        "muted_text_color",
        "rule_color",
    ):
        color = _optional_color(value.get(key), f"presentation.theme.{key}")
        if color is not None:
            result[key] = color
    for key in ("font_family", "heading_font_family"):
        font = _text(
            value.get(key),
            f"presentation.theme.{key}",
            max_chars=64,
            max_units=64,
            optional=True,
            single_line=True,
        )
        if font is not None:
            result[key] = font
    for key, minimum, maximum in (
        ("cover_title_size", 40, 64),
        ("slide_title_size", 35, 44),
        ("body_size", 16, 24),
        ("panel_radius", 0, 0.18),
        ("cover_accent_width", 0.08, 1.4),
    ):
        number = _optional_number(
            value.get(key),
            f"presentation.theme.{key}",
            minimum=minimum,
            maximum=maximum,
        )
        if number is not None:
            result[key] = number
    alignment = value.get("title_alignment")
    if alignment is not None:
        if alignment not in {"left", "center"}:
            raise ValueError(
                "presentation.theme.title_alignment must be left or center"
            )
        result["title_alignment"] = alignment
    return result


def _slide_style(value: object, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    allowed = {
        "background_color",
        "text_color",
        "accent_color",
        "panel_color",
        "muted_text_color",
        "rule_color",
        "font_family",
        "heading_font_family",
        "title_size",
        "body_size",
        "panel_radius",
        "title_alignment",
    }
    _keys(value, allowed, field)
    result: dict[str, Any] = {}
    for key in (
        "background_color",
        "text_color",
        "accent_color",
        "panel_color",
        "muted_text_color",
        "rule_color",
    ):
        color = _optional_color(value.get(key), f"{field}.{key}")
        if color is not None:
            result[key] = color
    for key in ("font_family", "heading_font_family"):
        font = _text(
            value.get(key),
            f"{field}.{key}",
            max_chars=64,
            max_units=64,
            optional=True,
            single_line=True,
        )
        if font is not None:
            result[key] = font
    for key, minimum, maximum in (
        ("title_size", 35, 44),
        ("body_size", 16, 24),
        ("panel_radius", 0, 0.18),
    ):
        number = _optional_number(
            value.get(key),
            f"{field}.{key}",
            minimum=minimum,
            maximum=maximum,
        )
        if number is not None:
            result[key] = number
    alignment = value.get("title_alignment")
    if alignment is not None:
        if alignment not in {"left", "center"}:
            raise ValueError(f"{field}.title_alignment must be left or center")
        result["title_alignment"] = alignment
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
            "stats",
            "steps",
            "quote",
            "source",
            "notes",
            "style",
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
        "hero": {"subtitle"},
        "stats": {"stats"},
        "steps": {"steps"},
        "quote": {"quote", "source"},
    }[layout]
    content_fields = {
        "subtitle",
        "bullets",
        "left",
        "right",
        "items",
        "table",
        "stats",
        "steps",
        "quote",
        "source",
    }
    required_fields = {
        "bullets": ("bullets",),
        "two_column": ("left", "right"),
        "icons": ("items",),
        "table": ("table",),
        "stats": ("stats",),
        "steps": ("steps",),
        "quote": ("quote",),
    }.get(layout, ())
    for required in required_fields:
        if required not in value:
            raise ValueError(
                f"{field}.{required} is required for the {layout} layout"
            )
    # One line at 35pt in the title band: ~23 CJK chars; the render-time
    # `_require_fit` check is the authoritative gate.
    title_units = 46
    result: dict[str, Any] = {
        "layout": layout,
        "title": _text(
            value.get("title"),
            f"{field}.title",
            max_chars=90,
            max_units=title_units,
            single_line=True,
        ),
        "notes": _text(
            value.get("notes"),
            f"{field}.notes",
            max_chars=4_000,
            optional=True,
        ),
        "style": _slide_style(value.get("style"), f"{field}.style"),
    }
    if layout in {"section", "hero"}:
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
    elif layout == "table":
        result["table"] = _table(value.get("table"), f"{field}.table")
    elif layout == "stats":
        result["stats"] = _stats_items(value.get("stats"), f"{field}.stats")
    elif layout == "steps":
        result["steps"] = _steps_items(value.get("steps"), f"{field}.steps")
    else:
        result["quote"] = _text(
            value.get("quote"),
            f"{field}.quote",
            max_chars=300,
            max_units=170,
        )
        result["source"] = _text(
            value.get("source"),
            f"{field}.source",
            max_chars=120,
            max_units=60,
            optional=True,
        )
    return result


def _input() -> dict[str, Any]:
    value = json.load(sys.stdin)
    presentation = value.get("presentation") if isinstance(value, dict) else None
    if not isinstance(presentation, dict):
        raise ValueError("presentation must be an object")
    _keys(
        presentation,
        {
            "title",
            "subtitle",
            "template",
            "brand",
            "theme",
            "footer",
            "slides",
        },
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
        "theme": _theme(presentation.get("theme")),
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


def _hex(color: tuple[int, int, int]) -> str:
    return "".join(f"{channel:02X}" for channel in color)


def _resolved_style(
    tokens: dict[str, Any],
    *,
    template: str,
    field: str,
) -> dict[str, Any]:
    background = _tuple(tokens["background"])
    text = _tuple(tokens["text"])
    primary = _tuple(tokens["primary"])
    panel = _tuple(tokens["panel"])
    rule = _tuple(tokens["rule"])
    if tokens.get("muted") is not None:
        muted = _tuple(tokens["muted"])
    else:
        muted = _mix(text, background, 0.45)
        if _contrast(background, muted) < 4.5:
            muted = text
    if _contrast(background, text) < 4.5:
        raise ValueError(f"{field} text and background need 4.5:1 contrast")
    if _contrast(panel, text) < 4.5:
        raise ValueError(f"{field} text and panel need 4.5:1 contrast")
    if _contrast(background, muted) < 4.5:
        raise ValueError(f"{field} muted text needs 4.5:1 contrast")
    if _contrast(background, primary) < 1.8:
        raise ValueError(f"{field} accent color must contrast with the background")
    black = (0, 0, 0)
    white = (255, 255, 255)
    primary_text = white if _contrast(primary, white) >= _contrast(primary, black) else black
    return {
        "background": background,
        "text": text,
        "primary": primary,
        "primary_text": primary_text,
        "panel": panel,
        "alternate": _mix(panel, background, 0.45),
        "primary_soft": _mix(primary, background, 0.86),
        "primary_pale": _mix(primary, background, 0.93),
        "rule": rule,
        "muted": muted,
        "font": tokens["font"],
        "heading_font": tokens["heading_font"],
        "cover_title_size": tokens["cover_title_size"],
        "title_size": tokens["title_size"],
        "body_size": tokens["body_size"],
        "corner_radius": tokens["corner_radius"],
        "cover_accent_width": tokens["cover_accent_width"],
        "title_alignment": tokens["title_alignment"],
        "template": template,
    }


def _style(presentation: dict[str, Any]) -> dict[str, Any]:
    template_name = presentation["template"]
    template = TEMPLATES[template_name]
    tokens: dict[str, Any] = {
        "background": template["background"],
        "text": template["text"],
        "primary": template["primary"],
        "panel": template["panel"],
        "rule": template["rule"],
        "muted": None,
        "font": template["font"],
        "heading_font": template["heading_font"],
        "cover_title_size": 56,
        "title_size": template["title_size"],
        "body_size": template["body_size"],
        "corner_radius": template["corner_radius"],
        "cover_accent_width": template["cover_accent_width"],
        "title_alignment": template["title_alignment"],
    }
    if brand := presentation["brand"]:
        tokens.update(
            {
                "background": brand["background_color"],
                "text": brand["text_color"],
                "primary": brand["primary_color"],
                "panel": _hex(
                    _mix(
                        _tuple(brand["background_color"]),
                        _tuple(brand["text_color"]),
                        0.07,
                    )
                ),
                "rule": _hex(
                    _mix(
                        _tuple(brand["background_color"]),
                        _tuple(brand["text_color"]),
                        0.35,
                    )
                ),
                "font": brand["font_family"],
                "heading_font": brand["font_family"],
            }
        )
    if theme := presentation["theme"]:
        for public, internal in _THEME_COLOR_FIELDS.items():
            if public in theme:
                tokens[internal] = theme[public]
        if {"background_color", "text_color"} & theme.keys():
            if "panel_color" not in theme:
                tokens["panel"] = tokens["background"]
            if "rule_color" not in theme:
                tokens["rule"] = _hex(
                    _mix(_tuple(tokens["background"]), _tuple(tokens["text"]), 0.35)
                )
            if "muted_text_color" not in theme:
                tokens["muted"] = None
            if "accent_color" not in theme and _contrast(
                _tuple(tokens["background"]), _tuple(tokens["primary"])
            ) < 1.8:
                tokens["primary"] = tokens["text"]
        if "font_family" in theme:
            tokens["font"] = theme["font_family"]
        if "heading_font_family" in theme:
            tokens["heading_font"] = theme["heading_font_family"]
        for public, internal in (
            ("cover_title_size", "cover_title_size"),
            ("slide_title_size", "title_size"),
            ("body_size", "body_size"),
            ("panel_radius", "corner_radius"),
            ("cover_accent_width", "cover_accent_width"),
            ("title_alignment", "title_alignment"),
        ):
            if public in theme:
                tokens[internal] = theme[public]
    return _resolved_style(tokens, template=template_name, field="presentation.theme")


def _style_for_slide(
    base: dict[str, Any],
    override: dict[str, Any] | None,
    field: str,
) -> dict[str, Any]:
    if not override:
        return base
    tokens: dict[str, Any] = {
        "background": _hex(base["background"]),
        "text": _hex(base["text"]),
        "primary": _hex(base["primary"]),
        "panel": _hex(base["panel"]),
        "rule": _hex(base["rule"]),
        "muted": _hex(base["muted"]),
        "font": base["font"],
        "heading_font": base["heading_font"],
        "cover_title_size": base["cover_title_size"],
        "title_size": base["title_size"],
        "body_size": base["body_size"],
        "corner_radius": base["corner_radius"],
        "cover_accent_width": base["cover_accent_width"],
        "title_alignment": base["title_alignment"],
    }
    for public, internal in _THEME_COLOR_FIELDS.items():
        if public in override:
            tokens[internal] = override[public]
    if {"background_color", "text_color"} & override.keys():
        if "panel_color" not in override:
            tokens["panel"] = tokens["background"]
        if "rule_color" not in override:
            tokens["rule"] = _hex(
                _mix(_tuple(tokens["background"]), _tuple(tokens["text"]), 0.35)
            )
        if "muted_text_color" not in override:
            tokens["muted"] = None
        if "accent_color" not in override and _contrast(
            _tuple(tokens["background"]), _tuple(tokens["primary"])
        ) < 1.8:
            tokens["primary"] = tokens["text"]
    if "font_family" in override:
        tokens["font"] = override["font_family"]
    if "heading_font_family" in override:
        tokens["heading_font"] = override["heading_font_family"]
    for public, internal in (
        ("title_size", "title_size"),
        ("body_size", "body_size"),
        ("panel_radius", "corner_radius"),
        ("title_alignment", "title_alignment"),
    ):
        if public in override:
            tokens[internal] = override[public]
    return _resolved_style(tokens, template=base["template"], field=field)


def _body_size(style: dict[str, Any], baseline: float, minimum: float) -> float:
    return max(minimum, round(baseline * style["body_size"] / 18, 1))


def _alignment(value: str):
    return PP_ALIGN.CENTER if value == "center" else PP_ALIGN.LEFT


def _rgb(color: tuple[int, int, int]) -> RGBColor:
    return RGBColor(*color)


def _background(slide, color: tuple[int, int, int]) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(color)


def _rect(
    slide,
    left: float,
    top: float,
    width: float,
    height: float,
    color: tuple[int, int, int],
    *,
    corner: float = 0.0,
):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if corner else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(
        shape_type,
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
    )
    if corner:
        shape.adjustments[0] = corner
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()
    shape.shadow.inherit = False
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
    fit: bool = False,
    min_size: float | None = None,
    single_line: bool = False,
    field: str = "text box",
):
    actual_size = size
    if fit:
        actual_size = _fit_text_size(
            text,
            size,
            width,
            height,
            min_size=min_size if min_size is not None else max(12, size * 0.75),
            single_line=single_line,
        )
    _require_text_fit(text, actual_size, width, height, field)
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
    _set_run_font(run, font)
    run.font.size = Pt(actual_size)
    run.font.bold = bold
    run.font.color.rgb = _rgb(color)
    return shape


def _rich_text_box(
    slide,
    parts: list[tuple[str, bool, tuple[int, int, int]]],
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    size: float,
    font: str,
    alignment=PP_ALIGN.LEFT,
    fit: bool = False,
    min_size: float | None = None,
    single_line: bool = False,
    field: str = "rich text box",
):
    text = "".join(part[0] for part in parts)
    actual_size = size
    if fit:
        actual_size = _fit_text_size(
            text,
            size,
            width,
            height,
            min_size=min_size if min_size is not None else max(12, size * 0.75),
            single_line=single_line,
        )
    _require_text_fit(text, actual_size, width, height, field)
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
    paragraph = frame.paragraphs[0]
    paragraph.alignment = alignment
    paragraph.space_after = Pt(0)
    for value, bold, color in parts:
        run = paragraph.add_run()
        run.text = value
        _set_run_font(run, font)
        run.font.size = Pt(actual_size)
        run.font.bold = bold
        run.font.color.rgb = _rgb(color)
    return shape


def _split_label(value: str) -> tuple[str, str]:
    match = re.match(r"^(.{1,18}?[:：])\s*(.*)$", value)
    if not match:
        return "", value
    return match.group(1), match.group(2)


def _math_expressions(values: list[str]) -> list[str]:
    pattern = re.compile(
        r"\d+(?:\s*[×x*]\s*\d+)(?:\s*[=＝]\s*[\d,]+)?"
        r"|\d+\s*[+＋-－]\s*\d+\s*[=＝]\s*[\d,]+"
    )
    result: list[str] = []
    for value in values:
        for match in pattern.findall(value):
            normalized = re.sub(r"\s+", " ", match).replace("=", "＝")
            if normalized not in result:
                result.append(normalized)
    return result[:4]


def _multiplication_parts(expressions: list[str]) -> tuple[int, int] | None:
    for expression in expressions:
        match = re.search(r"(\d+)\s*[×x*]\s*(\d+)", expression)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def _looks_like_math(title: str, bullets: list[str]) -> bool:
    keywords = ("数学", "乘", "算", "对位", "进位", "竖式", "估算", "练习")
    return bool(_math_expressions([title, *bullets])) or any(
        keyword in title for keyword in keywords
    ) and bool(_math_expressions(bullets))


def _section_number(title: str) -> str:
    mapping = {"一": "01", "二": "02", "三": "03", "四": "04", "五": "05"}
    for character, number in mapping.items():
        if title.startswith(f"{character}、") or title.startswith(f"{character}："):
            return number
    return "01"


def _bullet_rows(
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
    style: dict[str, Any],
    field_prefix: str = "bullet",
) -> list[int]:
    if not items:
        return []
    gap = 0.10
    row_height = (height - gap * (len(items) - 1)) / len(items)
    if row_height <= 0:
        raise ValueError("bullet rows do not fit their text box")
    ids: list[int] = []
    container = _rect(
        slide,
        left,
        top,
        width,
        height,
        style["primary_pale"],
        corner=style["corner_radius"],
    )
    rail = _rect(slide, left, top, 0.08, height, style["primary"])
    ids.extend([container.shape_id, rail.shape_id])
    for index, item in enumerate(items):
        y = top + index * (row_height + gap)
        if index:
            rule = _rect(
                slide,
                left + 0.78,
                y - gap / 2,
                width - 0.98,
                0.012,
                style["rule"],
            )
            ids.append(rule.shape_id)
        number = _text_box(
            slide,
            f"{index + 1:02d}",
            left + 0.22,
            y + 0.12,
            0.42,
            min(0.42, row_height - 0.16),
            size=14,
            color=style["primary"],
            font=font,
            bold=True,
            alignment=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        label, body = _split_label(item)
        text_left = left + 0.78
        text_width = max(0.2, width - 0.98)
        text_top = y + 0.13
        text_height = max(0.2, row_height - 0.20)
        field = f"{field_prefix} {index + 1}"
        if label:
            text_shape = _rich_text_box(
                slide,
                [(label, True, style["primary"]), (body, False, color)],
                text_left,
                text_top,
                text_width,
                text_height,
                size=size,
                font=font,
                fit=True,
                min_size=16,
                field=field,
            )
        else:
            text_shape = _text_box(
                slide,
                body,
                text_left,
                text_top,
                text_width,
                text_height,
                size=size,
                color=color,
                font=font,
                fit=True,
                min_size=16,
                field=field,
            )
        ids.extend([number.shape_id, text_shape.shape_id])
    return ids


def _math_panel(
    slide,
    expressions: list[str],
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    style: dict[str, Any],
) -> list[int]:
    panel = _rect(
        slide,
        left,
        top,
        width,
        height,
        style["primary_pale"],
        corner=style["corner_radius"],
    )
    ids = [panel.shape_id]
    label = _text_box(
        slide,
        "算式",
        left + 0.28,
        top + 0.25,
        width - 0.56,
        0.30,
        size=15,
        color=style["primary"],
        font=style["font"],
        bold=True,
    )
    ids.append(label.shape_id)
    if not expressions:
        return ids
    parts = _multiplication_parts(expressions)
    if parts and parts[1] >= 10:
        multiplicand, multiplier = parts
        units = multiplier % 10
        tens = multiplier // 10
        total = multiplicand * multiplier
        lines = [
            f"{multiplicand}",
            f"× {multiplier}",
            "────",
            f"{multiplicand * units}",
            f"{multiplicand * tens * 10}",
            "────",
            f"{total}",
        ]
        stack_text = "\n".join(lines)
        equation = _text_box(
            slide,
            stack_text,
            left + 0.40,
            top + 0.75,
            width - 0.80,
            height - 1.05,
            size=_fit_multiline_size(
                stack_text,
                24,
                width - 0.80,
                height - 1.05,
            ),
            color=style["text"],
            font="Courier New",
            bold=True,
            alignment=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        ids.append(equation.shape_id)
        return ids
    main = _text_box(
        slide,
        expressions[0],
        left + 0.28,
        top + 0.82,
        width - 0.56,
        0.72,
        size=_fit_size(expressions[0], 32, width - 0.56, min_size=22),
        color=style["text"],
        font=style["font"],
        bold=True,
        alignment=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    ids.append(main.shape_id)
    y = top + 1.72
    for expression in expressions[1:]:
        rule = _rect(slide, left + 0.28, y - 0.10, width - 0.56, 0.015, style["rule"])
        ids.append(rule.shape_id)
        line = _text_box(
            slide,
            expression,
            left + 0.28,
            y,
            width - 0.56,
            0.48,
            size=_fit_size(expression, 20, width - 0.56, min_size=16),
            color=style["text"],
            font=style["font"],
            alignment=PP_ALIGN.CENTER,
        )
        ids.append(line.shape_id)
        y += 0.66
    return ids


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
):
    bullet_text = "\n".join(f"• {item}" for item in items)
    _require_text_fit(
        bullet_text,
        size,
        width,
        height,
        "bullet list",
        paragraph_gap=(10 if size >= 20 else 7) / 72.0,
    )
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
        paragraph.line_spacing = 1.12
        run = paragraph.add_run()
        run.text = f"• {item}"
        _set_run_font(run, font)
        run.font.size = Pt(size)
        run.font.color.rgb = _rgb(color)
    return shape


def _chrome(slide, footer: str | None, slide_number: int, style: dict[str, Any]) -> None:
    if footer:
        _text_box(
            slide,
            footer,
            MARGIN,
            PAGE_NUMBER_TOP,
            10.0,
            0.24,
            size=CHROME_SIZE,
            color=style["muted"],
            font=style["font"],
        )
    _text_box(
        slide,
        str(slide_number),
        PAGE_NUMBER_LEFT,
        PAGE_NUMBER_TOP,
        0.57,
        0.24,
        size=CHROME_SIZE,
        color=style["muted"],
        font=style["font"],
        alignment=PP_ALIGN.RIGHT,
    )


def _header(slide, title: str, style: dict[str, Any]) -> tuple[float, int]:
    template = style["template"]
    alignment = _alignment(style["title_alignment"])
    if style["title_alignment"] == "center":
        left = MARGIN
        _rect(slide, MARGIN, TITLE_TOP - 0.08, CONTENT_WIDTH, 0.04, style["primary"])
    elif template == "bold":
        _rect(slide, 0, 0, 0.18, SLIDE_HEIGHT, style["primary"])
        left = 0.75
    else:
        left = MARGIN
        _rect(slide, left, TITLE_TOP + 0.14, 0.07, 0.46, style["primary"])
    title_left = left + (
        0.20
        if template != "bold" and style["title_alignment"] != "center"
        else 0
    )
    title_width = CONTENT_WIDTH - (title_left - MARGIN)
    title_size = _fit_size(
        title,
        style["title_size"],
        title_width,
        min_size=35,
    )
    _require_fit(title, title_size, title_width, "slide title")
    title_shape = _text_box(
        slide,
        title,
        title_left,
        TITLE_TOP,
        title_width,
        1.05,
        size=title_size,
        color=style["text"],
        font=style["heading_font"],
        bold=True,
        alignment=alignment,
    )
    _rect(
        slide,
        title_left,
        1.48,
        title_width,
        0.015,
        style["rule"],
    )
    return CONTENT_TOP, title_shape.shape_id


def _notes(slide, notes: str | None) -> None:
    if notes:
        frame = slide.notes_slide.notes_text_frame
        frame.clear()
        frame.text = notes


def _cover(slide, presentation: dict[str, Any], style: dict[str, Any]) -> list[list[int]]:
    _background(slide, style["background"])
    groups: list[list[int]] = []
    _rect(
        slide,
        0,
        0,
        style["cover_accent_width"],
        SLIDE_HEIGHT,
        style["primary"],
    )
    visual_left = 9.55
    visual = _rect(
        slide,
        visual_left,
        1.15,
        2.75,
        4.85,
        style["primary_pale"],
        corner=style["corner_radius"],
    )
    groups.append([visual.shape_id])
    symbol = "×" if any(word in presentation["title"] for word in ("数学", "乘", "加", "减", "除")) else "01"
    symbol_shape = _text_box(
        slide,
        symbol,
        visual_left + 0.25,
        1.75,
        2.25,
        2.35,
        size=100 if symbol == "×" else 84,
        color=style["primary"],
        font=style["heading_font"],
        bold=True,
        alignment=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    groups.append([symbol_shape.shape_id])
    _rect(slide, visual_left + 0.58, 4.25, 1.60, 0.04, style["primary"])
    _text_box(
        slide,
        "课堂设计",
        visual_left + 0.25,
        4.55,
        2.25,
        0.35,
        size=16,
        color=style["muted"],
        font=style["font"],
        alignment=PP_ALIGN.CENTER,
    )
    title_left = max(0.78, style["cover_accent_width"] + 0.20)
    title_width = visual_left - title_left - 0.52
    title = _text_box(
        slide,
        presentation["title"],
        title_left,
        1.95,
        title_width,
        2.15,
        size=_fit_size(
            presentation["title"],
            style["cover_title_size"],
            title_width,
            min_size=40,
        ),
        color=style["text"],
        font=style["heading_font"],
        bold=True,
        alignment=_alignment(style["title_alignment"]),
        anchor=MSO_ANCHOR.BOTTOM,
    )
    groups.append([title.shape_id])
    if presentation["subtitle"]:
        subtitle = _text_box(
            slide,
            presentation["subtitle"],
            title_left,
            4.72,
            title_width,
            0.85,
            size=_body_size(style, 20, 16),
            color=style["muted"],
            font=style["font"],
        )
        groups.append([subtitle.shape_id])
    _rect(slide, title_left, 5.85, title_width, 0.02, style["rule"])
    return groups


def _section_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    number = _section_number(spec["title"])
    if style["template"] == "bold":
        _rect(slide, 0, 1.75, SLIDE_WIDTH, 3.55, style["primary"])
        number_color = style["primary_text"]
        muted_color = style["primary_text"]
    else:
        _rect(slide, 8.65, 0, 4.68, SLIDE_HEIGHT, style["primary_pale"])
        number_color = style["primary"]
        muted_color = style["muted"]
        _rect(slide, MARGIN, 2.12, 0.08, 0.75, style["primary"])
    title = _text_box(
        slide,
        spec["title"],
        MARGIN + 0.26,
        2.10,
        7.6,
        1.25,
        size=_fit_size(
            spec["title"],
            max(style["title_size"], 40),
            7.6,
            min_size=35,
        ),
        color=style["primary_text"] if style["template"] == "bold" else style["text"],
        font=style["heading_font"],
        bold=True,
        alignment=_alignment(style["title_alignment"]),
        anchor=MSO_ANCHOR.MIDDLE,
    )
    marker = _text_box(
        slide,
        number,
        9.25,
        1.25,
        2.85,
        1.75,
        size=92,
        color=number_color,
        font=style["font"],
        bold=True,
        alignment=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    _text_box(
        slide,
        "SECTION",
        9.25,
        3.35,
        2.85,
        0.35,
        size=14,
        color=muted_color,
        font=style["font"],
        bold=True,
        alignment=PP_ALIGN.CENTER,
    )
    subtitle_ids = []
    if spec["subtitle"]:
        subtitle = _text_box(
            slide,
            spec["subtitle"],
            MARGIN + 0.26,
            3.70,
            7.5,
            1.9,
            size=_body_size(style, 22, 16),
            color=style["primary_text"] if style["template"] == "bold" else style["muted"],
            font=style["font"],
            field="section subtitle",
        )
        subtitle_ids.append(subtitle.shape_id)
    return [title.shape_id, marker.shape_id], subtitle_ids


def _hero_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    band = _rect(slide, 0, 1.62, SLIDE_WIDTH, 4.18, style["primary_pale"])
    _rect(slide, MARGIN, 1.62, 1.05, 0.06, style["primary"])
    _text_box(
        slide,
        "核心结论",
        MARGIN,
        1.88,
        1.5,
        0.32,
        size=15,
        color=style["primary"],
        font=style["font"],
        bold=True,
    )
    title = _text_box(
        slide,
        spec["title"],
        MARGIN + 0.20,
        2.38,
        8.55,
        1.72,
        size=_fit_size(
            spec["title"],
            max(style["title_size"], 44),
            8.55,
            min_size=35,
        ),
        color=style["text"],
        font=style["heading_font"],
        bold=True,
        alignment=_alignment(style["title_alignment"]),
        anchor=MSO_ANCHOR.BOTTOM,
    )
    subtitle_ids = []
    if spec["subtitle"]:
        subtitle = _text_box(
            slide,
            spec["subtitle"],
            MARGIN + 0.20,
            4.42,
            8.35,
            1.35,
            size=_body_size(style, 22, 16),
            color=style["muted"],
            font=style["font"],
            field="hero subtitle",
        )
        subtitle_ids.append(subtitle.shape_id)
    expressions = _math_expressions([spec["title"], spec["subtitle"] or ""])
    multiplication = _multiplication_parts(expressions)
    if multiplication:
        math_ids = _math_panel(
            slide,
            expressions,
            9.42,
            1.92,
            3.08,
            3.46,
            style=style,
        )
        return [title.shape_id], [band.shape_id, *math_ids, *subtitle_ids]
    visual = _rect(slide, 9.72, 2.20, 2.75, 2.75, style["background"])
    visual_rule = _rect(slide, 10.22, 4.46, 1.75, 0.04, style["primary"])
    visual_value = _text_box(
        slide,
        expressions[0] if expressions else "→",
        9.98,
        2.74,
        2.25,
        1.35,
        size=_fit_size(expressions[0], 30, 2.25, min_size=22) if expressions else 72,
        color=style["primary"],
        font=style["font"],
        bold=True,
        alignment=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    return [title.shape_id], [band.shape_id, visual.shape_id, visual_rule.shape_id, visual_value.shape_id, *subtitle_ids]


def _bullet_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    top, title_spid = _header(slide, spec["title"], style)
    total = sum(_display_units(item) for item in spec["bullets"])
    math_like = _looks_like_math(spec["title"], spec["bullets"])
    if math_like:
        left_width = 7.35
        size = _body_size(
            style,
            20 if len(spec["bullets"]) <= 4 and total <= 300 else 18,
            16,
        )
        body_ids = _bullet_rows(
            slide,
            spec["bullets"],
            MARGIN,
            top + 0.05,
            left_width,
            4.75,
            size=size,
            color=style["text"],
            font=style["font"],
            style=style,
            field_prefix="bullets bullet",
        )
        panel_ids = _math_panel(
            slide,
            _math_expressions([spec["title"], *spec["bullets"]]),
            MARGIN + left_width + 0.45,
            top + 0.05,
            CONTENT_WIDTH - left_width - 0.45,
            4.75,
            style=style,
        )
        return [title_spid], [*body_ids, *panel_ids]
    size = _body_size(
        style,
        22
        if len(spec["bullets"]) <= 3 and total <= 260
        else 20 if len(spec["bullets"]) <= 4 else 18,
        16,
    )
    body_ids = _bullet_rows(
        slide,
        spec["bullets"],
        MARGIN,
        top + 0.05,
        CONTENT_WIDTH,
        4.75,
        size=size,
        color=style["text"],
        font=style["font"],
        style=style,
        field_prefix="bullets bullet",
    )
    return [title_spid], body_ids


def _two_column_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    top, title_spid = _header(slide, spec["title"], style)
    shapes: list[int] = []
    gap = 0.46
    column_width = (CONTENT_WIDTH - gap) / 2
    right_left = MARGIN + column_width + gap
    panel_top = top + 0.05
    panel_height = 4.90
    for left, column in ((MARGIN, spec["left"]), (right_left, spec["right"])):
        panel = _rect(
            slide,
            left,
            panel_top,
            column_width,
            panel_height,
            style["panel"] if left == MARGIN else style["alternate"],
            corner=style["corner_radius"],
        )
        shapes.append(panel.shape_id)
        heading = _text_box(
            slide,
            column["heading"],
            left + 0.28,
            panel_top + 0.24,
            column_width - 0.56,
            0.55,
            size=_body_size(style, 22, 18),
            color=style["primary"],
            font=style["font"],
            bold=True,
            fit=True,
            min_size=18,
            single_line=True,
            field=(
                "left column heading"
                if left == MARGIN
                else "right column heading"
            ),
        )
        shapes.append(heading.shape_id)
        _rect(
            slide,
            left + 0.28,
            panel_top + 0.92,
            column_width - 0.56,
            0.025,
            style["primary"],
        )
        body_ids = _bullet_rows(
            slide,
            column["bullets"],
            left + 0.28,
            panel_top + 1.08,
            column_width - 0.56,
            3.70,
            size=_body_size(style, 17, 16),
            color=style["text"],
            font=style["font"],
            style=style,
            field_prefix="two_column bullet",
        )
        shapes.extend(body_ids)
    return [title_spid], shapes


def _icons_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    top, title_spid = _header(slide, spec["title"], style)
    items = spec["items"]
    if len(items) == 4:
        gap = 0.40
        row_gap = 0.15
        width = (CONTENT_WIDTH - gap) / 2
        height = (4.85 - row_gap) / 2
        shapes: list[int] = []
        for index, item in enumerate(items):
            column = index % 2
            row = index // 2
            left = MARGIN + column * (width + gap)
            item_top = top + 0.05 + row * (height + row_gap)
            panel = _rect(
                slide,
                left,
                item_top,
                width,
                height,
                style["panel"],
                corner=style["corner_radius"],
            )
            marker = _text_box(
                slide,
                f"{index + 1:02d}",
                left + 0.25,
                item_top + 0.18,
                0.55,
                0.28,
                size=14,
                color=style["primary"],
                font=style["font"],
                bold=True,
            )
            icon = slide.shapes.add_shape(
                ICONS[item["icon"]],
                Inches(left + 0.30),
                Inches(item_top + 0.78),
                Inches(0.72),
                Inches(0.72),
            )
            icon.fill.solid()
            icon.fill.fore_color.rgb = _rgb(style["primary"])
            icon.line.fill.background()
            icon.shadow.inherit = False
            text_left = left + 1.35
            text_width = width - 1.65
            title = _text_box(
                slide,
                item["title"],
                text_left,
                item_top + 0.18,
                text_width,
                0.98,
                size=_body_size(style, 22, 18),
                color=style["text"],
                font=style["font"],
                bold=True,
                fit=True,
                min_size=18,
                field=f"icon {index + 1} title",
            )
            body = _text_box(
                slide,
                item["body"],
                text_left,
                item_top + 1.25,
                text_width,
                0.95,
                size=_body_size(style, 17, 16),
                color=style["muted"],
                font=style["font"],
                fit=True,
                min_size=16,
                field=f"icon {index + 1} body",
            )
            shapes.extend(
                [
                    panel.shape_id,
                    marker.shape_id,
                    icon.shape_id,
                    title.shape_id,
                    body.shape_id,
                ]
            )
        return [title_spid], shapes
    gap = 0.40
    width = (CONTENT_WIDTH - gap * (len(items) - 1)) / len(items)
    shapes: list[int] = []
    baseline_y = top + 1.48
    _rect(slide, MARGIN, baseline_y, CONTENT_WIDTH, 0.025, style["rule"])
    for index, item in enumerate(items):
        left = MARGIN + index * (width + gap)
        marker = _text_box(
            slide,
            f"{index + 1:02d}",
            left,
            top + 0.16,
            width,
            0.28,
            size=14,
            color=style["primary"],
            font=style["font"],
            bold=True,
        )
        icon = slide.shapes.add_shape(
            ICONS[item["icon"]],
            Inches(left + width / 2 - 0.33),
            Inches(top + 0.66),
            Inches(0.66),
            Inches(0.66),
        )
        icon.fill.solid()
        icon.fill.fore_color.rgb = _rgb(style["primary"])
        icon.line.fill.background()
        icon.shadow.inherit = False
        title = _text_box(
            slide,
            item["title"],
            left,
            top + 1.78,
            width,
            1.35,
            size=_body_size(style, 24, 18),
            color=style["text"],
            font=style["font"],
            bold=True,
            alignment=PP_ALIGN.CENTER,
            fit=True,
            min_size=18,
            field=f"icon {index + 1} title",
        )
        body = _text_box(
            slide,
            item["body"],
            left,
            top + 3.20,
            width,
            1.75,
            size=_body_size(style, 18, 16),
            color=style["muted"],
            font=style["font"],
            alignment=PP_ALIGN.CENTER,
            field=f"icon {index + 1} body",
        )
        shapes.extend([marker.shape_id, icon.shape_id, title.shape_id, body.shape_id])
        if index < len(items) - 1:
            _rect(
                slide,
                left + width + 0.12,
                baseline_y - 0.08,
                gap - 0.24,
                0.18,
                style["primary_soft"],
            )
    return [title_spid], shapes


def _cell_borders(cell, color: str, width: int = 12700) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    fill_element = tc_pr.find(qn("a:solidFill"))
    for side in ("lnL", "lnR", "lnT", "lnB"):
        line = tc_pr.makeelement(
            qn(f"a:{side}"), {"w": str(width), "cap": "flat", "cmpd": "sng", "algn": "ctr"}
        )
        fill = line.makeelement(qn("a:solidFill"), {})
        srgb = fill.makeelement(qn("a:srgbClr"), {"val": color})
        fill.append(srgb)
        line.append(fill)
        if fill_element is not None:
            fill_element.addprevious(line)
        else:
            tc_pr.append(line)


def _table_row_heights(
    values: list[list[str]],
    column_widths: list[float],
    *,
    header_size: float,
    body_size: float,
) -> list[float]:
    heights: list[float] = []
    for row_index, row_values in enumerate(values):
        size = header_size if row_index == 0 else body_size
        required = 0.0
        for column_index, value in enumerate(row_values):
            inner_width = max(column_widths[column_index] - 0.24, 0.2)
            required = max(
                required,
                _estimate_text_height(str(value), size, inner_width) + 0.12,
            )
        heights.append(max(required, TABLE_MIN_ROW_HEIGHT))
    if sum(heights) > TABLE_HEIGHT:
        raise ValueError("table content does not fit the slide")
    return heights


def _table_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    top, title_spid = _header(slide, spec["title"], style)
    headers = spec["table"]["headers"]
    rows = spec["table"]["rows"]
    shape = slide.shapes.add_table(
        len(rows) + 1,
        len(headers),
        Inches(MARGIN),
        Inches(top),
        Inches(CONTENT_WIDTH),
        Inches(4.95),
    )
    table = shape.table
    table.first_row = False
    table.horz_banding = False
    tbl_pr = table._tbl.tblPr
    tbl_style = tbl_pr.find(qn("a:tblStyle"))
    if tbl_style is None:
        tbl_style = tbl_pr.makeelement(qn("a:tblStyle"), {})
        tbl_pr.append(tbl_style)
    tbl_style_id = tbl_style.find(qn("a:tblStyleId"))
    if tbl_style_id is None:
        tbl_style_id = tbl_style.makeelement(qn("a:tblStyleId"), {})
        tbl_style.append(tbl_style_id)
    tbl_style_id.text = _TABLE_GRID_STYLE
    column_weights = []
    for column_index in range(len(headers)):
        units = _display_units(headers[column_index])
        for row in rows:
            if column_index < len(row):
                units = max(units, _display_units(str(row[column_index])))
        # sqrt compresses long columns so short ones are not squeezed
        column_weights.append(math.sqrt(max(units, 2)) + 2)
    weight_total = sum(column_weights)
    column_widths = [CONTENT_WIDTH * weight / weight_total for weight in column_weights]
    for column, width in zip(table.columns, column_widths):
        column.width = Inches(width)
    values = [headers, *rows]
    header_size = _body_size(style, 18, 16)
    body_size = _body_size(style, 16, 16)
    row_heights = _table_row_heights(
        values,
        column_widths,
        header_size=header_size,
        body_size=body_size,
    )
    for row, height in zip(table.rows, row_heights):
        row.height = Inches(height)
    shape.height = Inches(sum(row_heights))
    rule_hex = f"{style['rule'][0]:02X}{style['rule'][1]:02X}{style['rule'][2]:02X}"
    for row_index, row_values in enumerate(values):
        for column_index, value in enumerate(row_values):
            cell = table.cell(row_index, column_index)
            cell.text = value
            cell.margin_left = Inches(0.12)
            cell.margin_right = Inches(0.12)
            cell.margin_top = Inches(0.06)
            cell.margin_bottom = Inches(0.06)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.text_frame.word_wrap = True
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(
                style["primary"]
                if row_index == 0
                else style["alternate"] if row_index % 2 == 0 else style["background"]
            )
            _cell_borders(cell, rule_hex)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.alignment = PP_ALIGN.LEFT
                for run in paragraph.runs:
                    _set_run_font(run, style["font"])
                    run.font.size = Pt(header_size if row_index == 0 else body_size)
                    run.font.bold = row_index == 0
                    run.font.color.rgb = _rgb(
                        style["primary_text"] if row_index == 0 else style["text"]
                    )
    return [title_spid], [shape.shape_id]


def _stats_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    top, title_spid = _header(slide, spec["title"], style)
    items = spec["stats"]
    if len(items) > 2:
        gap = 0.55
        row_gap = 0.22
        width = (CONTENT_WIDTH - gap) / 2
        height = (4.55 - row_gap) / 2
        shapes: list[int] = []
        for index, item in enumerate(items):
            column = index % 2
            row = index // 2
            left = MARGIN + column * (width + gap)
            item_top = top + 0.20 + row * (height + row_gap)
            panel = _rect(
                slide,
                left,
                item_top,
                width,
                height,
                style["primary_pale"],
                corner=style["corner_radius"],
            )
            value = _text_box(
                slide,
                item["value"],
                left + 0.25,
                item_top + 0.25,
                width - 0.50,
                0.95,
                size=_body_size(style, 42, 32),
                color=style["text"],
                font=style["font"],
                bold=True,
                alignment=PP_ALIGN.CENTER,
                fit=True,
                min_size=24,
                single_line=True,
                field=f"stat {index + 1} value",
            )
            label = _text_box(
                slide,
                item["label"],
                left + 0.25,
                item_top + 1.38,
                width - 0.50,
                0.55,
                size=_body_size(style, 18, 16),
                color=style["muted"],
                font=style["font"],
                alignment=PP_ALIGN.CENTER,
                fit=True,
                min_size=16,
                field=f"stat {index + 1} label",
            )
            shapes.extend([panel.shape_id, value.shape_id, label.shape_id])
        return [title_spid], shapes
    band = _rect(
        slide,
        MARGIN,
        top + 0.35,
        CONTENT_WIDTH,
        3.65,
        style["primary_pale"],
        corner=style["corner_radius"],
    )
    gap = 0.55
    width = (CONTENT_WIDTH - gap * (len(items) - 1)) / len(items)
    shapes: list[int] = [band.shape_id]
    for index, item in enumerate(items):
        left = MARGIN + index * (width + gap)
        value = _text_box(
            slide,
            item["value"],
            left,
            top + 1.0,
            width,
            1.3,
            size=_body_size(style, 52, 38),
            color=style["text"],
            font=style["font"],
            bold=True,
            alignment=PP_ALIGN.CENTER,
            fit=True,
            min_size=24,
            single_line=True,
            field=f"stat {index + 1} value",
        )
        label = _text_box(
            slide,
            item["label"],
            left,
            top + 2.58,
            width,
            0.8,
            size=_body_size(style, 20, 16),
            color=style["muted"],
            font=style["font"],
            alignment=PP_ALIGN.CENTER,
            fit=True,
            min_size=16,
            field=f"stat {index + 1} label",
        )
        shapes.extend([value.shape_id, label.shape_id])
        if index < len(items) - 1:
            _rect(slide, left + width + gap / 2, top + 1.12, 0.02, 1.72, style["rule"])
    return [title_spid], shapes


def _steps_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    top, title_spid = _header(slide, spec["title"], style)
    items = spec["steps"]
    gap = 0.46
    width = (CONTENT_WIDTH - gap * (len(items) - 1)) / len(items)
    line_y = top + 1.35
    line = _rect(slide, MARGIN + width / 2, line_y, CONTENT_WIDTH - width, 0.035, style["rule"])
    shapes: list[int] = [line.shape_id]
    for index, item in enumerate(items):
        left = MARGIN + index * (width + gap)
        circle = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(left + width / 2 - 0.37),
            Inches(top + 0.98),
            Inches(0.74),
            Inches(0.74),
        )
        circle.fill.solid()
        circle.fill.fore_color.rgb = _rgb(style["primary"])
        circle.line.fill.background()
        circle.shadow.inherit = False
        number = _text_box(
            slide,
            f"{index + 1:02d}",
            left + width / 2 - 0.37,
            top + 1.04,
            0.74,
            0.58,
            size=18,
            color=style["primary_text"],
            font=style["font"],
            bold=True,
            alignment=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        title = _text_box(
            slide,
            item["title"],
            left,
            top + 1.95,
            width,
            0.95,
            size=_body_size(style, 22, 18),
            color=style["text"],
            font=style["font"],
            bold=True,
            alignment=PP_ALIGN.CENTER,
            fit=True,
            min_size=18,
            field=f"step {index + 1} title",
        )
        body = _text_box(
            slide,
            item["body"],
            left,
            top + 2.95,
            width,
            1.65,
            size=_body_size(style, 17, 16),
            color=style["muted"],
            font=style["font"],
            alignment=PP_ALIGN.CENTER,
            field=f"step {index + 1} body",
        )
        shapes.extend([circle.shape_id, number.shape_id, title.shape_id, body.shape_id])
    return [title_spid], shapes


def _quote_slide(slide, spec: dict[str, Any], style: dict[str, Any]) -> tuple[list[int], list[int]]:
    _background(slide, style["background"])
    top, title_spid = _header(slide, spec["title"], style)
    shapes: list[int] = []
    mark = _text_box(
        slide,
        "“",
        MARGIN + 0.20,
        top + 0.55,
        1.00,
        1.10,
        size=_body_size(style, 48, 40),
        color=style["primary"],
        font=style["font"],
        bold=True,
    )
    shapes.append(mark.shape_id)
    _rect(slide, MARGIN + 0.92, top + 0.78, 0.04, 2.20, style["primary"])
    quote = _text_box(
        slide,
        spec["quote"],
        MARGIN + 1.20,
        top + 0.7,
        CONTENT_WIDTH - 2.0,
        2.35,
        size=_fit_size(
            spec["quote"],
            _body_size(style, 34, 26),
            CONTENT_WIDTH - 2.0,
            min_size=24,
        ),
        color=style["text"],
        font=style["heading_font"],
        alignment=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.MIDDLE,
        field="quote",
    )
    shapes.append(quote.shape_id)
    if spec["source"]:
        source = _text_box(
            slide,
            spec["source"],
            MARGIN + 1.20,
            top + 3.35,
            CONTENT_WIDTH - 2.0,
            0.6,
            size=_body_size(style, 20, 16),
            color=style["muted"],
            font=style["font"],
            alignment=PP_ALIGN.LEFT,
            field="quote source",
        )
        shapes.append(source.shape_id)
    _rect(slide, MARGIN + 1.20, top + 4.10, 1.5, 0.04, style["primary"])
    return [title_spid], shapes


def _add_transition(slide) -> None:
    transition = slide._element.makeelement(qn("p:transition"), {"spd": "med"})
    transition.append(transition.makeelement(qn("p:fade"), {}))
    anchor = slide._element.find(qn("p:clrMapOvr"))
    if anchor is None:
        anchor = slide._element.find(qn("p:cSld"))
    anchor.addnext(transition)


def _add_fade_animations(slide, groups: list[list[int]]) -> None:
    """One click per group; every shape in a group fades in together."""
    if not groups:
        return
    timing = slide._element.makeelement(qn("p:timing"), {})
    tn_lst = timing.makeelement(qn("p:tnLst"), {})
    par_root = tn_lst.makeelement(qn("p:par"), {})
    c_tn_root = par_root.makeelement(
        qn("p:cTn"),
        {"id": "1", "dur": "indefinite", "restart": "never", "nodeType": "tmRoot"},
    )
    child_root = c_tn_root.makeelement(qn("p:childTnLst"), {})
    seq = child_root.makeelement(qn("p:seq"), {"concurrent": "1", "nextAc": "seek"})
    seq_c_tn = seq.makeelement(
        qn("p:cTn"), {"id": "2", "dur": "indefinite", "nodeType": "mainSeq"}
    )
    seq_child = seq_c_tn.makeelement(qn("p:childTnLst"), {})
    next_id = 3

    def cond_list(parent, delay: str):
        conditions = parent.makeelement(qn("p:stCondLst"), {})
        conditions.append(conditions.makeelement(qn("p:cond"), {"delay": delay}))
        parent.append(conditions)

    for group in groups:
        par = seq_child.makeelement(qn("p:par"), {})
        c_tn = par.makeelement(qn("p:cTn"), {"id": str(next_id), "fill": "hold"})
        next_id += 1
        cond_list(c_tn, "indefinite")
        inner = c_tn.makeelement(qn("p:childTnLst"), {})
        par_2 = inner.makeelement(qn("p:par"), {})
        c_tn_2 = par_2.makeelement(qn("p:cTn"), {"id": str(next_id), "fill": "hold"})
        next_id += 1
        cond_list(c_tn_2, "0")
        inner_2 = c_tn_2.makeelement(qn("p:childTnLst"), {})
        par_3 = inner_2.makeelement(qn("p:par"), {})
        c_tn_3 = par_3.makeelement(
            qn("p:cTn"),
            {
                "id": str(next_id),
                "presetID": "10",
                "presetClass": "entr",
                "presetSubtype": "0",
                "fill": "hold",
                "nodeType": "clickEffect",
            },
        )
        next_id += 1
        cond_list(c_tn_3, "0")
        inner_3 = c_tn_3.makeelement(qn("p:childTnLst"), {})
        for spid in group:
            set_el = inner_3.makeelement(qn("p:set"), {})
            behavior = set_el.makeelement(qn("p:cBhvr"), {})
            c_tn_set = behavior.makeelement(
                qn("p:cTn"), {"id": str(next_id), "dur": "1", "fill": "hold"}
            )
            next_id += 1
            cond_list(c_tn_set, "0")
            behavior.append(c_tn_set)
            target = behavior.makeelement(qn("p:tgtEl"), {})
            target.append(target.makeelement(qn("p:spTgt"), {"spid": str(spid)}))
            behavior.append(target)
            attrs = behavior.makeelement(qn("p:attrNameLst"), {})
            attr = attrs.makeelement(qn("p:attrName"), {})
            attr.text = "style.visibility"
            attrs.append(attr)
            behavior.append(attrs)
            set_el.append(behavior)
            to_el = set_el.makeelement(qn("p:to"), {})
            to_el.append(to_el.makeelement(qn("p:strVal"), {"val": "visible"}))
            set_el.append(to_el)
            inner_3.append(set_el)
            effect = inner_3.makeelement(
                qn("p:animEffect"), {"transition": "in", "filter": "fade"}
            )
            behavior_2 = effect.makeelement(qn("p:cBhvr"), {})
            c_tn_effect = behavior_2.makeelement(
                qn("p:cTn"), {"id": str(next_id), "dur": "500"}
            )
            next_id += 1
            behavior_2.append(c_tn_effect)
            target_2 = behavior_2.makeelement(qn("p:tgtEl"), {})
            target_2.append(target_2.makeelement(qn("p:spTgt"), {"spid": str(spid)}))
            behavior_2.append(target_2)
            effect.append(behavior_2)
            inner_3.append(effect)
        c_tn_3.append(inner_3)
        par_3.append(c_tn_3)
        inner_2.append(par_3)
        c_tn_2.append(inner_2)
        par_2.append(c_tn_2)
        inner.append(par_2)
        c_tn.append(inner)
        par.append(c_tn)
        seq_child.append(par)
    seq_c_tn.append(seq_child)
    seq.append(seq_c_tn)
    for event in ("onPrev", "onNext"):
        conditions = seq.makeelement(qn("p:prevCondLst" if event == "onPrev" else "p:nextCondLst"), {})
        cond = conditions.makeelement(qn("p:cond"), {"evt": event, "delay": "0"})
        target = cond.makeelement(qn("p:tgtEl"), {})
        target.append(target.makeelement(qn("p:sldTgt"), {}))
        cond.append(target)
        conditions.append(cond)
        seq.append(conditions)
    child_root.append(seq)
    c_tn_root.append(child_root)
    par_root.append(c_tn_root)
    tn_lst.append(par_root)
    timing.append(tn_lst)
    anchor = slide._element.find(qn("p:transition"))
    if anchor is None:
        anchor = slide._element.find(qn("p:clrMapOvr"))
    if anchor is None:
        anchor = slide._element.find(qn("p:cSld"))
    anchor.addnext(timing)


def _text_shape_fit(shape, slide_number: int) -> None:
    if not hasattr(shape, "text_frame") or not shape.text.strip():
        return
    sizes = [
        run.font.size.pt
        for paragraph in shape.text_frame.paragraphs
        for run in paragraph.runs
        if run.font.size is not None
    ]
    if not sizes:
        return
    size = max(sizes)
    width = shape.width / 914400 - (
        shape.text_frame.margin_left / 914400
        + shape.text_frame.margin_right / 914400
    )
    height = shape.height / 914400 - (
        shape.text_frame.margin_top / 914400
        + shape.text_frame.margin_bottom / 914400
    )
    paragraph_gap = sum(
        (paragraph.space_after.pt if paragraph.space_after is not None else 0) / 72
        for paragraph in shape.text_frame.paragraphs[:-1]
    )
    estimated = _estimate_text_height(
        shape.text, size, width, paragraph_gap=paragraph_gap
    )
    if estimated > height * 1.12:
        raise ValueError(f"generated PPTX slide {slide_number} has clipped text")


def _text_shape_overlap(first, second) -> bool:
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.left + first.width, second.left + second.width)
    bottom = min(first.top + first.height, second.top + second.height)
    return right > left and bottom > top and (right - left) * (bottom - top) > Inches(0.02) ** 2


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
            _text_shape_fit(shape, index + 1)
        text_shapes = [
            shape
            for shape in slide.shapes
            if hasattr(shape, "text_frame") and shape.text.strip()
        ]
        for first_index, first in enumerate(text_shapes):
            for second in text_shapes[first_index + 1 :]:
                if _text_shape_overlap(first, second):
                    raise ValueError(
                        f"generated PPTX slide {index + 1} has overlapping text boxes"
                    )
        element = slide._element
        if element.find(qn("p:transition")) is None:
            raise ValueError(f"generated PPTX slide {index + 1} lost its transition")
        timing = element.find(qn("p:timing"))
        if timing is None:
            raise ValueError(f"generated PPTX slide {index + 1} lost its entrance animation")
        shape_ids = {shape.shape_id for shape in slide.shapes}
        for target in timing.iter(qn("p:spTgt")):
            spid = int(target.get("spid"))
            if spid not in shape_ids:
                raise ValueError(
                    f"generated PPTX slide {index + 1} animates a missing shape"
                )
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
    cover_groups = _cover(cover, presentation, style)
    _add_transition(cover)
    _add_fade_animations(cover, cover_groups)
    for index, spec in enumerate(presentation["slides"], start=2):
        slide = deck.slides.add_slide(blank)
        slide_style = _style_for_slide(
            style,
            spec["style"],
            f"presentation.slides[{index - 2}].style",
        )
        title_ids, content_ids = {
            "section": _section_slide,
            "bullets": _bullet_slide,
            "two_column": _two_column_slide,
            "icons": _icons_slide,
            "table": _table_slide,
            "hero": _hero_slide,
            "stats": _stats_slide,
            "steps": _steps_slide,
            "quote": _quote_slide,
        }[spec["layout"]](slide, spec, slide_style)
        _notes(slide, spec["notes"])
        _chrome(slide, presentation["footer"], index, slide_style)
        _add_transition(slide)
        groups = [group for group in (title_ids, content_ids) if group]
        _add_fade_animations(slide, groups)
    _set_theme_cjk_font(deck)
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
