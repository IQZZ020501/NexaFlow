import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, LargeZipFile, ZipFile, is_zipfile

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
    r"^\s{0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$"
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
ARCHIVE_MEMBER_EXTENSIONS = frozenset({".docx", ".epub", ".pptx", ".xlsx", ".zip"})
MAX_ARCHIVE_ENTRIES = 5_000
MAX_ARCHIVE_NESTING_DEPTH = 3
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


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
    # 表格续段在内容开头重复的表头+对齐行（首段与普通文本为 None）。
    # content == table_header_prefix + text[start_offset:end_offset]。
    table_header_prefix: str | None = None


@dataclass(frozen=True)
class ParentChunkDraft:
    title: str
    content: str
    section_path: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChildChunkDraft:
    content: str
    parent_index: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    asset_indexes: list[int] = field(default_factory=list)
    kind: str = "document"
    meta: dict[str, object] = field(default_factory=dict)


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


def validate_archive(path: Path) -> None:
    if not is_zipfile(path):
        return

    state = {"entries": 0, "bytes": 0}

    def inspect(source, depth: int) -> None:
        try:
            with ZipFile(source) as archive:
                for member in archive.infolist():
                    state["entries"] += 1
                    if state["entries"] > MAX_ARCHIVE_ENTRIES:
                        raise KnowledgePipelineError(
                            "Document archive contains too many entries."
                        )
                    if member.is_dir():
                        continue

                    state["bytes"] += member.file_size
                    if state["bytes"] > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise KnowledgePipelineError(
                            "Document archive contains too much expanded data."
                        )

                    if Path(member.filename).suffix.lower() not in ARCHIVE_MEMBER_EXTENSIONS:
                        continue
                    if depth >= MAX_ARCHIVE_NESTING_DEPTH:
                        raise KnowledgePipelineError(
                            "Document archive nesting is too deep."
                        )
                    with archive.open(member) as nested:
                        nested_content = nested.read(
                            MAX_ARCHIVE_UNCOMPRESSED_BYTES + 1
                        )
                    if len(nested_content) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise KnowledgePipelineError(
                            "Document archive contains too much expanded data."
                        )
                    nested_stream = BytesIO(nested_content)
                    if is_zipfile(nested_stream):
                        nested_stream.seek(0)
                        inspect(nested_stream, depth + 1)
        except (BadZipFile, LargeZipFile) as exc:
            raise KnowledgePipelineError("Document archive is invalid.") from exc

    inspect(path, 1)


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
    validate_archive(path)
    assets: list[DocumentAssetDraft] = []
    try:
        if extension == ".docx":
            def convert_image(image):
                asset_id = new_id()
                asset_index = len(assets)
                image_content_type = image.content_type or "application/octet-stream"
                extension_name = DOCX_EXTENSION_BY_MIME.get(image_content_type)
                if extension_name is None:
                    image_content_type = "application/octet-stream"
                    extension_name = "bin"
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


def _is_table_row_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_table_alignment_line(line: str) -> bool:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return False
    return any(
        cell and set(cell) <= {"-", ":"}
        for cell in (part.strip() for part in stripped[1:-1].split("|"))
    )


def _find_table_blocks(text: str) -> list[tuple[int, int]]:
    """定位 markdown 管道表格块（表头行 + 对齐行 + 连续数据行）的字符区间。"""
    blocks: list[tuple[int, int]] = []
    lines = text.splitlines(keepends=True)
    line_starts: list[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line)

    index = 0
    while index < len(lines):
        if (
            _is_table_row_line(lines[index])
            and index + 1 < len(lines)
            and _is_table_alignment_line(lines[index + 1])
        ):
            end_index = index + 2
            while end_index < len(lines) and (
                _is_table_row_line(lines[end_index])
                and not _is_table_alignment_line(lines[end_index])
            ):
                end_index += 1
            blocks.append(
                (
                    line_starts[index],
                    line_starts[end_index - 1] + len(lines[end_index - 1]),
                )
            )
            index = end_index
        else:
            index += 1
    return blocks


