"""
Source Service Facade for Taproot Application Layer.
Manages source document ingestion, extraction inspection, page assets, and Phase 5 error/recovery states.
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
from storage.store import DocumentStorage
from phase5.config.phase5_config import Phase5Config
from phase5.validation.input_validator import InputValidator


def _title_text(metadata: Dict[str, Any]) -> str:
    """
    Human-readable document title as a plain string.

    Persisted documents written before the ``TitleMetadata`` model existed store a
    bare string; everything since stores ``{"value": ..., "source": ...}``. Both are
    accepted so the client is always given a string it can render.
    """
    raw = metadata.get("title")
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ""


def _source_filename(struct_doc: Dict[str, Any]) -> str:
    """Original upload filename, from ``StructuredDocument.source`` (SourceMetadata)."""
    source = struct_doc.get("source") or {}
    name = source.get("filename") if isinstance(source, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


class SourceService:
    def __init__(
        self,
        doc_storage: Optional[DocumentStorage] = None,
        input_validator: Optional[InputValidator] = None,
        knowledge_builder: Optional[Any] = None,
    ):
        self.doc_storage = doc_storage or DocumentStorage()
        self.p5_config = Phase5Config()
        self.input_validator = input_validator or InputValidator()
        # Injected so tests can drive ingestion against a temporary storage root.
        self._knowledge_builder = knowledge_builder

    def list_sources(self) -> List[Dict[str, Any]]:
        """
        Lists stored documents with metadata, page counts, and Phase 5 ingestion status.
        """
        sources = []
        root_dir = self.doc_storage.root_dir
        if root_dir.exists():
            for doc_dir in root_dir.iterdir():
                if doc_dir.is_dir():
                    doc_id = doc_dir.name
                    struct_doc = self.doc_storage.load_structured_document(doc_id)
                    pdf_path = self.doc_storage.get_original_pdf_path(doc_id)

                    status = "READY"
                    recovery_state = "COMPLETED"
                    page_count = 0

                    if struct_doc and "pages" in struct_doc:
                        page_count = len(struct_doc["pages"])
                    elif pdf_path.exists():
                        status = "PROCESSING"
                        recovery_state = "RECOVERING"
                    else:
                        status = "PARTIAL"
                        recovery_state = "PARTIAL_RECOVERY"

                    fn = ""
                    if struct_doc:
                        # ``filename`` lives on ``StructuredDocument.source``
                        # (SourceMetadata), a sibling of ``metadata`` - reading it from
                        # ``metadata`` always returned "", so every upload was
                        # mislabelled as a PDF.
                        fn = _source_filename(struct_doc) or fn

                    # Title = real uploaded filename (extension stripped). Never
                    # generate a name from doc_id or PDF metadata.
                    title = fn.rsplit(".", 1)[0] if fn else doc_id.replace("_", " ").title()

                    file_type = Path(fn).suffix.replace(".", "").upper() if fn else "PDF"

                    is_demo = doc_id in ("calculus_101", "machine_learning", "subj_algebra", "subj_calculus_e2e")

                    sources.append({
                        "document_id": doc_id,
                        "title": title,
                        "filename": fn,
                        "file_type": file_type or "PDF",
                        "status": status,
                        "recovery_state": recovery_state,
                        "page_count": page_count,
                        "file_size_bytes": pdf_path.stat().st_size if pdf_path.exists() else 0,
                        "is_demo": is_demo,
                    })

        # No demo fallback: when nothing has been uploaded, the library is
        # empty. Fabricated entries ("42 pages, 10 MB") would teach material
        # the learner never uploaded.
        return sources

    def save_uploaded_source(self, document_id: str, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """
        Ingest an uploaded file and return its grounded knowledge build.

        Delegates to :class:`~backend.services.knowledge_build_service.KnowledgeBuildService`,
        which runs the real Phase 1 → Phase 2 → Phase 3 chain.

        The previous implementation sampled at most 12 pages, discarded the extracted
        text, wrote stub pages containing nothing but ``{"page_index": i, "status": "ok"}``,
        asked the LLM to invent 8-14 concepts from a truncated excerpt, and then — on an
        LLM error *or* on any exception at all — fabricated
        ``"<Title> Foundations" / "<Title> Core Principles" / "<Title> Advanced Topics"``.
        That is why the product could teach material the learner never uploaded. Any
        failure now raises a typed :mod:`phase3.errors` exception instead.
        """
        from backend.services.knowledge_build_service import KnowledgeBuildService

        builder = self._knowledge_builder or KnowledgeBuildService(storage=self.doc_storage)
        return builder.build(document_id, file_bytes, filename)
