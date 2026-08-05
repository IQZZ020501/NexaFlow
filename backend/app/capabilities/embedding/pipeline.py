import re
from dataclasses import dataclass
from pathlib import Path

from markitdown import MarkItDown, StreamInfo

from app.shareddomain.knowledge.models import KnowledgeDocument

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
PARENT_CHUNK_SIZE = CHUNK_SIZE * 4
EMBED_BATCH_SIZE = 64
MARKITDOWN = MarkItDown(enable_plugins=False)
SPLIT_SEPARATORS = frozenset({"\n\n", "\n", "。", "."})
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {".docx", ".md", ".markdown", ".pdf", ".txt"}
)
MARKDOWN_HEADING_PATTERN = re.compile(
    r"^\s{0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$"
)


@dataclass(frozen=True)
class TextSpan:
    content: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class ParentChunkDraft:
    title: str
    content: str


@dataclass(frozen=True)
class ChildChunkDraft:
    content: str
    parent_index: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True)
class DocumentChunkDrafts:
    parents: list[ParentChunkDraft]
    children: list[ChildChunkDraft]


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
    return [
        span.content
        for span in split_text_spans(text, chunk_size, overlap, separator)
    ]


def split_text_spans(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    separator: str = "\n\n",
) -> list[TextSpan]:
    chunks: list[TextSpan] = []
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

        raw_chunk = text[start:end]
        content_start = start + len(raw_chunk) - len(raw_chunk.lstrip())
        content_end = end - (len(raw_chunk) - len(raw_chunk.rstrip()))
        if content_start < content_end:
            chunks.append(
                TextSpan(
                    content=text[content_start:content_end],
                    start_offset=content_start,
                    end_offset=content_end,
                )
            )
        if end >= text_length:
            break

        next_start = max(end - overlap, 0)
        if next_start <= start:
            next_start = end
        while next_start < text_length and text[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks


def split_parent_chunks(
    text: str,
    max_size: int = PARENT_CHUNK_SIZE,
) -> list[ParentChunkDraft]:
    sections: list[tuple[str, str]] = []
    section_start = 0
    section_title = ""
    offset = 0
    fence_marker: str | None = None

    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if fence_marker is not None:
            if marker == fence_marker:
                fence_marker = None
            offset += len(line)
            continue
        if marker is not None:
            fence_marker = marker
            offset += len(line)
            continue

        heading = MARKDOWN_HEADING_PATTERN.match(line.rstrip("\r\n"))
        if heading is not None:
            content = text[section_start:offset].strip()
            if content:
                sections.append((section_title, content))
            section_start = offset
            section_title = heading.group(1).strip()
        offset += len(line)

    content = text[section_start:].strip()
    if content:
        sections.append((section_title, content))

    parents: list[ParentChunkDraft] = []
    for title, section in sections:
        parents.extend(
            ParentChunkDraft(title=title, content=span.content)
            for span in split_text_spans(section, max_size, 0, "\n\n")
        )
    return parents


def build_hierarchical_chunks(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    separator: str = "\n\n",
) -> DocumentChunkDrafts:
    parents = split_parent_chunks(text)
    children: list[ChildChunkDraft] = []
    for parent_index, parent in enumerate(parents):
        children.extend(
            ChildChunkDraft(
                content=span.content,
                parent_index=parent_index,
                start_offset=span.start_offset,
                end_offset=span.end_offset,
            )
            for span in split_text_spans(
                parent.content,
                chunk_size,
                overlap,
                separator,
            )
        )
    return DocumentChunkDrafts(parents=parents, children=children)


def build_flat_chunks(contents: list[str]) -> DocumentChunkDrafts:
    return DocumentChunkDrafts(
        parents=[],
        children=[ChildChunkDraft(content=content) for content in contents],
    )


def chunk_token_count(content: str) -> int:
    return max(1, len(content.split()))
