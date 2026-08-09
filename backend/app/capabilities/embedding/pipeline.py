import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import mammoth
import pymupdf
import pymupdf4llm
from markitdown import MarkItDown, StreamInfo
from markitdown.converters._docx_converter import pre_process_docx
from markitdown.converters._html_converter import HtmlConverter
from PIL import Image

from app.infrastructure.model_utils import new_id

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
PARENT_CHUNK_SIZE = CHUNK_SIZE * 4
EMBED_BATCH_SIZE = 64
PDF_OCR_LANGUAGE = "chi_sim+eng"
MARKITDOWN = MarkItDown(enable_plugins=False)
SPLIT_SEPARATORS = frozenset({"\n\n", "\n", "。", "."})
IMAGE_DOCUMENT_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {
        ".docx",
        ".md",
        ".markdown",
        ".pdf",
        ".txt",
        ".pptx",
        ".xlsx",
        ".xls",
        ".html",
        ".csv",
        ".json",
        ".xml",
        ".ipynb",
        ".epub",
        ".zip",
        *IMAGE_DOCUMENT_EXTENSIONS,
    }
)
MARKDOWN_HEADING_PATTERN = re.compile(
    r"^\s{0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$"
)
PDF_INLINE_FORMAT_TAG_PATTERN = re.compile(r"</?(?:sub|sup)>", re.IGNORECASE)
PDF_CJK_SPACE_PATTERN = re.compile(
    r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]) +"
    r"(?=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff，。！？；：、）》】」』])"
)
PDF_CJK_LEADING_SPACE_PATTERN = re.compile(
    r"(?<=[（《【「『]) +(?=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])"
)
PDF_CJK_PUNCTUATION_SPACE_PATTERN = re.compile(
    r"(?<=[，。！？；：、）》】」』）]) +"
    r"(?=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])"
)
ASSET_MARKER_BASE = 0xE000
ASSET_MARKER_LIMIT = 0xF8FF - ASSET_MARKER_BASE + 1
ASSET_MARKER_PATTERN = re.compile(r"[\ue000-\uf8ff]")
DOCX_ASSET_MARKDOWN_PATTERN = re.compile(
    r"!\[([^]]*)]\(nexaflow-asset://(\d+)\)",
    re.IGNORECASE,
)
DOCX_EXTENSION_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "image/webp": "webp",
}


def asset_marker(asset_index: int) -> str:
    if not 0 <= asset_index < ASSET_MARKER_LIMIT:
        raise KnowledgePipelineError("Document contains too many embedded images.")
    return chr(ASSET_MARKER_BASE + asset_index)


def extract_asset_indexes(content: str) -> list[int]:
    return list(
        dict.fromkeys(
            ord(marker) - ASSET_MARKER_BASE
            for marker in ASSET_MARKER_PATTERN.findall(content)
        )
    )


def remove_asset_markers(content: str) -> str:
    return ASSET_MARKER_PATTERN.sub("", content)


def strip_asset_markers(content: str) -> str:
    return remove_asset_markers(content).strip()


@dataclass(frozen=True)
class DocumentAssetDraft:
    id: str
    filename: str
    content_type: str
    content: bytes
    alt_text: str




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
    asset_indexes: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentChunkDrafts:
    parents: list[ParentChunkDraft]
    children: list[ChildChunkDraft]
    assets: list[DocumentAssetDraft] = field(default_factory=list)


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


def normalize_pdf_markdown(filename: str, markdown: str) -> str:
    markdown = PDF_INLINE_FORMAT_TAG_PATTERN.sub("", markdown)
    markdown = PDF_CJK_SPACE_PATTERN.sub("", markdown)
    markdown = PDF_CJK_LEADING_SPACE_PATTERN.sub("", markdown)
    markdown = PDF_CJK_PUNCTUATION_SPACE_PATTERN.sub("", markdown)
    if not any(MARKDOWN_HEADING_PATTERN.match(line) for line in markdown.splitlines()):
        markdown = f"# {Path(filename).stem}\n\n{markdown}"
    return markdown


def extract_with_pymupdf(
    filename: str,
    source: Path | pymupdf.Document,
    *,
    force_ocr: bool,
) -> str:
    extracted_text = pymupdf4llm.to_markdown(
        source,
        use_ocr=True,
        force_ocr=force_ocr,
        ocr_language=PDF_OCR_LANGUAGE,
        ocr_dpi=300,
        write_images=False,
    )
    if not isinstance(extracted_text, str):
        raise TypeError("PyMuPDF Markdown conversion returned an invalid result.")
    return normalize_pdf_markdown(filename, extracted_text)


