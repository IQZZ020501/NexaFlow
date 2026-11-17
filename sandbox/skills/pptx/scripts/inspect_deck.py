"""Bounded PPTX inventory for authoring/editing; no layout or rendering policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from pptx import Presentation


def inspect_deck(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 4096
            or sum(item.file_size for item in entries) > 64 * 1024 * 1024
        ):
            raise ValueError("Presentation package is too large to inspect.")
        if archive.testzip() is not None:
            raise ValueError("Presentation ZIP integrity check failed.")
        parts = [item.filename for item in entries]
        preserved = {
            item.filename: hashlib.sha256(archive.read(item)).hexdigest()
            for item in entries
            if item.filename.startswith(
                ("ppt/media/", "ppt/embeddings/", "ppt/comments/")
            )
        }
    deck = Presentation(path)
    slides, warnings = [], []

    def inventory(shape, slide_index):
        # Child coordinates in a group use the group's coordinate system; do
        # not report them as if they were absolute slide coordinates.
        item = {
            "name": shape.name,
            "type": int(shape.shape_type),
            "bounds_inches": [
                round(value / 914400, 3)
                for value in (shape.left, shape.top, shape.width, shape.height)
            ],
        }
        if shape.has_text_frame:
            item["text"] = shape.text[:1200]
            item["text_truncated"] = len(shape.text) > 1200
            item["font_sizes_pt"] = sorted(
                {
                    run.font.size.pt
                    for paragraph in shape.text_frame.paragraphs
                    for run in paragraph.runs
                    if run.font.size
                }
            )
        if shape.has_chart:
            item["chart"] = {
                "type": int(shape.chart.chart_type),
                "series": len(shape.chart.series),
            }
        if shape.has_table:
            item["table"] = {
                "rows": len(shape.table.rows),
                "columns": len(shape.table.columns),
            }
        if hasattr(shape, "shapes"):
            item["children"] = [inventory(child, slide_index) for child in shape.shapes]
        return item

    for index, slide in enumerate(deck.slides, start=1):
        shapes = [inventory(shape, index) for shape in slide.shapes]
        for shape in slide.shapes:
            if (
                shape.left < -9144
                or shape.top < -9144
                or shape.left + shape.width > deck.slide_width + 9144
                or shape.top + shape.height > deck.slide_height + 9144
            ):
                warnings.append(
                    f"Slide {index}: '{shape.name}' extends outside the canvas; inspect whether this is intentional."
                )
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        slides.append(
            {
                "number": index,
                "layout": slide.slide_layout.name,
                "shapes": shapes,
                "notes": notes[:1200],
                "notes_truncated": len(notes) > 1200,
            }
        )
    return {
        "file": path.name,
        "slides": slides,
        "slide_count": len(slides),
        "size_inches": [
            round(value / 914400, 4) for value in (deck.slide_width, deck.slide_height)
        ],
        "core_properties": {
            key: getattr(deck.core_properties, key)
            for key in ("title", "subject", "author")
        },
        "package": {
            "zip_integrity": "passed",
            "entries": parts,
            "preserved_part_hashes": preserved,
            "chart_parts": sum(
                name.startswith("ppt/charts/chart") and name.endswith(".xml")
                for name in parts
            ),
            "relationship_parts": sum(name.endswith(".rels") for name in parts),
        },
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("presentation", type=Path)
    arguments = parser.parse_args()
    print(
        json.dumps(inspect_deck(arguments.presentation), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
