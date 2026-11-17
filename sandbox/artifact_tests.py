"""File delivery checks exercise real parsers and the bounded child protocol."""

import hashlib
import unittest
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from .artifact_check import inspect_artifact


class ArtifactQualityTests(unittest.TestCase):
    def assert_passed(self, filename, content, check):
        result = inspect_artifact(filename, content)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
        self.assertIn(check, result["checks"])
        return result

    def test_real_office_and_pdf_parsers(self):
        import pymupdf
        from docx import Document
        from openpyxl import Workbook
        from pptx import Presentation

        document = Document()
        document.add_paragraph("中文报告，交付数量 12。")
        data = BytesIO()
        document.save(data)
        self.assert_passed("report.docx", data.getvalue(), "document_parse")
        workbook = Workbook()
        workbook.active.append(["数量", 12])
        workbook.active.append(["总计", "=B1*2"])
        data = BytesIO()
        workbook.save(data)
        result = self.assert_passed("data.xlsx", data.getvalue(), "workbook_parse")
        self.assertEqual(result["details"]["sheets"][0]["rows"], 2)
        self.assertEqual(result["details"]["formulas"], 1)
        deck = Presentation()
        deck.slides.add_slide(deck.slide_layouts[6])
        data = BytesIO()
        deck.save(data)
        self.assert_passed("deck.pptx", data.getvalue(), "presentation_parse")
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40, 40), "Delivery 12")
            self.assert_passed("report.pdf", pdf.tobytes(), "pdf_parse")

    def test_xlsx_distinguishes_stored_values_and_uncached_formulas(self):
        from openpyxl import Workbook, load_workbook

        for cached_value in (None, 0, 24):
            with self.subTest(cached_value=cached_value):
                workbook = Workbook()
                workbook.active.append(["Quantity", "Amount"])
                formula = "=A2-A2" if cached_value == 0 else "=A2*2"
                workbook.active.append([12, formula])
                data = BytesIO()
                workbook.save(data)
                if cached_value is not None:
                    rewritten = BytesIO()
                    with ZipFile(data) as source, ZipFile(rewritten, "w") as target:
                        for item in source.infolist():
                            content = source.read(item)
                            if item.filename == "xl/worksheets/sheet1.xml":
                                xml = ElementTree.fromstring(content)
                                namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                                xml.find(f".//{namespace}c[@r='B2']/{namespace}v").text = str(cached_value)
                                content = ElementTree.tostring(xml)
                            target.writestr(item, content)
                    data = rewritten
                result = self.assert_passed("formula.xlsx", data.getvalue(), "workbook_parse")
                self.assertEqual(result["details"]["formulas"], 1)
                self.assertEqual(result["details"]["uncached_formulas"], int(cached_value is None))
                self.assertEqual(
                    any("no cached result" in warning for warning in result["warnings"]),
                    cached_value is None,
                )
                saved = load_workbook(BytesIO(data.getvalue()), read_only=True)
                self.assertEqual(saved.active["B2"].value, formula)
                saved.close()
        workbook = Workbook()
        workbook.active.append([12, 24])
        data = BytesIO()
        workbook.save(data)
        result = self.assert_passed("values.xlsx", data.getvalue(), "workbook_parse")
        self.assertEqual(result["details"]["formulas"], 0)
        self.assertEqual(result["details"]["uncached_formulas"], 0)
        self.assertFalse(result["warnings"])

    def test_valid_headers_are_insufficient(self):
        for kind, member in (("docx", "word/document.xml"), ("xlsx", "xl/workbook.xml"), ("pptx", "ppt/presentation.xml")):
            data = BytesIO()
            with ZipFile(data, "w") as archive:
                archive.writestr("[Content_Types].xml", "<broken/>")
                archive.writestr(member, "<broken/>")
            self.assertEqual(inspect_artifact("broken." + kind, data.getvalue())["status"], "failed")
        self.assertEqual(inspect_artifact("broken.pdf", b"%PDF-1.7\ninvalid")["status"], "failed")

    def test_zip_bomb_is_rejected_before_document_parse(self):
        data = BytesIO()
        with ZipFile(data, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", b"x" * (33 * 1024 * 1024))
        report = inspect_artifact("oversized.docx", data.getvalue())
        self.assertEqual(report["status"], "failed")
        self.assertIn("inspection limits", report["error"])

    def test_text_structure_and_format_specific_failures(self):
        self.assert_passed("data.csv", "名称,数量\n产品,12\n".encode(), "text_parse")
        self.assert_passed("data.json", b'{"count":12}', "text_parse")
        for filename, content in (("data.json", b'{"count":NaN}'), ("data.csv", b'"unfinished'), ("data.xml", b'<!DOCTYPE x [<!ENTITY e "a">]><x>&e;</x>'), ("data.txt", b"\xff")):
            self.assertEqual(inspect_artifact(filename, content)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
