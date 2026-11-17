"""PPTX inventory and preview support without fixed design constraints."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from pptx import Presentation
from pptx.util import Inches


def helper(name):
    source = Path(__file__).parent / "skills/pptx/scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("pptx_" + name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PptxAuthoringTests(unittest.TestCase):
    def test_inventory_records_notes_shapes_and_preservation_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "deck.pptx"
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.shapes.add_textbox(
                Inches(1), Inches(1), Inches(5), Inches(1)
            ).text = "Readable title"
            slide.notes_slide.notes_text_frame.text = "Preserved notes"
            deck.save(path)
            report = helper("inspect_deck").inspect_deck(path)
            self.assertEqual(report["slide_count"], 1)
            self.assertEqual(report["slides"][0]["notes"], "Preserved notes")
            self.assertEqual(report["slides"][0]["shapes"][0]["text"], "Readable title")
            self.assertEqual(report["package"]["zip_integrity"], "passed")
            self.assertEqual(report["warnings"], [])

    def test_geometry_warnings_do_not_restrict_composition(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bleed.pptx"
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.shapes.add_textbox(
                Inches(-0.2), Inches(1), Inches(3), Inches(1)
            ).text = "Intentional bleed"
            deck.save(path)
            report = helper("inspect_deck").inspect_deck(path)
            self.assertIn("outside the canvas", report["warnings"][0])
            self.assertIn("intentional", report["warnings"][0])

    def test_inventory_rejects_unbounded_zip_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oversized.pptx"
            with ZipFile(path, "w") as archive:
                for index in range(4097):
                    archive.writestr(str(index), b"")
            with self.assertRaisesRegex(ValueError, "too large"):
                helper("inspect_deck").inspect_deck(path)

    def test_preview_requires_real_converter(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pptx"
            source.write_bytes(b"placeholder")
            preview = helper("preview")
            with patch.object(preview.shutil, "which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    preview.preview_deck(source, Path(temporary) / "preview")

    def test_preview_conversion_failure_is_not_visual_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pptx"
            source.write_bytes(b"placeholder")
            preview = helper("preview")
            with (
                patch.object(
                    preview.shutil, "which", return_value="/usr/bin/libreoffice"
                ),
                patch.object(preview.subprocess, "run") as convert,
            ):
                convert.return_value.returncode = 1
                convert.return_value.stderr = "Failed to open source"
                with self.assertRaisesRegex(RuntimeError, "conversion failed"):
                    preview.preview_deck(source, Path(temporary) / "preview")
