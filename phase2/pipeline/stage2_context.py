"""
Stage 2 — Document and Section Context.
Computes document profile and builds hierarchical section path context.
Plan §5.
"""

from typing import Dict, List, Optional
from schemas.document import StructuredDocument, SectionNode
from phase2.models import DocumentProfile
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext


def compute_document_profile(doc: StructuredDocument) -> DocumentProfile:
    title_text = (doc.metadata.title.value if doc.metadata and doc.metadata.title else "").lower()

    genre = "textbook"
    if "exam" in title_text or "paper" in title_text or "test" in title_text:
        genre = "question_paper"
    elif "slide" in title_text or "lecture" in title_text:
        genre = "slides"
    elif "worksheet" in title_text or "exercise" in title_text:
        genre = "worksheet"

    domain_hint = None
    for domain in ["physics", "calculus", "biology", "chemistry", "finance", "economics", "computer science"]:
        if domain in title_text:
            domain_hint = domain
            break

    languages = ["en"]
    for page in doc.pages:
        for block in page.blocks:
            if block.language and block.language not in languages:
                languages.append(block.language)

    return DocumentProfile(
        genre=genre,
        domain_hint=domain_hint,
        languages=languages
    )


def build_section_path_map(outline: List[SectionNode]) -> Dict[str, str]:
    path_map = {}

    def traverse(nodes: List[SectionNode], parent_path: str):
        for node in nodes:
            curr_path = f"{parent_path} > {node.title}" if parent_path else node.title
            path_map[node.section_id] = curr_path
            if node.children:
                traverse(node.children, curr_path)

    traverse(outline, "")
    return path_map


class DocumentContext:
    def __init__(self, norm_doc: NormalizedDocumentContext):
        self.norm_doc = norm_doc
        self.profile = compute_document_profile(norm_doc.doc)
        self.section_paths = build_section_path_map(norm_doc.doc.outline)


def run_stage2_context(norm_doc: NormalizedDocumentContext) -> DocumentContext:
    return DocumentContext(norm_doc)
