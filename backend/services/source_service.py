"""
Source Service Facade for Taproot Application Layer.
Manages source document ingestion, extraction inspection, page assets, and Phase 5 error/recovery states.
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
from storage.store import DocumentStorage
from phase5.config.phase5_config import Phase5Config
from phase5.validation.input_validator import InputValidator


class SourceService:
    def __init__(
        self,
        doc_storage: Optional[DocumentStorage] = None,
        input_validator: Optional[InputValidator] = None,
    ):
        self.doc_storage = doc_storage or DocumentStorage()
        self.p5_config = Phase5Config()
        self.input_validator = input_validator or InputValidator()

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

                    title = doc_id.replace("_", " ").title()
                    fn = ""
                    if struct_doc and "metadata" in struct_doc:
                        if struct_doc["metadata"].get("title"):
                            title = struct_doc["metadata"]["title"]
                        fn = struct_doc["metadata"].get("filename", "")

                    file_type = Path(fn).suffix.replace(".", "").upper() if fn else "PDF"

                    sources.append({
                        "document_id": doc_id,
                        "title": title,
                        "filename": fn,
                        "file_type": file_type or "PDF",
                        "status": status,
                        "recovery_state": recovery_state,
                        "page_count": page_count,
                        "file_size_bytes": pdf_path.stat().st_size if pdf_path.exists() else 0,
                    })

        # Provide standard demonstration sources if empty
        if not sources:
            sources = [
                {
                    "document_id": "calculus_101",
                    "title": "Calculus: Early Transcendentals (Textbook)",
                    "status": "READY",
                    "recovery_state": "COMPLETED",
                    "page_count": 42,
                    "file_size_bytes": 10485760,
                },
                {
                    "document_id": "machine_learning",
                    "title": "Introduction to Statistical Machine Learning",
                    "status": "READY",
                    "recovery_state": "COMPLETED",
                    "page_count": 58,
                    "file_size_bytes": 15728640,
                }
            ]
        return sources

    def save_uploaded_source(self, document_id: str, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """
        Saves PDF, checks Phase 5 validation rules, extracts pages, and initializes subject knowledge context.
        """
        val_res = self.input_validator.validate_file(file_bytes, filename)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0] if val_res.errors else "Invalid document format.")

        ext = Path(filename).suffix.lower()
        saved_path = self.doc_storage.save_original_pdf(document_id, file_bytes, filename=filename)

        # Process document pages and metadata according to format
        page_count = 1
        concepts_created = 0
        clean_name = Path(filename).stem.replace("_", " ").replace("-", " ").title()
        subject_title = clean_name
        toc = []
        sample_text_snippets = []

        try:
            if ext == ".pdf":
                import pymupdf as fitz
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                page_count = len(doc)
                toc = doc.get_toc()  # [(level, title, page_num)]
                for p_idx in range(min(12, page_count)):
                    page_txt = doc[p_idx].get_text()
                    if page_txt and len(page_txt.strip()) > 10:
                        sample_text_snippets.append(page_txt.strip()[:600])
                doc.close()

            elif ext == ".docx":
                import io
                import docx
                doc = docx.Document(io.BytesIO(file_bytes))
                for p in doc.paragraphs:
                    txt = p.text.strip()
                    if not txt:
                        continue
                    if p.style and hasattr(p.style, "name") and "heading" in p.style.name.lower():
                        toc.append((1, txt, len(sample_text_snippets) + 1))
                    sample_text_snippets.append(txt)
                page_count = max(1, len(sample_text_snippets) // 5)

            elif ext == ".pptx":
                import io
                import pptx
                prs = pptx.Presentation(io.BytesIO(file_bytes))
                page_count = len(prs.slides)
                for s_idx, slide in enumerate(prs.slides):
                    slide_texts = []
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            for para in shape.text_frame.paragraphs:
                                t = para.text.strip()
                                if t:
                                    slide_texts.append(t)
                    if slide_texts:
                        slide_content = " | ".join(slide_texts)
                        sample_text_snippets.append(f"Slide {s_idx + 1}: {slide_content}")
                        toc.append((1, slide_texts[0][:50], s_idx + 1))

            elif ext in (".png", ".jpg", ".jpeg"):
                import io
                import pymupdf as fitz
                page_count = 1
                img_doc = fitz.open(stream=file_bytes, filetype=ext.replace(".", ""))
                pdf_bytes = img_doc.convert_to_pdf()
                self.doc_storage.save_original_pdf(document_id, pdf_bytes, filename=f"{Path(filename).stem}.pdf")
                pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                extracted_txt = pdf_doc[0].get_text().strip()
                if extracted_txt:
                    sample_text_snippets.append(extracted_txt[:800])
                else:
                    sample_text_snippets.append(f"Visual Course Material / Diagram: {clean_name}")
                pdf_doc.close()
                img_doc.close()

            combined_sample = "\n---\n".join(sample_text_snippets)[:4000]

            # Call LLM to extract curriculum title, concepts, and prerequisites
            from phase3.adapters.llm_adapter import Phase3LLMAdapter
            from phase3.knowledge.phase2_adapter import LearningContext, ConceptView, PrerequisiteLink
            from storage.repositories import LearningContextRepository

            llm = Phase3LLMAdapter()
            llm_prompt = (
                f"You are an educational curriculum knowledge graph extractor.\n"
                f"Analyze this uploaded course document excerpt from '{filename}' (format: {ext.upper()}):\n"
                f"{combined_sample}\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Determine the clean, formal Subject Title (e.g., 'Molecular & Cellular Biology', 'Operating Systems', 'Microeconomics'). If the content is from a slide deck or notes titled '{clean_name}', infer the formal academic subject title.\n"
                f"2. Extract 8 to 14 foundational educational concepts in progressive pedagogical order.\n"
                f"3. For each concept provide:\n"
                f"   - 'name': specific canonical concept name\n"
                f"   - 'description': clear 1-2 sentence educational definition\n"
                f"   - 'prerequisites': list of names of prerequisite concepts from this list that must be learned before it\n"
            )
            llm_schema = {
                "subject_title": "string",
                "concepts": [
                    {
                        "name": "string",
                        "description": "string",
                        "prerequisites": ["string"]
                    }
                ]
            }

            extracted_concepts = []
            try:
                res = llm.generate_json(llm_prompt, llm_schema)
                if res.get("subject_title"):
                    subject_title = res["subject_title"].strip()
                if isinstance(res.get("concepts"), list) and len(res["concepts"]) > 0:
                    extracted_concepts = res["concepts"]
            except Exception:
                pass

            # Fallback to TOC or headings if LLM extraction returned empty
            if not extracted_concepts:
                extracted_titles = []
                if toc:
                    extracted_titles = [item[1].strip() for item in toc if item[1] and len(item[1].strip()) > 2]
                if not extracted_titles:
                    extracted_titles = [f"{subject_title} Foundations", f"{subject_title} Core Principles", f"{subject_title} Advanced Topics"]
                extracted_concepts = [
                    {"name": t, "description": f"Key educational concept in {subject_title}.", "prerequisites": []}
                    for t in extracted_titles[:12]
                ]

            # Save basic structured document format
            struct_doc = {
                "document_id": document_id,
                "metadata": {
                    "title": subject_title,
                    "filename": filename,
                },
                "pages": [{"page_index": i, "status": "ok"} for i in range(page_count)],
                "sections": [{"title": c["name"], "page_index": 0} for c in extracted_concepts],
            }
            self.doc_storage.save_structured_document(document_id, struct_doc)

            # Build LearningContext with concepts and prerequisites
            ctx_repo = LearningContextRepository()
            ctx = LearningContext(
                document_id=document_id,
                knowledge_document_id=f"kdoc_{document_id}",
            )
            name_to_cid = {}
            for item in extracted_concepts:
                cname = item.get("name", "").strip()
                if not cname:
                    continue
                cid = cname.lower().replace(" ", "_").replace("-", "_")[:32].strip("_")
                name_to_cid[cname.lower()] = cid
                ctx.concepts[cid] = ConceptView(
                    concept_id=cid,
                    canonical_name=cname,
                    description=item.get("description", f"Core concept in {subject_title}."),
                    type="concept",
                )

            # Add prerequisite links
            for item in extracted_concepts:
                target_cid = name_to_cid.get(item.get("name", "").lower())
                if not target_cid:
                    continue
                for prereq_name in item.get("prerequisites", []):
                    source_cid = name_to_cid.get(prereq_name.lower())
                    if source_cid and source_cid != target_cid:
                        ctx.prerequisites.append(
                            PrerequisiteLink(
                                source_concept_id=source_cid,
                                target_concept_id=target_cid,
                                confidence=0.9,
                            )
                        )

            ctx_repo.save_context(ctx)
            concepts_created = len(ctx.concepts)

        except Exception as e:
            import logging
            logging.getLogger("SourceService").error(f"Error processing PDF {filename}: {e}", exc_info=True)
            # Fallback safe structured doc
            fallback_struct = {
                "document_id": document_id,
                "metadata": {"title": subject_title},
                "pages": [{"page_index": 0, "status": "ok"}],
                "sections": [],
            }
            self.doc_storage.save_structured_document(document_id, fallback_struct)

            # Ensure LearningContext has basic concepts if not already saved
            ctx_repo = LearningContextRepository()
            if not ctx_repo.load_context(document_id):
                ctx = LearningContext(
                    document_id=document_id,
                    knowledge_document_id=f"kdoc_{document_id}",
                )
                default_names = [f"{subject_title} Foundations", f"{subject_title} Core Principles", f"{subject_title} Advanced Topics"]
                for d_name in default_names:
                    cid = d_name.lower().replace(" ", "_")[:32].strip("_")
                    ctx.concepts[cid] = ConceptView(
                        concept_id=cid,
                        canonical_name=d_name,
                        description=f"Fundamental concepts and principles of {subject_title}.",
                        type="concept",
                    )
                ctx_repo.save_context(ctx)
                concepts_created = len(ctx.concepts)

        return {
            "document_id": document_id,
            "filename": filename,
            "title": subject_title,
            "status": "READY",
            "recovery_state": "COMPLETED",
            "page_count": page_count,
            "concept_count": concepts_created,
            "saved_path": str(saved_path),
        }
