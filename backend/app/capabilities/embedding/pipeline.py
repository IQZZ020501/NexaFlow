from pathlib import Path

from markitdown import MarkItDown, StreamInfo

from app.shareddomain.knowledge.models import KnowledgeDocument

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
EMBED_BATCH_SIZE = 64
MARKITDOWN = MarkItDown(enable_plugins=False)
SPLIT_SEPARATORS = frozenset({"\n\n", "\n", "。", "."})
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {".docx", ".md", ".markdown", ".pdf", ".txt"}
)


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()).strip()


def clean_text(text: str, rules: list[str], preserve_empty_lines: bool = False) -> str:
    lines = text.splitlines()
    if "trim_lines" in rules:
        lines = [line.strip() for line in lines]
    if "collapse_spaces" in rules:
        lines = [" ".join(line.split()) for line in lines]
    if "remove_empty_lines" in rules and not preserve_empty_lines:
        lines = [line for line in lines if line.strip()]
    return "\n".join(lines).strip()


def has_printable_text(text: str) -> bool:
    return any(character.isprintable() and not character.isspace() for character in text)


class KnowledgePipelineError(Exception):
    pass


def extract_text(document: KnowledgeDocument, path: Path) -> str:
    if not path.exists():
        raise KnowledgePipelineError("Document file is missing.")

    extension = Path(document.filename).suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise KnowledgePipelineError("Document format is not supported.")

    content_type = document.content_type.split(";", 1)[0].strip().lower()
    try:
        result = MARKITDOWN.convert_local(
            path,
            stream_info=StreamInfo(
                mimetype=content_type or None,
                extension=extension,
                filename=document.filename,
                local_path=str(path),
            ),
        )
    except Exception as exc:
        raise KnowledgePipelineError("Document text extraction failed.") from exc

    text = normalize_text(result.text_content)
    if not text or not has_printable_text(text):
        raise KnowledgePipelineError("Document has no extractable text.")
    return text


def split_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    separator: str = "\n\n",
) -> list[str]:
    chunks: list[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            split_at = text.rfind(separator, start, end)
            if split_at > start:
                end = split_at + len(separator)
            else:
                split_at = text.rfind("\n\n", start, end)
                if split_at <= start:
                    split_at = text.rfind(" ", start, end)
                if split_at > start:
                    end = split_at

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break

        next_start = max(end - overlap, 0)
        if next_start <= start:
            next_start = end
        while next_start < text_length and text[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks


def chunk_token_count(content: str) -> int:
    return max(1, len(content.split()))
