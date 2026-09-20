from __future__ import annotations

import base64
import binascii
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

PAGE_WIDTH = 960
PAGE_HEIGHT = 540
MAX_SLIDES = 30
MAX_ELEMENTS = 80
MAX_MEDIA_FILES = 24
MAX_MEDIA_BYTES = 4 * 1024 * 1024
MAX_SINGLE_MEDIA_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 5 * 1024 * 1024

SCENARIOS = {
    "academic-research",
    "analysis-decision",
    "brand-creative",
    "business-plan",
    "education-training",
    "management-report",
    "tech-engineering",
}
ANIMATION_EFFECTS = {
    "appear",
    "fade-in",
    "fly-in",
    "zoom-in",
    "wipe-in",
    "float-in",
    "peek-in",
    "rise-in",
    "pulse",
    "grow-shrink",
    "spin",
    "teeter",
    "fill-color",
    "transparency",
    "color-pulse",
    "disappear",
    "fade-out",
    "fly-out",
    "zoom-out",
    "wipe-out",
    "float-out",
    "motion-path",
}
ELEMENT_TYPES = {"text", "shape", "line", "image"}
ELEMENT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
MEDIA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.(?:png|jpe?g|gif)$", re.I)
COLOR = re.compile(
    r"^(?:#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?|\$[A-Za-z][A-Za-z0-9_-]{0,31})$"
)


def _preset(
    background: str,
    surface: str,
    primary: str,
    accent: str,
    text: str,
    muted: str,
    *,
    heading: str = "Noto Sans CJK SC",
    body: str = "Noto Sans CJK SC",
) -> dict[str, Any]:
    return {
        "colors": {
            "background": background,
            "surface": surface,
            "primary": primary,
            "accent": accent,
            "text": text,
            "muted": muted,
            "rule": muted,
            "white": "#FFFFFF",
        },
        "heading": heading,
        "body": body,
    }


