"""Real DOCX structure, physical cell addressing and content-addressed inspection."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import _Cell


def inspector():
    source = Path(__file__).parent / "skills/documents/scripts/inspect_document.py"
    spec = importlib.util.spec_from_file_location("document_inventory", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocumentInspectionTests(unittest.TestCase):
    def test_vertical_merges_and_unspecified_page_geometry(self):
        module = inspector()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "vertical.docx"
            document = Document()
            table = document.add_table(rows=2, cols=2)
            table.cell(0, 0).merge(table.cell(1, 0)).text = "Shared label"
            section = document.sections[0]._sectPr
            for tag in ("w:pgSz", "w:pgMar"):
                section.remove(section.find(qn(tag)))
            document.save(source)
            report = module.inspect_document(source)
            rows = report["tables"][0]["rows"]
            self.assertEqual(rows[0]["cells"][0]["vertical_merge"], "restart")
            self.assertEqual(rows[1]["cells"][0]["vertical_merge"], "continue")
            self.assertIsNone(report["sections"][0]["page_width_cm"])

    def test_physical_cells_and_cached_source_changes(self):
        module = inspector()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, cache = root / "template.docx", root / "inspection.json"
            document = Document()
            document.add_paragraph("Template introduction")
            table = document.add_table(rows=2, cols=4)
            table.cell(0, 0).merge(table.cell(0, 1)).text = "预期成果"
            table.cell(0, 2).text = "A、D"
            table.cell(0, 3).text = "250"
            table.cell(1, 0).text = "申请经费"
            table.cell(1, 0).merge(table.cell(1, 1))
            before = OxmlElement("w:gridBefore")
            before.set(qn("w:val"), "2")
            table.rows[1]._tr.get_or_add_trPr().append(before)
            table.rows[1]._tr.remove(table.rows[1]._tr.tc_lst[0])
            document.save(source)
            original = source.read_bytes()
            first = module.inspect_document(source, cache=cache)
            cells = first["tables"][0]["rows"][0]["cells"]
            self.assertEqual(
                [(c["cell"], c["grid_column"], c["grid_span"]) for c in cells],
                [(0, 0, 2), (1, 2, 1), (2, 3, 1)],
            )
            self.assertEqual(cells[0]["text"], "预期成果")
            self.assertEqual(
                first["tables"][0]["rows"][1]["cells"][0]["grid_column"], 2
            )
            self.assertEqual(source.read_bytes(), original)
            # Physical indices keep the merged label separate from its value.
            target = cells[1]
            _Cell(table.rows[0]._tr.tc_lst[target["cell"]], table).text = "A、C"
            output = root / "filled.docx"
            document.save(output)
            verified = module.inspect_document(output)["tables"][0]["rows"][0]["cells"]
            self.assertEqual([c["text"] for c in verified], ["预期成果", "A、C", "250"])
            with patch.object(
                module,
                "Document",
                side_effect=AssertionError("Cached source must not be reparsed"),
            ):
                self.assertEqual(module.inspect_document(source, cache=cache), first)
            document.paragraphs[0].text = "Revised introduction"
            document.save(source)
            second = module.inspect_document(source, cache=cache)
            self.assertNotEqual(first["source_sha256"], second["source_sha256"])
            self.assertEqual(second["paragraphs"][0]["text"], "Revised introduction")
            cache.write_text("broken cache")
            self.assertEqual(module.inspect_document(source, cache=cache), second)
            with self.assertRaises(ValueError):
                module.inspect_document(source, cache=source)
            renamed = root / "renamed.docx"
            renamed.write_bytes(source.read_bytes())
            self.assertEqual(
                module.inspect_document(renamed, cache=cache)["file"], renamed.name
            )

    def test_selection_and_output_are_bounded(self):
        module = inspector()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "large.docx"
            document = Document()
            document.add_paragraph("A" * 10000)
            for index in range(3):
                table = document.add_table(rows=25, cols=8)
                for row in table.rows:
                    for cell in row.cells:
                        cell.text = f"table {index} " + "表" * 150
            document.save(source)
            report = module.inspect_document(source)
            self.assertLessEqual(
                len(json.dumps(report, ensure_ascii=False).encode()), 24000
            )
            self.assertTrue(report["truncated"])
            self.assertEqual(report["table_count"], 3)
            selected = module.inspect_document(source, tables=[2], row_start=23)
            self.assertEqual(selected["paragraphs"], [])
            self.assertEqual([t["table"] for t in selected["tables"]], [2])
            self.assertEqual(
                [r["row"] for r in selected["tables"][0]["rows"]], [23, 24]
            )
            with self.assertRaises(ValueError):
                module.inspect_document(source, tables=[3])
            completed = subprocess.run(
                [
                    sys.executable,
                    module.__file__,
                    str(source),
                    "--tables",
                    "2",
                    "--row-start",
                    "24",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                json.loads(completed.stdout)["tables"][0]["rows"][0]["row"], 24
            )
