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


def artifact_format_from_filename(filename: str) -> str:
    if (
        not isinstance(filename, str)
        or not filename
        or filename != filename.strip()
        or len(filename) > 120
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