# Adapted from open-kimi-ppt's named design-system families. The preset supplies
# the stable tokens; the Agent still composes every page from PPTD elements.
DESIGN_SYSTEMS = {
    "apricot-white-brief": _preset(
        "#FFF9F2", "#FFFFFF", "#A44A2A", "#F2A65A", "#2B211D", "#7A675E"
    ),
    "indigo-due-diligence": _preset(
        "#F5F6FA", "#FFFFFF", "#273469", "#6C63FF", "#171B2D", "#687086"
    ),
    "marine-blue-research": _preset(
        "#F4F8FB", "#FFFFFF", "#0A4D68", "#00A8CC", "#102A43", "#627D98"
    ),
    "moss-green-transformation": _preset(
        "#F5F7F1", "#FFFFFF", "#40513B", "#8AA874", "#263126", "#66725F"
    ),
    "pine-green-strategy": _preset(
        "#F2F6F3", "#FFFFFF", "#12372A", "#436850", "#10251C", "#60746A"
    ),
    "red-black-growth": _preset(
        "#F7F7F7", "#FFFFFF", "#111111", "#D62828", "#111111", "#656565"
    ),
    "black-gold-ledger": _preset(
        "#0F0F10",
        "#1B1B1D",
        "#D4AF37",
        "#F4D06F",
        "#F7F3E8",
        "#B8B09D",
        heading="Noto Serif CJK SC",
    ),
    "ebony-ledger": _preset(
        "#181716",
        "#252321",
        "#C6A15B",
        "#8B6F47",
        "#F1ECE2",
        "#B4AA9A",
        heading="Noto Serif CJK SC",
    ),
    "honey-orange-memo": _preset(
        "#FFF8ED", "#FFFFFF", "#7A3E00", "#F59E0B", "#3B2715", "#806B55"
    ),
    "lake-blue-memo": _preset(
        "#F3F8FA", "#FFFFFF", "#155E75", "#38BDF8", "#15313B", "#607985"
    ),
    "prospect-annual": _preset(
        "#F5F7F6",
        "#FFFFFF",
        "#1F4D3E",
        "#C6A15B",
        "#172922",
        "#65736D",
        heading="Noto Serif CJK SC",
    ),
    "rice-paper-annual": _preset(
        "#F5F0E6",
        "#FBF8F1",
        "#674C3C",
        "#B86B4B",
        "#332820",
        "#75685E",
        heading="Noto Serif CJK SC",
    ),
    "blue-flame-brand": _preset(
        "#07111F", "#10243B", "#2F80ED", "#56CCF2", "#F5FAFF", "#9AB3CC"
    ),
    "electric-violet-business": _preset(
        "#120D24", "#21183B", "#8B5CF6", "#D946EF", "#FAF7FF", "#B6A9D0"
    ),
    "moon-white-imagery": _preset(
        "#F7F7F4",
        "#FFFFFF",
        "#31343A",
        "#9CA3AF",
        "#1B1D21",
        "#6D727A",
        heading="Noto Serif CJK SC",
    ),
    "sky-blue-wayfinding": _preset(
        "#F2F8FD", "#FFFFFF", "#176B9C", "#55B6E9", "#17324A", "#667F91"
    ),
    "warm-clay-works": _preset(
        "#F5EEE8",
        "#FFFDFC",
        "#934F3C",
        "#D58A62",
        "#352722",
        "#78675F",
        heading="Noto Serif CJK SC",
    ),
    "warm-jade-annual-report": _preset(
        "#F2F5EF",
        "#FFFFFF",
        "#426B5A",
        "#C6A96B",
        "#22342D",
        "#6D7D75",
        heading="Noto Serif CJK SC",
    ),
    "aqua-charity-report": _preset(
        "#EFFAFA", "#FFFFFF", "#087E8B", "#4ECDC4", "#173B3F", "#638084"
    ),
    "cream-collage": _preset(
        "#F7F0E3",
        "#FFFDF8",
        "#8C5E3C",
        "#D9A441",
        "#3D3026",
        "#7B6B5E",
        heading="Noto Serif CJK SC",
    ),
    "pine-soot-pictorial": _preset(
        "#EEEDE8",
        "#FAF9F5",
        "#1F302A",
        "#667B68",
        "#171B19",
        "#646B67",
        heading="Noto Serif CJK SC",
    ),
    "silk-yellow-magazine": _preset(
        "#FFF6D8",
        "#FFFCF1",
        "#5F4B1B",
        "#E7B928",
        "#2F2817",
        "#786F55",
        heading="Noto Serif CJK SC",
    ),
    "silver-gray-luxury-magazine": _preset(
        "#EDEFF2",
        "#F9FAFB",
        "#30343B",
        "#8D99AE",
        "#17191D",
        "#656B74",
        heading="Noto Serif CJK SC",
    ),
    "travel-green-handbook": _preset(
        "#EFF5EC", "#FFFFFF", "#2D6A4F", "#74C69D", "#1E3328", "#60756A"
    ),
    "blue-line-courseware": _preset(
        "#F8FAFC", "#FFFFFF", "#174EA6", "#3B82F6", "#14213D", "#64748B"
    ),
    "deep-blue-atlas": _preset(
        "#F7FAFC", "#FFFFFF", "#0B2E59", "#00A6C8", "#10233B", "#64748B"
    ),
    "paper-white-courseware": _preset(
        "#FCFBF7",
        "#FFFFFF",
        "#102A43",
        "#E07A5F",
        "#102A43",
        "#66788A",
        heading="Noto Serif CJK SC",
    ),
    "pastel-derivation": _preset(
        "#FAF7FC", "#FFFFFF", "#665191", "#E8A6C9", "#29213A", "#786D86"
    ),
    "teal-green-academic-defense": _preset(
        "#F2F8F6", "#FFFFFF", "#0F766E", "#2DD4BF", "#163B38", "#607C78"
    ),
    "wine-red-data": _preset(
        "#FAF6F7",
        "#FFFFFF",
        "#7F1D3D",
        "#C24164",
        "#351B25",
        "#7B6570",
        heading="Noto Serif CJK SC",
    ),
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _input() -> dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict) or not isinstance(value.get("presentation"), dict):
        _fail("presentation must be an object")
    return value


def _is_modern(presentation: dict[str, Any]) -> bool:
    slides = presentation.get("slides")
    if not isinstance(slides, list) or not slides:
        _fail("presentation.slides must contain 1 to 30 slides")
    modern = [isinstance(slide, dict) and "elements" in slide for slide in slides]
    if any(modern) and not all(modern):
        _fail("presentation.slides cannot mix PPTD elements with legacy layouts")
    return all(modern)


