import mimetypes
import re
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
ARTIFACT_FORMAT = re.compile(r"[a-z0-9][a-z0-9+_-]{0,31}\Z")
ARTIFACT_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "html": "text/html; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "py": "text/x-python; charset=utf-8",
    "java": "text/x-java-source; charset=utf-8",
    "zip": "application/zip",
}
RICH_ARTIFACT_MEMBERS = {
    "docx": frozenset({"[Content_Types].xml", "word/document.xml"}),
    "xlsx": frozenset({"[Content_Types].xml", "xl/workbook.xml"}),
    "pptx": frozenset({"[Content_Types].xml", "ppt/presentation.xml"}),
}


ARTIFACT_FILENAME_MAX_CHARS = 120
ARTIFACT_FILENAME_RESERVED_CHARS = '<>:"/\\|?*'
# A caption is only useful as a name while it stays short, so the label stops at
# its first clause before the length cap applies.
ARTIFACT_FILENAME_CLAUSE_SEPARATORS = r"[。！？!?；;，,、\n.]"


def artifact_filename_from_label(
    label: str,
    artifact_format: str,
    *,
    max_chars: int = 40,
    fallback: str = "generated-image",
) -> str:
    """Build a short, safe artifact filename from a human-readable label.

    "instruction: description" labels are named after the description, the result
    keeps its first clause, reserved and control characters collapse to spaces,
    whitespace runs collapse to one space, and the result is truncated so the
    extension always stays inside the filename limits enforced by
    ``artifact_format_from_filename``.
    """
    text = label or ""
    for separator in ("：", ":"):
        _, found, tail = text.partition(separator)
        if found and tail.strip():
            text = tail
            break
    clause = re.split(ARTIFACT_FILENAME_CLAUSE_SEPARATORS, text, maxsplit=1)[0]
    printable = "".join(
        " "
        if character in ARTIFACT_FILENAME_RESERVED_CHARS
        or ord(character) < 32
        or ord(character) == 127
        else character
        for character in clause
    )
    cleaned = " ".join(printable.split()).strip(" .")
    if len(cleaned) > max_chars:
        # Prefer the last whole word over a mid-word cut.
        truncated = cleaned[:max_chars]
        cleaned = (
            truncated.rsplit(" ", 1)[0] if " " in truncated else truncated
        ).strip(" .")
    for candidate in (cleaned, fallback):
        if not candidate:
            continue
        filename = f"{candidate}.{artifact_format}"
        try:
            resolved_format = artifact_format_from_filename(filename)
        except ValueError:
            continue
        if resolved_format == artifact_format:
            return filename
    # An empty fallback lets the caller try another label before defaulting.
    return f"{fallback}.{artifact_format}" if fallback else ""


def artifact_format_from_filename(filename: str) -> str:
    if (
        not isinstance(filename, str)
        or not filename
        or filename != filename.strip()
        or len(filename) > ARTIFACT_FILENAME_MAX_CHARS
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in filename
        )
    ):
        raise ValueError("Artifact filename is invalid.")
    artifact_format = Path(filename).suffix.removeprefix(".").lower() or "file"
    if not ARTIFACT_FORMAT.fullmatch(artifact_format):
        raise ValueError("Artifact filename is invalid.")
    return artifact_format


def validate_generated_artifact(
    artifact_format: str,
    filename: str,
    content: bytes,
) -> str:
    if artifact_format != artifact_format_from_filename(filename):
        raise ValueError("Artifact format does not match its filename.")
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact content must be between 1 byte and 5 MiB.")
    required_members = RICH_ARTIFACT_MEMBERS.get(artifact_format)
    if required_members is not None:
        try:
            with ZipFile(BytesIO(content)) as archive:
                if not required_members.issubset(archive.namelist()):
                    raise ValueError(
                        f"Generated {artifact_format.upper()} is missing "
                        "its document structure."
                    )
                if archive.testzip() is not None:
                    raise ValueError(
                        f"Generated {artifact_format.upper()} is corrupt."
                    )
        except BadZipFile as exc:
            raise ValueError(
                f"Generated {artifact_format.upper()} is not a valid Office document."
            ) from exc
    elif artifact_format == "pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("Generated PDF is not a valid PDF file.")
    return (
        ARTIFACT_MEDIA_TYPES.get(artifact_format)
        or mimetypes.guess_type(filename, strict=False)[0]
        or "application/octet-stream"
    )
