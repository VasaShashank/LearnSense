"""
Document Format Normalisation for Phase 1 Ingestion.

Every supported upload format must reach Phase 2 as a fully populated
:class:`~schemas.document.StructuredDocument` containing real text blocks, real
bounding boxes, real roles and a real section outline.

The previous implementation of ``SourceService`` did the opposite: it sampled a
handful of pages, discarded all extracted text, and wrote a stub document whose
"pages" contained nothing but ``{"page_index": i, "status": "ok"}``. Downstream
stages then had no evidence to ground anything in, which is exactly how the
production path ended up inventing content.

Supported inputs
-----------------
``pdf``      -> handled natively by :class:`ingestion.pipeline.IngestionPipeline`
``docx``     -> converted to PDF via LibreOffice when available, else parsed natively
``pptx``     -> converted to PDF via LibreOffice when available, else parsed natively
``png/jpg``  -> converted to PDF via PyMuPDF, then handled natively
``txt/md``   -> wrapped into a paginated PDF, then handled natively
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from phase3.errors import UnsupportedDocumentError
from schemas.document import (
    BlockContent,
    BlockStatusEnum,
    BlockTypeEnum,
    DocumentBlock,
    DocumentMetadata,
    DocumentPage,
    DocumentWarning,
    EngineInfo,
    ExtractionMethodEnum,
    PageOrientationEnum,
    PageStatusEnum,
    PageTypeEnum,
    ProcessingStatusEnum,
    SectionNode,
    SourceMetadata,
    StructuredDocument,
    TitleMetadata,
    TitleSourceEnum,
)

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst"}
OOXML_EXTENSIONS = {".docx", ".pptx"}

SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS | TEXT_EXTENSIONS | OOXML_EXTENSIONS

# Characters per synthetic page when paginating plain text.
_TEXT_PAGE_CHARS = 3000
_TEXT_CHARS_PER_LINE = 92
_TEXT_LINES_PER_PAGE = 42


def _fitz():
    import pymupdf as fitz  # noqa: PLC0415 - optional/lazy heavy import

    return fitz


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS


def _libreoffice_binary() -> Optional[str]:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _convert_with_libreoffice(source: Path, target_dir: Path) -> Optional[Path]:
    binary = _libreoffice_binary()
    if not binary:
        return None
    try:
        subprocess.run(
            [
                binary,
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(target_dir),
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    produced = target_dir / f"{source.stem}.pdf"
    return produced if produced.exists() and produced.stat().st_size > 0 else None


def image_to_pdf(image_bytes: bytes, extension: str) -> bytes:
    fitz = _fitz()
    img = fitz.open(stream=image_bytes, filetype=extension.lstrip("."))
    try:
        return img.convert_to_pdf()
    finally:
        img.close()


def text_to_pdf(text: str) -> bytes:
    """Paginate plain text into a real PDF so the normal Phase 1 path applies."""
    fitz = _fitz()
    doc = fitz.open()
    try:
        lines: List[str] = []
        for raw_line in (text or "").splitlines():
            raw_line = raw_line.rstrip()
            if not raw_line:
                lines.append("")
                continue
            while len(raw_line) > _TEXT_CHARS_PER_LINE:
                lines.append(raw_line[:_TEXT_CHARS_PER_LINE])
                raw_line = raw_line[_TEXT_CHARS_PER_LINE:]
            lines.append(raw_line)

        page: Optional[object] = None
        y = 0.0
        for line in lines:
            if page is None or y > 760:
                page = doc.new_page()
                y = 70.0
            try:
                page.insert_text((54, y), line, fontsize=10.5, fontname="helv")
            except Exception:  # pragma: no cover - glyph-level failures must not abort
                page.insert_text((54, y), " ", fontsize=10.5, fontname="helv")
            y += 14.0

        if page is None:
            doc.new_page()

        out = doc.tobytes()
    finally:
        doc.close()
    return out


def to_pdf(file_bytes: bytes, filename: str, document_id: str) -> Optional[Tuple[bytes, str]]:
    """
    Normalise ``file_bytes`` to PDF bytes plus the effective PDF filename.

    Returns ``None`` when the format is an OOXML document that could not be converted
    (LibreOffice absent). Callers must then use the native OOXML reader
    (:func:`docx_to_structured_document` / :func:`pptx_to_structured_document`), which
    still produces real text blocks -- just without page-exact coordinates.

    Raises :class:`UnsupportedDocumentError` for formats we cannot honestly process.
    """
    suffix = Path(filename).suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return file_bytes, filename

    if suffix in IMAGE_EXTENSIONS:
        try:
            return image_to_pdf(file_bytes, suffix), f"{Path(filename).stem}.pdf"
        except Exception as exc:  # pragma: no cover - corrupt image
            raise UnsupportedDocumentError(
                f"Could not convert image '{filename}' into a readable document.",
                details={"reason": str(exc)},
            ) from exc

    if suffix in TEXT_EXTENSIONS:
        try:
            decoded = file_bytes.decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover - defensive
            raise UnsupportedDocumentError(
                f"Could not decode text file '{filename}'.", details={"reason": str(exc)}
            ) from exc
        return text_to_pdf(decoded), f"{Path(filename).stem}.pdf"

    if suffix in OOXML_EXTENSIONS:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / f"input{suffix}"
            src.write_bytes(file_bytes)
            produced = _convert_with_libreoffice(src, tmp_path)
            if produced is not None:
                return produced.read_bytes(), produced.name
        # No LibreOffice: the caller must use the native reader.
        return None

    raise UnsupportedDocumentError(
        f"Unsupported file type '{suffix or filename}'. "
        f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        details={"filename": filename, "extension": suffix},
    )


def to_structured_document(file_bytes: bytes, filename: str, document_id: str, run_pdf_pipeline):
    """
    Produce a fully populated ``StructuredDocument`` for any supported upload.

    ``run_pdf_pipeline`` is a callable ``(pdf_bytes, pdf_name, document_id) ->
    StructuredDocument``; injecting it keeps this module free of any dependency on the
    Phase 1 pipeline while still guaranteeing every format yields real text blocks.
    """
    suffix = Path(filename).suffix.lower()

    converted = to_pdf(file_bytes, filename, document_id)

    if converted is not None:
        pdf_bytes, pdf_name = converted
        return run_pdf_pipeline(pdf_bytes, pdf_name, document_id)

    if suffix == ".docx":
        return docx_to_structured_document(file_bytes, filename, document_id)
    if suffix == ".pptx":
        return pptx_to_structured_document(file_bytes, filename, document_id)

    raise UnsupportedDocumentError(
        f"Could not convert '{filename}' into a readable document.",
        details={"filename": filename, "extension": suffix},
    )


# ---------------------------------------------------------------------------
# Native (LibreOffice-free) OOXML readers
# ---------------------------------------------------------------------------


def _block(
    block_id: str,
    text: str,
    page_index: int,
    reading_order: int,
    block_type: BlockTypeEnum,
    role: str,
    y0: float,
    height: float = 14.0,
) -> DocumentBlock:
    width = 612.0
    return DocumentBlock(
        block_id=block_id,
        type=block_type,
        role=role,
        bbox=[54.0, y0, width - 54.0, min(y0 + height, 780.0)],
        content=BlockContent(text=text, text_raw=text),
        reading_order=reading_order,
        extraction_method=ExtractionMethodEnum.NATIVE,
        engine=EngineInfo(name="OOXMLNativeReader", version="1.0"),
        confidence=1.0,
        status=BlockStatusEnum.OK,
    )


def _paginate(
    blocks: List[DocumentBlock], *, page_width: float = 612.0, page_height: float = 792.0
) -> List[DocumentPage]:
    """Chunk a flat block list into pseudo-pages so page_count is meaningful."""
    pages: List[DocumentPage] = []
    per_page = 34
    for page_index, start in enumerate(range(0, len(blocks), per_page) or [0]):
        chunk = blocks[start : start + per_page]
        if not chunk:
            chunk = []
        pages.append(
            DocumentPage(
                page_index=page_index,
                page_label=str(page_index + 1),
                width=page_width,
                height=page_height,
                orientation=PageOrientationEnum.PORTRAIT,
                page_type=PageTypeEnum.NATIVE,
                status=PageStatusEnum.OK if chunk else PageStatusEnum.EMPTY,
                blocks=chunk,
            )
        )
    if not pages:
        pages.append(
            DocumentPage(
                page_index=0,
                page_label="1",
                width=page_width,
                height=page_height,
                orientation=PageOrientationEnum.PORTRAIT,
                page_type=PageTypeEnum.EMPTY,
                status=PageStatusEnum.EMPTY,
                blocks=[],
            )
        )
    return pages


def _build_outline(pages: List[DocumentPage]) -> List[SectionNode]:
    sections: List[SectionNode] = []
    counter = 1
    for page in pages:
        for block in page.blocks:
            if block.type == BlockTypeEnum.HEADING:
                sec_id = f"sec_{counter:03d}"
                block.section_id = sec_id
                sections.append(
                    SectionNode(
                        section_id=sec_id,
                        title=block.content.text.strip(),
                        level=1,
                        page_start=page.page_index + 1,
                    )
                )
                counter += 1
    return sections


def docx_to_structured_document(file_bytes: bytes, filename: str, document_id: str) -> StructuredDocument:
    import docx as python_docx  # noqa: PLC0415

    document = python_docx.Document(io.BytesIO(file_bytes))

    blocks: List[DocumentBlock] = []
    order = 1
    y = 70.0
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            y += 6.0
            continue
        style_name = ""
        if paragraph.style is not None and getattr(paragraph.style, "name", None):
            style_name = str(paragraph.style.name)

        if style_name.lower().startswith("heading"):
            btype, role = BlockTypeEnum.HEADING, "heading_l1"
        elif style_name.lower().startswith("title"):
            btype, role = BlockTypeEnum.HEADING, "heading_l1"
        elif style_name.lower() in ("list bullet", "list number", "list paragraph"):
            btype, role = BlockTypeEnum.LIST_ITEM, "list"
        else:
            btype, role = BlockTypeEnum.PARAGRAPH, "body"

        blocks.append(
            _block(
                f"blk_docx_{order:04d}", text, 0, order, btype, role, y, height=12.0 * max(1, len(text) // 90 + 1)
            )
        )
        order += 1
        y += 14.0 * max(1, len(text) // 90 + 1)
        if y > 760:
            y = 70.0

    pages = _paginate(blocks)
    outline = _build_outline(pages)

    title = next((b.content.text for p in pages for b in p.blocks if b.type == BlockTypeEnum.HEADING), None)
    return StructuredDocument(
        document_id=document_id,
        source=SourceMetadata(sha256="", filename=filename, size_bytes=len(file_bytes)),
        metadata=DocumentMetadata(
            page_count=len(pages),
            title=TitleMetadata(
                value=title or Path(filename).stem.replace("_", " ").title(),
                source=TitleSourceEnum.INFERRED,
            ),
            processing_status=ProcessingStatusEnum.COMPLETED,
        ),
        outline=outline,
        pages=pages,
        warnings=[],
    )


def pptx_to_structured_document(file_bytes: bytes, filename: str, document_id: str) -> StructuredDocument:
    import pptx  # noqa: PLC0415

    presentation = pptx.Presentation(io.BytesIO(file_bytes))

    pages: List[DocumentPage] = []
    used_fallback = False
    for slide_index, slide in enumerate(presentation.slides):
        blocks: List[DocumentBlock] = []
        order = 1
        y = 70.0
        try:
            title_shape = slide.shapes.title
            title_text = title_shape.text.strip() if title_shape is not None else ""
        except Exception:  # pragma: no cover - layout without a title placeholder
            title_text = ""

        if title_text:
            blocks.append(
                _block(f"blk_p{slide_index:04d}_ppt_{order:04d}", title_text, slide_index, order,
                       BlockTypeEnum.HEADING, "heading_l1", y, height=20.0)
            )
            order += 1
            y += 34.0

        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            if title_shape is not None and shape is title_shape:
                continue
            for para in shape.text_frame.paragraphs:
                text = para.text.strip()
                if not text:
                    continue
                role = "list" if para.level and para.level > 0 else "body"
                btype = BlockTypeEnum.LIST_ITEM if role == "list" else BlockTypeEnum.PARAGRAPH
                blocks.append(
                    _block(f"blk_p{slide_index:04d}_ppt_{order:04d}", text, slide_index, order, btype, role, y)
                )
                order += 1
                y += 15.0
                if y > 760:
                    y = 70.0

        pages.append(
            DocumentPage(
                page_index=slide_index,
                page_label=str(slide_index + 1),
                width=960.0,
                height=540.0,
                orientation=PageOrientationEnum.LANDSCAPE,
                page_type=PageTypeEnum.NATIVE,
                status=PageStatusEnum.OK if blocks else PageStatusEnum.EMPTY,
                blocks=blocks,
            )
        )

    if not pages:
        pages = _paginate([])

    outline = _build_outline(pages)
    title = next(
        (b.content.text for p in pages for b in p.blocks if b.type == BlockTypeEnum.HEADING), None
    )
    return StructuredDocument(
        document_id=document_id,
        source=SourceMetadata(sha256="", filename=filename, size_bytes=len(file_bytes)),
        metadata=DocumentMetadata(
            page_count=len(pages),
            title=TitleMetadata(
                value=title or Path(filename).stem.replace("_", " ").title(),
                source=TitleSourceEnum.INFERRED,
            ),
            processing_status=ProcessingStatusEnum.COMPLETED,
        ),
        outline=outline,
        pages=pages,
        warnings=[],
    )