def _legacy(raw: dict[str, Any]) -> None:
    script = Path(__file__).with_name("legacy_render.py")
    result = subprocess.run(
        [sys.executable, "-I", str(script)],
        input=json.dumps(raw, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode:
        message = result.stderr.strip() or "legacy PPTX renderer failed"
        raise RuntimeError(message[-4000:])


def _number(value: object, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        _fail(f"{field} must be between {minimum:g} and {maximum:g}")
    return result


def _validate_bounds(value: object, field: str) -> None:
    if not isinstance(value, list) or len(value) != 4:
        _fail(f"{field} must be [x, y, width, height]")
    x = _number(value[0], f"{field}[0]", 0, PAGE_WIDTH)
    y = _number(value[1], f"{field}[1]", 0, PAGE_HEIGHT)
    width = _number(value[2], f"{field}[2]", 0.1, PAGE_WIDTH)
    height = _number(value[3], f"{field}[3]", 0.1, PAGE_HEIGHT)
    if x + width > PAGE_WIDTH + 0.01 or y + height > PAGE_HEIGHT + 0.01:
        _fail(f"{field} exceeds the 960x540 canvas")


def _validate_color(value: object, field: str) -> None:
    if not isinstance(value, str) or COLOR.fullmatch(value) is None:
        _fail(f"{field} must be #RRGGBB, #RRGGBBAA, or a $theme token")


def _walk_image_sources(value: object) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        if value.get("type") == "image" and isinstance(value.get("src"), str):
            result.append(value["src"])
        if value.get("elementType") == "image" and isinstance(value.get("src"), str):
            result.append(value["src"])
        for child in value.values():
            result.extend(_walk_image_sources(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_walk_image_sources(child))
    return result


def _validate_element(element: object, field: str) -> str:
    if not isinstance(element, dict):
        _fail(f"{field} must be an object")
    element_id = element.get("elementId")
    if not isinstance(element_id, str) or ELEMENT_ID.fullmatch(element_id) is None:
        _fail(f"{field}.elementId is invalid")
    element_type = element.get("elementType")
    if element_type not in ELEMENT_TYPES:
        _fail(f"{field}.elementType is unsupported")
    _validate_bounds(element.get("bounds"), f"{field}.bounds")
    if element_type == "text":
        content = element.get("content")
        if not isinstance(content, dict) or not isinstance(content.get("text"), str):
            _fail(f"{field}.content.text must be a string")
        if not content["text"].strip() or len(content["text"]) > 12_000:
            _fail(f"{field}.content.text is empty or too long")
    elif element_type == "shape":
        if not isinstance(element.get("shapeName"), str):
            _fail(f"{field}.shapeName must be a string")
    elif element_type == "line":
        view_box = element.get("viewBox")
        if not isinstance(view_box, list) or len(view_box) != 2:
            _fail(f"{field}.viewBox must contain width and height")
        if not isinstance(element.get("points"), str):
            _fail(f"{field}.points must be a string")
    else:
        if not isinstance(element.get("src"), str):
            _fail(f"{field}.src must be a media path")
    return element_id


def _validate_animation(animation: object, ids: set[str], field: str) -> None:
    if not isinstance(animation, dict):
        _fail(f"{field} must be an object")
    if animation.get("elementId") not in ids:
        _fail(f"{field}.elementId must target an element on the same slide")
    effect = animation.get("effect")
    if effect not in ANIMATION_EFFECTS:
        _fail(f"{field}.effect is unsupported")
    if effect in {"fill-color", "color-pulse"}:
        _validate_color(animation.get("color"), f"{field}.color")
    if effect == "transparency":
        _number(animation.get("amount"), f"{field}.amount", 0, 1)
    if effect == "motion-path":
        path = animation.get("path")
        if not isinstance(path, str) or not re.match(
            r"^M\s*0(?:\.0+)?[ ,]+0(?:\.0+)?(?:\s|$)", path
        ):
            _fail(f"{field}.path must start at M 0 0")


def _decode_media(presentation: dict[str, Any], root: Path) -> set[str]:
    media = presentation.get("media", [])
    if not isinstance(media, list) or len(media) > MAX_MEDIA_FILES:
        _fail(f"presentation.media must contain at most {MAX_MEDIA_FILES} files")
    media_dir = root / "media"
    media_dir.mkdir()
    names: set[str] = set()
    folded_names: set[str] = set()
    total = 0
    signatures = {
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".gif": (b"GIF87a", b"GIF89a"),
    }
    for index, item in enumerate(media):
        field = f"presentation.media[{index}]"
        if not isinstance(item, dict):
            _fail(f"{field} must be an object")
        name = item.get("filename")
        if not isinstance(name, str) or MEDIA_NAME.fullmatch(name) is None:
            _fail(f"{field}.filename is invalid")
        normalized = name.casefold()
        if normalized in folded_names:
            _fail(f"{field}.filename is duplicated")
        encoded = item.get("content_base64")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError, binascii.Error):
            _fail(f"{field}.content_base64 is invalid")
        suffix = Path(name).suffix.lower()
        if not 0 < len(content) <= MAX_SINGLE_MEDIA_BYTES:
            _fail(f"{field} exceeds the per-file media limit")
        if not any(content.startswith(signature) for signature in signatures[suffix]):
            _fail(f"{field} does not match its image extension")
        total += len(content)
        if total > MAX_MEDIA_BYTES:
            _fail("presentation.media exceeds the total media limit")
        (media_dir / name).write_bytes(content)
        names.add(name)
        folded_names.add(normalized)
    return names


def _theme(presentation: dict[str, Any]) -> dict[str, Any]:
    design = presentation.get("design_system", "blue-line-courseware")
    if design not in DESIGN_SYSTEMS:
        _fail("presentation.design_system is unsupported")
    preset = DESIGN_SYSTEMS[design]
    colors = dict(preset["colors"])
    heading = preset["heading"]
    body = preset["body"]
    raw_theme = presentation.get("theme")
    if raw_theme is not None:
        if not isinstance(raw_theme, dict):
            _fail("presentation.theme must be an object")
        mapping = {
            "background_color": "background",
            "panel_color": "surface",
            "accent_color": "accent",
            "text_color": "text",
            "muted_text_color": "muted",
            "rule_color": "rule",
        }
        for source, target in mapping.items():
            if raw_theme.get(source) is not None:
                _validate_color(raw_theme[source], f"presentation.theme.{source}")
                colors[target] = raw_theme[source]
        if isinstance(raw_theme.get("font_family"), str):
            body = raw_theme["font_family"]
        if isinstance(raw_theme.get("heading_font_family"), str):
            heading = raw_theme["heading_font_family"]
    brand = presentation.get("brand")
    if isinstance(brand, dict):
        for source, target in {
            "primary_color": "primary",
            "background_color": "background",
            "text_color": "text",
        }.items():
            if brand.get(source) is not None:
                _validate_color(brand[source], f"presentation.brand.{source}")
                colors[target] = brand[source]
        if isinstance(brand.get("font_family"), str):
            heading = body = brand["font_family"]
    return {
        "colors": colors,
        "textStyles": {
            "title": {
                "fontFamily": heading,
                "fontSize": 38,
                "bold": True,
                "color": "$text",
                "lineHeight": 1.05,
            },
            "body": {
                "fontFamily": body,
                "fontSize": 18,
                "color": "$text",
                "lineHeight": 1.35,
            },
            "label": {
                "fontFamily": body,
                "fontSize": 12,
                "bold": True,
                "color": "$primary",
                "letterSpacing": 1.5,
            },
        },
    }


def _write_project(
    presentation: dict[str, Any], root: Path
) -> tuple[Path, list[bool], list[str | None]]:
    title = presentation.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        _fail("presentation.title is invalid")
    scenario = presentation.get("scenario", "management-report")
    if scenario not in SCENARIOS:
        _fail("presentation.scenario is unsupported")
    slides = presentation.get("slides")
    if not isinstance(slides, list) or not 1 <= len(slides) <= MAX_SLIDES:
        _fail("presentation.slides must contain 1 to 30 slides")
    media_names = _decode_media(presentation, root)
    pages_dir = root / "pages"
    pages_dir.mkdir()
    page_paths: list[str] = []
    animation_flags: list[bool] = []
    notes_values: list[str | None] = []
    for slide_index, slide in enumerate(slides):
        field = f"presentation.slides[{slide_index}]"
        if not isinstance(slide, dict):
            _fail(f"{field} must be an object")
        elements = slide.get("elements")
        if not isinstance(elements, list) or not 1 <= len(elements) <= MAX_ELEMENTS:
            _fail(f"{field}.elements must contain 1 to {MAX_ELEMENTS} items")
        ids: set[str] = set()
        for element_index, element in enumerate(elements):
            element_id = _validate_element(
                element, f"{field}.elements[{element_index}]"
            )
            if element_id in ids:
                _fail(f"{field}.elements contains duplicate elementId {element_id}")
            ids.add(element_id)
        animations = slide.get("animations", [])
        if not isinstance(animations, list) or len(animations) > 24:
            _fail(f"{field}.animations must contain at most 24 items")
        for animation_index, animation in enumerate(animations):
            _validate_animation(
                animation, ids, f"{field}.animations[{animation_index}]"
            )
        for src in _walk_image_sources(slide):
            path = PurePosixPath(src)
            if (
                path.is_absolute()
                or len(path.parts) != 2
                or path.parts[0] != "media"
                or path.parts[1] not in media_names
            ):
                _fail(f"{field} references undeclared or non-local media: {src}")
        page = {
            "pageType": slide.get("page_type", "content"),
            "background": slide.get(
                "background", {"type": "solid", "color": "$background"}
            ),
            "elements": elements,
        }
        if animations:
            page["animations"] = animations
        notes = slide.get("notes")
        if notes is not None:
            if not isinstance(notes, str) or len(notes) > 4_000:
                _fail(f"{field}.notes is invalid")
            page["notes"] = notes
        page_name = f"pages/{slide_index + 1:02d}.page"
        (root / page_name).write_text(
            json.dumps(page, ensure_ascii=False, separators=(",", ":"))
        )
        page_paths.append(page_name)
        animation_flags.append(bool(animations))
        notes_values.append(notes)
    manifest = {
        "version": "v2",
        "title": title.strip(),
        "size": [PAGE_WIDTH, PAGE_HEIGHT],
        "theme": _theme(presentation),
        "pages": page_paths,
    }
    path = root / "presentation.pptd"
    path.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    return path, animation_flags, notes_values


def _verify(
    path: Path,
    expected_slides: int,
    animation_flags: list[bool],
    expected_notes: list[str | None],
    transition: str,
) -> None:
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_OUTPUT_BYTES:
        _fail("generated PPTX is missing or exceeds 5 MiB")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        slides = sorted(
            (name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),
        )
        if len(slides) != expected_slides:
            _fail("generated PPTX slide count does not match the request")
        namespace = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
        for index, name in enumerate(slides):
            root = ElementTree.fromstring(archive.read(name))
            if transition != "none" and root.find("p:transition", namespace) is None:
                _fail(f"generated PPTX slide {index + 1} lost its transition")
            if animation_flags[index] and root.find("p:timing", namespace) is None:
                _fail(f"generated PPTX slide {index + 1} lost its animations")
    from pptx import Presentation

    deck = Presentation(path)
    if len(deck.slides) != expected_slides:
        _fail("generated PPTX could not be reopened with the expected slide count")
    for index, notes in enumerate(expected_notes):
        if notes and notes not in deck.slides[index].notes_slide.notes_text_frame.text:
            _fail(f"generated PPTX slide {index + 1} lost its speaker notes")


def _modern(presentation: dict[str, Any], output_path: Path) -> None:
    transition = presentation.get("page_transition", "fade")
    if transition not in {"fade", "none"}:
        _fail("presentation.page_transition is unsupported")
    vendor = Path(__file__).parent / "vendor" / "open-kimi-ppt"
    exporter = vendor / "export-pptd.mjs"
    wasm = vendor / "pptd_wasm_bg.wasm"
    node = os.environ.get("NEXAFLOW_NODE_BINARY") or shutil.which("node")
    if node is None or not exporter.is_file() or not wasm.is_file():
        raise RuntimeError("PPTD renderer runtime is unavailable")
    with tempfile.TemporaryDirectory(prefix="nexaflow-pptd-") as temporary:
        manifest, animation_flags, expected_notes = _write_project(
            presentation, Path(temporary)
        )
        result = subprocess.run(
            [
                node,
                str(exporter),
                str(manifest),
                "-o",
                str(output_path),
                "--no-sign",
                "--transition",
                transition,
                "--wasm",
                str(wasm),
            ],
            cwd=temporary,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
            env={"PATH": os.environ.get("PATH", "")},
        )
        if result.returncode:
            message = (
                result.stderr.strip() or result.stdout.strip() or "PPTD export failed"
            )
            raise RuntimeError(message[-4000:])
    _verify(
        output_path,
        len(presentation["slides"]),
        animation_flags,
        expected_notes,
        transition,
    )
    print(
        json.dumps(
            {
                "renderer": "open-kimi-pptd",
                "slides": len(presentation["slides"]),
                "scenario": presentation.get("scenario", "management-report"),
                "design_system": presentation.get(
                    "design_system", "blue-line-courseware"
                ),
            },
            separators=(",", ":"),
        )
    )


def main() -> None:
    output_path = Path(os.environ["NEXAFLOW_OUTPUT_PATH"])
    if output_path.suffix.lower() != ".pptx":
        _fail("pptx Skill requires a .pptx filename")
    raw = _input()
    presentation = raw["presentation"]
    if _is_modern(presentation):
        _modern(presentation, output_path)
    else:
        _legacy(raw)


if __name__ == "__main__":
    main()
