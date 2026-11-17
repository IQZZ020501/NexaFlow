"""Inspect bounded downloaded deliverables for the live evaluation CLI."""

import hashlib
import json
import uuid
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import ZipFile

from app.domain.agents.evaluation_files import EvaluationFileObservation

MAX_FILE = 5 * 1024 * 1024
MAX_TEXT = 200000


def delivered_files(events):
    """Read identities from successful tool outputs, never answer hyperlinks."""
    files = {}
    remaining = 512

    def visit(value, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 8:
            return
        if isinstance(value, str) and len(value) <= 100000:
            try:
                value = json.loads(value)
            except ValueError:
                return
        if isinstance(value, dict):
            artifact_id = value.get("artifact_id")
            path = value.get("relative_path") or value.get("filename")
            if isinstance(artifact_id, str) and isinstance(path, str):
                try:
                    if str(uuid.UUID(artifact_id)) == artifact_id:
                        files[path] = artifact_id
                except ValueError:
                    pass
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth + 1)

    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict) and event.get("type") == "tool" and event.get("status") == "succeeded":
            visit(event.get("output"))
    return files


def _xml(archive, path):
    data = archive.read(path)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Unsupported XML entity declaration.")
    return ElementTree.fromstring(data)


def inspect_deliverable(expected, artifact_id, content, *, inspection_passed, previous_hash=""):
    """Bounded text and selected cells only; never evaluate workbook formulas."""
    if not 0 < len(content) <= MAX_FILE:
        raise ValueError("Invalid file size.")
    kind = PurePosixPath(expected.path).suffix.lower()
    text = ""
    pages = slides = 0
    cells = {}
    if kind in {".docx", ".xlsx", ".pptx"}:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 4096 or sum(item.file_size for item in members) > 64 * 1024 * 1024:
                raise ValueError("Office file exceeds evaluation limits.")
            names = [item.filename for item in members]
            if len(names) != len(set(names)) or archive.testzip() is not None:
                raise ValueError("Corrupt Office file.")
            if kind == ".docx":
                root = _xml(archive, "word/document.xml")
                namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                text = "\n".join("".join(p.itertext()) for p in root.iter(f"{namespace}p"))[:MAX_TEXT]
            elif kind == ".pptx":
                paths = sorted((name for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml")), key=lambda name: int(PurePosixPath(name).stem[5:]))
                if len(paths) > 500:
                    raise ValueError("Presentation exceeds evaluation page limit.")
                slides = len(paths)
                chunks = []
                length = 0
                for path in paths:
                    root = _xml(archive, path)
                    for paragraph in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}p"):
                        chunk = "".join(paragraph.itertext())
                        if length < MAX_TEXT:
                            chunks.append(chunk[: MAX_TEXT - length])
                        length += len(chunk) + 1
                text = "\n".join(chunks)
            else:
                from openpyxl import load_workbook

                workbook = load_workbook(BytesIO(content), read_only=True, keep_links=False)
                try:
                    for address in expected.cells:
                        sheet, cell = address.rsplit("!", 1)
                        if sheet in workbook.sheetnames:
                            cells[address] = workbook[sheet][cell].value
                    # Text assertions inspect stored values; formula evaluation
                    # requires an external spreadsheet engine and is not implied.
                    chunks = []
                    length = 0
                    total = 0
                    for sheet in workbook:
                        sheet.reset_dimensions()
                        for row in sheet.iter_rows():
                            total += len(row)
                            if total > 1000000:
                                raise ValueError("Workbook exceeds evaluation cell limit.")
                            for cell in row:
                                if cell.value is not None and length < MAX_TEXT:
                                    chunk = str(cell.value)[: MAX_TEXT - length]
                                    chunks.append(chunk)
                                    length += len(chunk) + 1
                    text = "\n".join(chunks)
                finally:
                    workbook.close()
    elif kind == ".pdf":
        from pypdf import PdfReader

        document = PdfReader(BytesIO(content), strict=True)
        if document.is_encrypted or not 0 < len(document.pages) <= 500:
            raise ValueError("PDF exceeds evaluation limits or is encrypted.")
        pages = len(document.pages)
        chunks = []
        length = 0
        for page in document.pages:
            chunk = page.extract_text() or ""
            if length < MAX_TEXT:
                chunks.append(chunk[: MAX_TEXT - length])
            length += len(chunk) + 1
        text = "\n".join(chunks)
    else:
        text = content.decode("utf-8-sig")[:MAX_TEXT]
    digest = hashlib.sha256(content).hexdigest()
    return EvaluationFileObservation(
        path=expected.path, artifact_id=artifact_id, sha256=digest,
        text=text, cells=cells, pages=pages, slides=slides,
        inspection_passed=inspection_passed,
        changed=bool(previous_hash and digest != previous_hash),
    )


def observe_deliverables(client, run, expectations, previous):
    identities = delivered_files(run.get("events"))
    files = []
    for expected in expectations:
        artifact_id = identities.get(expected.path)
        if not artifact_id:
            continue
        try:
            content, checked = client.download_artifact(artifact_id, run_id=run["id"])
            observed = inspect_deliverable(expected, artifact_id, content, inspection_passed=checked, previous_hash=previous.get(expected.path, ""))
        except Exception:
            # Evaluation output is a rule failure, never arbitrary parser/API
            # text that could contain document content or credentials.
            observed = EvaluationFileObservation(path=expected.path, artifact_id=artifact_id, error=True)
        files.append(observed)
    return tuple(files)
