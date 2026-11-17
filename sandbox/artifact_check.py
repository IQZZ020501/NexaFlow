"""Bounded file inspection in a separate, unprivileged guest process.

The root shell supervisor passes bytes, never user-controlled import paths or
commands. Document parsers run only in the child, with the guest's denied egress.
"""

import base64
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

MAX_FILE = 5 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_REPORT = 32 * 1024
VERSION = "nexaflow-file-check/1"
OFFICE_MEMBERS = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}


def _office_container(content, kind):
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if (
                len(members) > 4096
                or sum(item.file_size for item in members) > MAX_EXPANDED
                or any(item.file_size > MAX_EXPANDED // 2 for item in members)
                or any(item.flag_bits & 1 for item in members)
            ):
                raise ValueError("Office container exceeds inspection limits or is encrypted.")
            names = [item.filename for item in members]
            if len(names) != len(set(names)) or not {
                "[Content_Types].xml", OFFICE_MEMBERS[kind]
            }.issubset(names):
                raise ValueError("Office document structure is invalid.")
            if archive.testzip() is not None:
                raise ValueError("Office document has corrupt ZIP entries.")
    except BadZipFile as exc:
        raise ValueError("File is not a readable Office document.") from exc


def _inspect_content(filename, content):
    kind = Path(filename).suffix.removeprefix(".").lower() or "file"
    if not 0 < len(content) <= MAX_FILE:
        raise ValueError("File must be between 1 byte and 5 MiB.")
    checks = ["size", "sha256"]
    details = {}
    warnings = []
    if kind in OFFICE_MEMBERS:
        _office_container(content, kind)
        checks.append("office_container")
    if kind == "docx":
        from docx import Document

        document = Document(BytesIO(content))
        details = {
            "paragraphs": len(document.paragraphs),
            "tables": len(document.tables),
            "sections": len(document.sections),
        }
        if not any(p.text.strip() for p in document.paragraphs) and not document.tables:
            warnings.append("Document has no paragraph text or tables.")
        checks.append("document_parse")
    elif kind == "xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(BytesIO(content), read_only=True, keep_links=False)
        cached_workbook = None
        try:
            cached_workbook = load_workbook(
                BytesIO(content), read_only=True, keep_links=False, data_only=True
            )
            sheets = []
            cells = 0
            formulas = 0
            uncached_formulas = 0
            for sheet in workbook:
                # Do not trust worksheet dimension declarations; iterate actual XML.
                sheet.reset_dimensions()
                cached_sheet = cached_workbook[sheet.title]
                cached_sheet.reset_dimensions()
                cached_rows = cached_sheet.iter_rows()
                rows = columns = 0
                for row in sheet.iter_rows():
                    rows += 1
                    if rows > 100000:
                        raise ValueError("Worksheet exceeds the 100000 row inspection limit.")
                    columns = max(columns, len(row))
                    if columns > 16384:
                        raise ValueError("Worksheet exceeds the column inspection limit.")
                    cells += len(row)
                    if cells > 1000000:
                        raise ValueError("Workbook exceeds the 1000000 cell inspection limit.")
                    cached_row = next(cached_rows, ())
                    for column, cell in enumerate(row):
                        if cell.data_type == "f":
                            formulas += 1
                            if column >= len(cached_row) or cached_row[column].value is None:
                                uncached_formulas += 1
                sheets.append({"name": sheet.title, "rows": rows, "columns": columns})
                if len(sheets) > 128:
                    raise ValueError("Workbook exceeds the 128 sheet inspection limit.")
            details = {
                "sheets": sheets, "formulas": formulas,
                "uncached_formulas": uncached_formulas,
            }
            if formulas:
                warnings.append("Formulas were parsed; this check does not calculate them.")
            if uncached_formulas:
                warnings.append(
                    f"{uncached_formulas} formula cell(s) have no cached result. "
                    "Readers that do not recalculate will see empty values. "
                    "If stored numeric values are required, calculate and write numbers, "
                    "then reopen with data_only=True to verify them before delivery."
                )
        finally:
            if cached_workbook is not None:
                cached_workbook.close()
            workbook.close()
        checks.append("workbook_parse")
    elif kind == "pptx":
        from pptx import Presentation

        deck = Presentation(BytesIO(content))
        if not 0 < len(deck.slides) <= 500:
            raise ValueError("Presentation must have between 1 and 500 slides.")
        outside = 0
        for slide in deck.slides:
            for shape in slide.shapes:
                outside += int(
                    shape.left < -9144 or shape.top < -9144
                    or shape.left + shape.width > deck.slide_width + 9144
                    or shape.top + shape.height > deck.slide_height + 9144
                )
                if shape.has_text_frame:
                    # Force lazy text XML parsing too.
                    _ = shape.text_frame.text
        details = {"slides": len(deck.slides), "shapes_outside_slide": outside}
        if outside:
            warnings.append("Some shapes extend outside the slide; review their rendered layout.")
        checks.append("presentation_parse")
    elif kind == "pdf":
        import pymupdf

        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.needs_pass or not 0 < document.page_count <= 500:
                raise ValueError("PDF must be unencrypted and have between 1 and 500 pages.")
            if document.is_repaired:
                raise ValueError("PDF required structural repair; regenerate it before delivery.")
            for page in document:
                # Parse page content without an unbounded raster allocation.
                _ = page.get_text("text")
            details = {"pages": document.page_count}
        checks.append("pdf_parse")
    elif kind in {"txt", "md", "markdown", "html", "csv", "json", "xml"}:
        text = content.decode("utf-8-sig")
        if kind == "json":
            def invalid_constant(_value):
                raise ValueError("JSON contains a non-finite number.")

            json.loads(text, parse_constant=invalid_constant)
        elif kind == "csv":
            import csv
            from io import StringIO

            csv.field_size_limit(1024 * 1024)
            rows = sum(1 for _ in csv.reader(StringIO(text), strict=True))
            details["rows"] = rows
        elif kind == "xml":
            from xml.etree import ElementTree

            if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
                raise ValueError("XML declarations with entities are not supported.")
            ElementTree.fromstring(text)
        details["characters"] = len(text)
        checks.append("text_parse")
    return {
        "schema_version": 1, "validator": VERSION, "status": "passed",
        "format": kind, "sha256": hashlib.sha256(content).hexdigest(),
        "checks": checks, "details": details, "warnings": warnings,
    }


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (8, 9))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_REPORT,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (32,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(65532)
        os.setuid(65532)


def inspect_artifact(filename, content, *, python_binary=sys.executable, timeout_seconds=8):
    """Inspect immutable bytes, failing closed on parser/timeout/protocol errors."""
    payload = json.dumps({
        "filename": filename, "content": base64.b64encode(content).decode("ascii")
    }).encode()
    failure = {
        "schema_version": 1, "validator": VERSION, "status": "failed",
        "format": Path(filename).suffix.removeprefix(".").lower() or "file",
        "sha256": hashlib.sha256(content).hexdigest(),
        "error": "File inspection exceeded its limits or could not complete.",
    }
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            [python_binary, "-I", str(Path(__file__).resolve()), "--child"],
            stdin=subprocess.PIPE, stdout=output, stderr=errors, cwd="/tmp",
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                 "PYTHONDONTWRITEBYTECODE": "1"},
            start_new_session=True, preexec_fn=_limits,
        )
        try:
            process.communicate(payload, timeout=max(0.01, min(8, timeout_seconds)))
        except (TimeoutError, subprocess.TimeoutExpired, BrokenPipeError):
            return failure
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        output.seek(0)
        if process.returncode != 0:
            return failure
        try:
            value = json.loads(output.read(MAX_REPORT + 1))
            if not isinstance(value, dict) or value.get("status") not in {"passed", "failed"}:
                return failure
            if value.get("sha256") != failure["sha256"]:
                return failure
            return value
        except (ValueError, UnicodeDecodeError):
            return failure


if __name__ == "__main__":
    request = json.loads(sys.stdin.buffer.read(8 * 1024 * 1024))
    blob = base64.b64decode(request["content"], validate=True)
    try:
        report = _inspect_content(request["filename"], blob)
    except Exception as exc:
        report = {
            "schema_version": 1, "validator": VERSION, "status": "failed",
            "format": Path(request["filename"]).suffix.removeprefix(".").lower() or "file",
            "sha256": hashlib.sha256(blob).hexdigest(),
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }
    print(json.dumps(report, ensure_ascii=False))