def extract_webp_with_pymupdf(filename: str, path: Path) -> str:
    converted = BytesIO()
    with Image.open(path) as image:
        image.save(converted, format="PNG")
    document = pymupdf.open(stream=converted.getvalue(), filetype="png")
    try:
        return extract_with_pymupdf(filename, document, force_ocr=True)
    finally:
        if not document.is_closed:
            document.close()


def extract_document(
    filename: str,
    content_type: str,
    path: Path,
) -> tuple[str, list[DocumentAssetDraft]]:
    if not path.exists():
        raise KnowledgePipelineError("Document file is missing.")

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise KnowledgePipelineError("Document format is not supported.")

    content_type = content_type.split(";", 1)[0].strip().lower()
    assets: list[DocumentAssetDraft] = []
    try:
        if extension == ".docx":
            def convert_image(image):
                asset_id = new_id()
                asset_index = len(assets)
                image_content_type = image.content_type or "application/octet-stream"
                extension_name = DOCX_EXTENSION_BY_MIME.get(
                    image_content_type,
                    image_content_type.split("/", 1)[-1] or "bin",
                )
                alt_text = (image.alt_text or "").strip()[:500]
                with image.open() as image_bytes:
                    image_content = image_bytes.read()
                assets.append(
                    DocumentAssetDraft(
                        id=asset_id,
                        filename=f"inline_image_{asset_id}.{extension_name}",
                        content_type=image_content_type,
                        content=image_content,
                        alt_text=alt_text,
                    )
                )
                return {
                    "src": f"nexaflow-asset://{asset_index}",
                    "alt": alt_text,
                }

            with path.open("rb") as stream:
                html = mammoth.convert_to_html(
                    pre_process_docx(stream),
                    convert_image=mammoth.images.img_element(convert_image),
                ).value
            extracted_text = HtmlConverter().convert_string(html).text_content
            extracted_text = DOCX_ASSET_MARKDOWN_PATTERN.sub(
                lambda match: f"{match.group(1)} {asset_marker(int(match.group(2)))}".strip(),
                extracted_text,
            )
        elif extension == ".pdf":
            # Native PDF text is preferred; OCR runs only for pages without usable text.
            extracted_text = extract_with_pymupdf(filename, path, force_ocr=False)
        elif extension == ".webp":
            extracted_text = extract_webp_with_pymupdf(filename, path)
        elif extension in IMAGE_DOCUMENT_EXTENSIONS:
            # Standalone images have no text layer, so OCR is always required.
            extracted_text = extract_with_pymupdf(filename, path, force_ocr=True)
        else:
            result = MARKITDOWN.convert_local(
                path,
                stream_info=StreamInfo(
                    mimetype=content_type or None,
                    extension=extension,
                    filename=filename,
                    local_path=str(path),
                ),
            )
            extracted_text = result.text_content
    except Exception as exc:
        raise KnowledgePipelineError("Document text extraction failed.") from exc

    text = normalize_text(extracted_text)
    if not text or not has_printable_text(strip_asset_markers(text)):
        raise KnowledgePipelineError("Document has no extractable text.")
    return text, assets


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
    raw_parents = split_parent_chunks(text)
    parents: list[ParentChunkDraft] = []
    children: list[ChildChunkDraft] = []
    for parent_index, raw_parent in enumerate(raw_parents):
        clean_parent = remove_asset_markers(raw_parent.content)
        parents.append(
            ParentChunkDraft(
                title=raw_parent.title,
                content=clean_parent.strip(),
            )
        )
        parent_leading = len(clean_parent) - len(clean_parent.lstrip())
        for span in split_text_spans(
            raw_parent.content,
            chunk_size,
            overlap,
            separator,
        ):
            cleaned_span = remove_asset_markers(span.content)
            content = cleaned_span.strip()
            if not content:
                continue
            span_leading = len(cleaned_span) - len(cleaned_span.lstrip())
            start_offset = (
                len(remove_asset_markers(raw_parent.content[: span.start_offset]))
                + span_leading
                - parent_leading
            )
            children.append(
                ChildChunkDraft(
                    content=content,
                    parent_index=parent_index,
                    start_offset=start_offset,
                    end_offset=start_offset + len(content),
                    asset_indexes=extract_asset_indexes(span.content),
                )
            )
    return DocumentChunkDrafts(parents=parents, children=children)


def build_flat_chunks(contents: list[str]) -> DocumentChunkDrafts:
    return DocumentChunkDrafts(
        parents=[],
        children=[
            ChildChunkDraft(
                content=strip_asset_markers(content),
                asset_indexes=extract_asset_indexes(content),
            )
            for content in contents
            if strip_asset_markers(content)
        ],
    )


def chunk_token_count(content: str) -> int:
    return max(1, len(content.split()))
