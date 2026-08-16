"""Document parsing and chunking port.

The pipeline functions are pure and stateless (the parser integrations live
behind ``extract_document`` inside the capability), so this
port re-exports the contract surface; swapping the parser implementation
touches only ``app.capabilities.embedding.pipeline``.
"""

from typing import Any, Protocol

from app.capabilities.embedding.pipeline import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    ChildChunkDraft,
    DocumentAssetDraft,
    DocumentChunkDrafts,
    EMBED_BATCH_SIZE,
    KnowledgePipelineError,
    SPLIT_SEPARATORS,
    build_flat_chunks,
    build_hierarchical_chunks,
    chunk_token_count,
    clean_text,
    extract_document,
    has_printable_text,
    normalize_text,
    split_text,
    split_text_spans,
)
from app.capabilities.embedding.qa_import import QaRow, extract_qa_rows

__all__ = [
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "ChildChunkDraft",
    "DocumentAssetDraft",
    "DocumentChunkDrafts",
    "EMBED_BATCH_SIZE",
    "KnowledgePipelineError",
    "QaRow",
    "SPLIT_SEPARATORS",
    "build_flat_chunks",
    "build_hierarchical_chunks",
    "chunk_token_count",
    "clean_text",
    "extract_document",
    "extract_qa_rows",
    "has_printable_text",
    "normalize_text",
    "split_text",
    "split_text_spans",
]


class DocumentParser(Protocol):
    """Typing-only contract for the parsing pipeline; see module docstring."""

    def extract(self, filename: str, content_type: str, path: Any) -> Any: ...


def build_document_parser() -> DocumentParser:
    """Composition point for a parser implementation.

    Today the pipeline is stateless function collection; the returned adapter
    is a thin facade kept for a future swappable parser backend.
    """

    class _PipelineParser:
        def extract(self, filename: str, content_type: str, path: Any) -> Any:
            return extract_document(filename, content_type, path)

    return _PipelineParser()
