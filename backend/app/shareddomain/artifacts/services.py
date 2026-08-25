import mimetypes
import re
from pathlib import Path


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
    return (
        ARTIFACT_MEDIA_TYPES.get(artifact_format)
        or mimetypes.guess_type(filename, strict=False)[0]
        or "application/octet-stream"
    )
