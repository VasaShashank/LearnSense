"""
Shared pytest fixtures.

The most important fixture here ingests a **real** document. LearnSense refuses to
generate content that is not grounded in a learner's own material, so any test that
exercises the API end to end needs a document whose passages actually exist. Hand-built
``LearningContext`` objects with concepts but no evidence cannot produce a question, so
these fixtures use the real Phase 1 -> Phase 2 -> Phase 3 pipeline instead.
"""

from __future__ import annotations

import shutil
from typing import Dict, List

import pytest

CALCULUS_TEXT = (
    "Limits\n"
    "A limit describes the value a function approaches as its input becomes arbitrarily "
    "close to a given point.\n"
    "Derivatives\n"
    "The derivative of a function at a point is the limit of the difference quotient as "
    "the increment approaches zero.\n"
    "Chain Rule\n"
    "The chain rule states that the derivative of a composition of functions is the "
    "product of the derivative of the inner function and the derivative of the outer "
    "function.\n"
    "Definite Integrals\n"
    "A definite integral accumulates the signed area between a curve and the axis over a "
    "closed interval.\n"
)


def _pdf_bytes(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), text, fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


class IngestedDocument:
    """A really-ingested document plus the concept IDs the pipeline actually found."""

    def __init__(self, document_id: str, context, structured_document_path=None) -> None:
        self.document_id = document_id
        self.context = context
        self.concept_ids: List[str] = list(context.concepts.keys())
        self.concept_names: List[str] = [c.canonical_name for c in context.concepts.values()]

    def id_for(self, name_fragment: str) -> str:
        """
        Concept ID whose canonical name contains ``name_fragment`` (case-insensitive).

        Lets a test ask for "Limits" without hard-coding the extractor's generated ID.
        """
        needle = name_fragment.lower()
        for concept_id, concept in self.context.concepts.items():
            if needle in concept.canonical_name.lower():
                return concept_id
        raise AssertionError(
            f"No concept matching {name_fragment!r}; available: {self.concept_names}"
        )

    def ids_for(self, *fragments: str) -> List[str]:
        return [self.id_for(f) for f in fragments]


@pytest.fixture(scope="session")
def ingested_calculus() -> IngestedDocument:
    """
    Ingest a real calculus PDF once per test session.

    The document is removed afterwards so a test run does not leave learner material in
    the repository's ``storage/`` tree.
    """
    from backend.services.knowledge_build_service import KnowledgeBuildService
    from storage.repositories import LearningContextRepository

    document_id = "test_fixture_calculus"
    service = KnowledgeBuildService()
    try:
        service.build(document_id, _pdf_bytes(CALCULUS_TEXT), "fixture_calculus.pdf")
    except Exception as exc:  # pragma: no cover - surfaces a real pipeline failure
        pytest.fail(f"Could not ingest the fixture document: {exc}")

    context = LearningContextRepository().load_context(document_id)
    assert context is not None, "fixture document produced no learning context"
    assert context.concepts, "fixture document produced no concepts"
    assert context.evidence, "fixture document produced no evidence to ground questions in"

    yield IngestedDocument(document_id, context)

    _purge(document_id)


def _purge(document_id: str) -> None:
    """Delete every artefact written for a fixture document."""
    from pathlib import Path

    for relative in (
        f"storage/documents/{document_id}",
        f"storage/learning_contexts/{document_id}.json",
        f"storage/question_banks/{document_id}.json",
        f"storage/question_banks/{document_id}",
        f"storage/sessions/{document_id}.json",
    ):
        path = Path(relative)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            try:
                path.unlink()
            except OSError:
                pass