def _split_table_block(
    text: str,
    table_start: int,
    table_end: int,
    chunk_size: int,
) -> list[TextSpan]:
    """表格 ≤ chunk_size 时整体保留；否则只在数据行之间切分，续段重复表头。"""
    lines: list[str] = []
    line_starts: list[int] = []
    pos = table_start
    while pos < table_end:
        newline = text.find("\n", pos)
        line_starts.append(pos)
        if newline == -1 or newline >= table_end:
            lines.append(text[pos:table_end])
            break
        lines.append(text[pos : newline + 1])
        pos = newline + 1

    if table_end - table_start <= chunk_size:
        return [
            TextSpan(
                content=text[table_start:table_end],
                start_offset=table_start,
                end_offset=table_end,
            )
        ]

    data_lines = lines[2:]
    if not data_lines:
        # 仅有表头+对齐行且超限：整体保留，允许超限。
        return [
            TextSpan(
                content=text[table_start:table_end],
                start_offset=table_start,
                end_offset=table_end,
            )
        ]
    prefix = lines[0] + lines[1]
    budget = chunk_size - len(prefix)

    spans: list[TextSpan] = []
    row_start = 0
    while row_start < len(data_lines):
        row_end = row_start
        size = 0
        while (
            row_end < len(data_lines)
            and size + len(data_lines[row_end]) <= budget
        ):
            size += len(data_lines[row_end])
            row_end += 1
        if row_end == row_start:
            # 表头+单行仍超限：允许该段超限，不切单元格。
            row_end = row_start + 1
        rows = data_lines[row_start:row_end]
        data_start = line_starts[row_start + 2]
        data_end = line_starts[row_end + 1] + len(data_lines[row_end - 1])
        spans.append(
            TextSpan(
                content=prefix + "".join(rows),
                start_offset=table_start if row_start == 0 else data_start,
                end_offset=data_end,
                table_header_prefix=prefix if row_start > 0 else None,
            )
        )
        row_start = row_end
    return spans


def split_text_spans(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    separator: str = "\n\n",
) -> list[TextSpan]:
    chunks: list[TextSpan] = []
    text_length = len(text)
    table_blocks = _find_table_blocks(text)
    block_index = 0
    start = 0

    while start < text_length:
        if block_index < len(table_blocks):
            table_start, table_end = table_blocks[block_index]
            if start <= table_start and text[start:table_start].strip() == "":
                start = table_start
                chunks.extend(
                    _split_table_block(text, table_start, table_end, chunk_size)
                )
                block_index += 1
                start = table_end
                while start < text_length and text[start].isspace():
                    start += 1
                continue

        run_end = (
            table_blocks[block_index][0]
            if block_index < len(table_blocks)
            else text_length
        )
        end = min(start + chunk_size, run_end)
        if end < run_end:
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
        if end >= run_end:
            if run_end == text_length:
                break
            start = run_end
            continue

        next_start = max(end - overlap, 0)
        if next_start <= start:
            next_start = end
        while next_start < run_end and text[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks


def split_parent_chunks(
    text: str,
    max_size: int = PARENT_CHUNK_SIZE,
) -> list[ParentChunkDraft]:
    sections: list[tuple[str, list[str], str]] = []
    section_start = 0
    section_title = ""
    section_path: list[str] = []
    heading_stack: list[str] = []
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
                sections.append((section_title, section_path, content))
            section_start = offset
            level = len(heading.group(1))
            section_title = heading.group(2).strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(section_title)
            section_path = list(heading_stack)
        offset += len(line)

    content = text[section_start:].strip()
    if content:
        sections.append((section_title, section_path, content))

    parents: list[ParentChunkDraft] = []
    for title, path, section in sections:
        parents.extend(
            ParentChunkDraft(
                title=title,
                content=span.content,
                section_path=path,
            )
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
                section_path=raw_parent.section_path,
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
            if span.table_header_prefix is not None:
                # 续段 content 含重复表头，偏移区间仅覆盖其数据行；
                # 表头/对齐行可能含 asset marker，须用清除后的长度计算。
                cleaned_prefix = remove_asset_markers(span.table_header_prefix)
                end_offset = start_offset + len(content) - len(cleaned_prefix)
            else:
                end_offset = start_offset + len(content)
            children.append(
                ChildChunkDraft(
                    content=content,
                    parent_index=parent_index,
                    start_offset=start_offset,
                    end_offset=end_offset,
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
