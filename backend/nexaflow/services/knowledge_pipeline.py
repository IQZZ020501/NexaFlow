from dataclasses import dataclass
from pathlib import Path
from typing import Any

from markitdown import MarkItDown, StreamInfo

from nexaflow.core.config import Settings
from nexaflow.models.knowledge import KnowledgeBase, KnowledgeDocument

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


@dataclass(frozen=True)
class VectorChunk:
    id: str
    document_id: str
    document_filename: str
    chunk_index: int
    content: str


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    distance: float | None


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


def chroma_collection_name(knowledge_base_id: str) -> str:
    return f"kb_{knowledge_base_id.replace('-', '')}"


def chroma_client(settings: Settings):
    import chromadb

    settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_persist_dir))


def get_chroma_collection(settings: Settings, knowledge_base_id: str):
    return chroma_client(settings).get_or_create_collection(chroma_collection_name(knowledge_base_id))


def delete_chroma_collection(settings: Settings, knowledge_base_id: str) -> None:
    client = chroma_client(settings)
    try:
        client.delete_collection(chroma_collection_name(knowledge_base_id))
    except Exception as exc:
        if "does not exist" not in str(exc).lower() and "not found" not in str(exc).lower():
            raise


def delete_chroma_vectors(settings: Settings, knowledge_base_id: str, vector_ids: list[str]) -> None:
    if not vector_ids:
        return
    get_chroma_collection(settings, knowledge_base_id).delete(ids=vector_ids)


def upsert_chroma_vectors(
    settings: Settings,
    knowledge_base: KnowledgeBase,
    chunks: list[VectorChunk],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise KnowledgePipelineError("Embedding response count did not match chunk count.")

    collection = get_chroma_collection(settings, knowledge_base.id)
    collection.upsert(
        ids=[chunk.id for chunk in chunks],
        embeddings=embeddings,
        documents=[chunk.content for chunk in chunks],
        metadatas=[
            {
                "workspace_id": knowledge_base.workspace_id,
                "knowledge_base_id": knowledge_base.id,
                "document_id": chunk.document_id,
                "document_filename": chunk.document_filename,
                "chunk_index": chunk.chunk_index,
            }
            for chunk in chunks
        ],
    )


def query_chroma_vectors(
    settings: Settings,
    knowledge_base_id: str,
    embedding: list[float],
    limit: int,
) -> list[VectorHit]:
    collection = get_chroma_collection(settings, knowledge_base_id)
    collection_count = collection.count()
    if collection_count == 0:
        return []

    result: dict[str, Any] = collection.query(query_embeddings=[embedding], n_results=min(limit, collection_count))
    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    return [
        VectorHit(chunk_id=chunk_id, distance=distances[index] if index < len(distances) else None)
        for index, chunk_id in enumerate(ids)
    ]
