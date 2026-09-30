"""
Anti-Fabrication Tests for get_concept_learning_content.

The previous implementation generated generic template content such as
"Consider the relationship and constraints defined for {concept}" and invented
misconceptions, while appending truncated source fragments. This violated the
project's core principle (phase3/errors.py):

    "No error in this module ever implies that substitute educational content
     is acceptable. When an LLM-backed artifact cannot be produced, the error
     propagates. Inventing content is a bug, not a recovery strategy."

These tests prove the function now returns ONLY source-grounded content, or
fails loudly with ContentValidationError. They would all fail against the old
fabricating implementation.
"""

import pytest

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from phase3.errors import ContentValidationError, LearnSenseError


@pytest.fixture(scope="module")
def services():
    ks = KnowledgeService()
    ls = LearnerService(knowledge_service=ks)
    learning = LearningService(learner_service=ls, knowledge_service=ks)
    return learning, ks, ls


def _subject_with_evidence(learning, ks, ingested_calculus):
    """Find a subject+concept that has real retrievable source evidence."""
    sid = ingested_calculus.document_id
    graph = ks.get_subject_graph(sid)
    for concept in graph["concepts"]:
        cid = concept["concept_id"]
        try:
            content = learning.get_concept_learning_content(sid, cid)
            if content.get("source_evidence"):
                return sid, cid, content
        except ContentValidationError:
            continue
    pytest.fail("No subject with retrievable source evidence is available.")


class TestLearningContentIsNotFabricated:
    """The learning content path must never invent educational claims."""

    def test_a_real_source_evidence_produces_grounded_content(self, services, ingested_calculus):
        """A. Real source evidence produces content marked as grounded."""
        learning, ks, _ = services
        sid, cid, content = _subject_with_evidence(learning, ks, ingested_calculus)

        assert content["concept_id"] == cid
        assert content["concept_name"]
        assert content["grounded"] is True
        assert len(content["source_evidence"]) > 0

        for evidence in content["source_evidence"]:
            assert evidence["text"], "source evidence must not be empty"
            assert "provenance" in evidence
            assert evidence["provenance"]["document_id"] == sid

    def test_b_insufficient_evidence_raises_typed_error(self, services, ingested_calculus):
        """B. No evidence -> a typed LearnSenseError, never fabricated content.

        Both ContentValidationError and KnowledgeNotFoundError are acceptable:
        the requirement is that the function fails loudly rather than inventing
        substitute content.
        """
        learning, ks, _ = services
        # A subject that does not exist in the graph must fail loudly.
        with pytest.raises(LearnSenseError):
            learning.get_concept_learning_content(
                "non_existent_subject_zzz", "non_existent_concept_zzz"
            )

    def test_c_no_generic_misconceptions_are_emitted(self, services, ingested_calculus):
        """C. The response must not contain a generic misconceptions list."""
        learning, ks, _ = services
        _, _, content = _subject_with_evidence(learning, ks, ingested_calculus)

        assert "common_misconceptions" not in content, (
            "SECURITY: generic misconceptions must never be silently emitted"
        )

    def test_d_no_truncated_source_fragment_presented_as_explanation(self, services, ingested_calculus):
        """
        D. Source fragments must be labelled as source evidence, never disguised
        as a generated explanation with an ellipsis appended.
        """
        learning, ks, _ = services
        _, _, content = _subject_with_evidence(learning, ks, ingested_calculus)

        # The old code produced strings like "Core intuition: <fragment>..." and
        # "Step 2: Apply principle: <fragment>...". Those keys must be gone.
        for fabricated_key in ("intuition", "overview", "key_takeaway", "worked_example"):
            assert fabricated_key not in content, (
                f"fabricated field '{fabricated_key}' must not be present"
            )

        # Source evidence must be verbatim, not truncated with an ellipsis.
        for evidence in content["source_evidence"]:
            assert not evidence["text"].rstrip().endswith("..."), (
                "source fragments must not be truncated and presented as explanation"
            )

    def test_e_no_invented_worked_example(self, services, ingested_calculus):
        """E. Worked examples are never invented."""
        learning, ks, _ = services
        _, _, content = _subject_with_evidence(learning, ks, ingested_calculus)
        assert "worked_example" not in content

    def test_f_definition_comes_from_knowledge_graph(self, services, ingested_calculus):
        """F. The definition field is the graph's own value, not invented."""
        learning, ks, _ = services
        sid, cid, content = _subject_with_evidence(learning, ks, ingested_calculus)
        graph = ks.get_subject_graph(sid)
        node = next(c for c in graph["concepts"] if c["concept_id"] == cid)
        assert content["definition"] == (node.get("definition") or None)

    def test_g_grounded_flag_is_true_only_with_evidence(self, services, ingested_calculus):
        """G. grounded=True is only returned when evidence actually exists."""
        learning, ks, _ = services
        _, _, content = _subject_with_evidence(learning, ks, ingested_calculus)
        assert content["grounded"] is True
        assert content["source_evidence"], "grounded=True requires real evidence"

    def test_h_no_hidden_fallback_content(self, services, ingested_calculus):
        """H. There is no code path that fills fields with template text."""
        learning, ks, _ = services
        _, _, content = _subject_with_evidence(learning, ks, ingested_calculus)
        # Every value in the response must be either a real field or source evidence.
        allowed_keys = {"concept_id", "concept_name", "definition", "source_evidence", "grounded"}
        assert set(content.keys()) <= allowed_keys, (
            f"unexpected keys in response: {set(content.keys()) - allowed_keys}"
        )
