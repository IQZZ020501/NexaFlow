from io import BytesIO
from pathlib import Path
import zipfile


MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
ARTIFACT_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html; charset=utf-8",
}


def validate_generated_artifact(
    artifact_format: str,
    filename: str,
    content: bytes,
) -> str:
    if artifact_format not in ARTIFACT_MEDIA_TYPES:
        raise ValueError("Artifact format must be docx or html.")
    if (
        not isinstance(filename, str)
        or not filename
        or len(filename) > 120
        or Path(filename).name != filename
        or "\x00" in filename
        or not filename.lower().endswith(f".{artifact_format}")
    ):
        raise ValueError("Artifact filename is invalid.")
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact content must be between 1 byte and 5 MiB.")
    if artifact_format == "html":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("HTML artifacts must be UTF-8.") from exc
    else:
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise ValueError("DOCX artifact is invalid.") from exc
        if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
            raise ValueError("DOCX artifact is invalid.")
    return ARTIFACT_MEDIA_TYPES[artifact_format]
