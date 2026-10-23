"""
Content mapping: rule table, decision thresholds and the Phase 1 boundary.

The mapper is deterministic and local.  Two properties are load-bearing and get
explicit negative tests here:

* an unmatched term is *proposed for review*, never silently created as a
  canonical concept, and
* ``passages_from_structured_document`` only *reads* the Phase 1
  ``StructuredDocument``; it is a boundary, not a second parser.
"""

from __future__ import annotations

import pathlib

import pytest

from curriculum.mapping import (
    ACCEPTED_MIN_STRENGTH,
    DECISIVENESS_MARGIN,
    UNCERTAIN_MIN_STRENGTH,
    ConceptMatch,
    ContentMapper,
    ExtractedConceptCandidate,
    MappingContext,
    MappingStatus,
    MatchKind,
    Passage,
    passages_from_structured_document,
    score_surface_against_concept,
)
from curriculum.models import CanonicalConcept, CurriculumGraph, Subject

HUMAN = "curriculum_review"


def build_graph() -> tuple[CurriculumGraph, dict]:
    graph = CurriculumGraph(curriculum_id="t", syllabus_version="v1")
    displacement = CanonicalConcept.create(
        "Displacement",
        Subject.PHYSICS,
        stable_key="physics/displacement",
        curriculum_id="t",
        aliases=["change in position"],
    )
    distance = CanonicalConcept.create(
        "Distance",
        Subject.PHYSICS,
        stable_key="physics/distance",
        curriculum_id="t",
        aliases=["path length"],
    )
    equilibrium = CanonicalConcept.create(
        "Chemical Equilibrium",
        Subject.CHEMISTRY,
        stable_key="chemistry/equilibrium",
        curriculum_id="t",
    )
    for concept in (displacement, distance, equilibrium):
        graph.add_concept(concept)
    return graph, {"displacement": displacement, "distance": distance, "equilibrium": equilibrium}


def passage(text: str, passage_id: str = "p1") -> Passage:
    return Passage(passage_id=passage_id, source_id="doc1", text=text, locator="p.1")


def synthetic_match(concept_id: str, strength: float) -> ConceptMatch:
    return ConceptMatch(
        concept_id=concept_id,
        canonical_name=concept_id,
        matched_surface=concept_id,
        match_kind=MatchKind.CANONICAL_NAME,
        match_strength=strength,
    )


class TestDecisionRuleTable:
    def test_documented_thresholds_are_pinned(self):
        assert ACCEPTED_MIN_STRENGTH == 0.90
        assert UNCERTAIN_MIN_STRENGTH == 0.60
        assert DECISIVENESS_MARGIN == 0.05

    def test_no_matches_is_unmapped(self):
        status, reason = ContentMapper.decide([])
        assert status is MappingStatus.UNMAPPED
        assert "no canonical name or alias matched" in reason

    def test_below_the_floor_is_unmapped(self):
        status, reason = ContentMapper.decide([synthetic_match("a", 0.55)])
        assert status is MappingStatus.UNMAPPED
        assert "below" in reason

    def test_accepted_requires_margin_over_the_runner_up(self):
        status, _ = ContentMapper.decide(
            [synthetic_match("a", 0.92), synthetic_match("b", 0.80)]
        )
        assert status is MappingStatus.ACCEPTED

    def test_small_margin_is_uncertain_even_at_high_strength(self):
        status, reason = ContentMapper.decide(
            [synthetic_match("a", 0.92), synthetic_match("b", 0.90)]
        )
        assert status is MappingStatus.UNCERTAIN
        assert "plausible concepts" in reason

    def test_exact_tie_is_uncertain(self):
        status, _ = ContentMapper.decide(
            [synthetic_match("a", 1.0), synthetic_match("b", 1.0)]
        )
        assert status is MappingStatus.UNCERTAIN

    def test_confident_but_sub_threshold_is_uncertain(self):
        status, reason = ContentMapper.decide([synthetic_match("a", 0.75)])
        assert status is MappingStatus.UNCERTAIN
        assert "acceptance threshold" in reason


class TestSurfaceScoring:
    def test_canonical_name_beats_alias(self):
        _, nodes = build_graph()
        exact = score_surface_against_concept("Displacement", nodes["displacement"])
        alias = score_surface_against_concept("change in position", nodes["displacement"])
        assert exact is not None and alias is not None
        assert exact.match_kind is MatchKind.CANONICAL_NAME
        assert alias.match_kind is MatchKind.ALIAS
        assert exact.match_strength > alias.match_strength
        assert exact.match_strength >= ACCEPTED_MIN_STRENGTH

    def test_unrelated_surface_scores_nothing(self):
        _, nodes = build_graph()
        assert score_surface_against_concept("Photosynthesis", nodes["equilibrium"]) is None

    def test_scoring_never_exceeds_one(self):
        _, nodes = build_graph()
        match = score_surface_against_concept("Displacement", nodes["displacement"])
        assert match is not None
        assert 0.0 <= match.match_strength <= 1.0


class TestMapperOnPassages:
    def test_definitive_sentence_maps_to_the_named_concept(self):
        graph, nodes = build_graph()
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        result = mapper.map_passages(
            [passage("The car moved five metres. Displacement is the change in position.")]
        )
        candidate = result.candidates[0]
        assert candidate.status is MappingStatus.ACCEPTED
        assert candidate.predicted_concept_id == nodes["displacement"].concept_id

    def test_definition_position_bonus_is_recorded(self):
        graph, _ = build_graph()
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        result = mapper.map_passages([passage("Distance is a scalar quantity.")])
        match = result.candidates[0].matches[0]
        assert "definition_position" in match.applied_rules

    def test_subject_hint_adds_a_bounded_bonus(self):
        graph, nodes = build_graph()
        text = "The change in position is measured along the path travelled."
        without = ContentMapper(graph, MappingContext(document_id="doc1")).map_passages(
            [passage(text)]
        )
        with_hint = ContentMapper(
            graph, MappingContext(document_id="doc1", subject_hint=Subject.PHYSICS)
        ).map_passages([passage(text)])

        def strength_of(result, concept_id):
            for match in result.candidates[0].matches:
                if match.concept_id == concept_id:
                    return match.match_strength
            return None

        bare = strength_of(without, nodes["displacement"].concept_id)
        hinted = strength_of(with_hint, nodes["displacement"].concept_id)
        assert bare is not None and hinted is not None
        assert hinted > bare
        assert hinted - bare <= 0.05  # the bonus is bounded, never decisive alone

    def test_unknown_text_is_unmapped_and_proposes_nothing(self):
        graph, _ = build_graph()
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        result = mapper.map_passages([passage("Photosynthesis converts light into chemical energy.")])
        candidate = result.candidates[0]
        assert candidate.status is MappingStatus.UNMAPPED
        # text passages never mint concepts; only extracted concepts get proposals
        assert candidate.proposed_concept is None

    def test_summary_counts_match_the_candidates(self):
        graph, _ = build_graph()
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        result = mapper.map_passages(
            [
                passage("Displacement is the change in position.", "p1"),
                passage("Photosynthesis converts light into chemical energy.", "p2"),
            ]
        )
        assert result.summary["total"] == 2
        assert result.summary["unmapped"] == 1
        assert result.summary == {
            **result.summary,
            "accepted": result.status_counts()["accepted"],
            "uncertain": result.status_counts()["uncertain"],
            "unmapped": result.status_counts()["unmapped"],
        }


class TestExtractedConceptMapping:
    def test_unmatched_item_is_proposed_not_created(self):
        graph, _ = build_graph()
        mapper = ContentMapper(graph, MappingContext(document_id="doc1", subject_hint=Subject.PHYSICS))
        before = dict(graph.concepts)
        result = mapper.map_extracted_concepts(
            [
                ExtractedConceptCandidate(
                    item_id="ex1",
                    name="Quantum Entanglement",
                    description="Spooky action.",
                    extracted_type="definition",
                )
            ]
        )
        candidate = result.candidates[0]
        assert candidate.status is MappingStatus.UNMAPPED
        assert candidate.proposed_concept is not None
        assert candidate.proposed_concept.name == "Quantum Entanglement"
        assert "proposing a new canonical concept" in candidate.reason
        # the graph is untouched: nothing is added without a teacher decision
        assert graph.concepts == before

    def test_alias_match_suppresses_the_proposal(self):
        graph, nodes = build_graph()
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        result = mapper.map_extracted_concepts(
            [ExtractedConceptCandidate(item_id="ex2", name="Change In Position")]
        )
        candidate = result.candidates[0]
        assert candidate.status is MappingStatus.ACCEPTED
        assert candidate.predicted_concept_id == nodes["displacement"].concept_id
        assert candidate.proposed_concept is None

    def test_aliases_cannot_split_one_concept_into_several(self):
        graph, _ = build_graph()
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        result = mapper.map_extracted_concepts(
            [
                ExtractedConceptCandidate(
                    item_id="ex3", name="Displacement", aliases=["change in position"]
                )
            ]
        )
        # both surfaces resolve to one concept; the candidate is decisive
        assert len(result.candidates[0].matches) == 1
        assert result.candidates[0].status is MappingStatus.ACCEPTED


class TestDeterminism:
    def test_same_input_same_fingerprint(self):
        graph, _ = build_graph()
        passages = [
            passage("Displacement is the change in position.", "p1"),
            passage("Photosynthesis converts light into chemical energy.", "p2"),
        ]
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        first = mapper.map_passages(passages)
        second = ContentMapper(graph, MappingContext(document_id="doc1")).map_passages(passages)
        assert first.fingerprint == second.fingerprint
        assert first.predicted_pairs() == second.predicted_pairs()
        assert ContentMapper.fingerprint(first) == first.fingerprint

    def test_passage_order_does_not_change_per_item_predictions(self):
        graph, _ = build_graph()
        passages = [
            passage("Displacement is the change in position.", "p1"),
            passage("Chemical Equilibrium is a dynamic balance.", "p2"),
        ]
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        forward = mapper.map_passages(passages)
        backward = mapper.map_passages(list(reversed(passages)))
        assert sorted(forward.predicted_pairs()) == sorted(backward.predicted_pairs())


class TestPhase1Boundary:
    def document_dict(self) -> dict:
        return {
            "document_id": "doc_phase1",
            "source": {"sha256": "0" * 64, "filename": "notes.pdf", "size_bytes": 10},
            "metadata": {
                "page_count": 1,
                "title": {"value": "Class Notes"},
                "processing_status": "completed",
            },
            "status": "completed",
            "outline": [
                {"section_id": "s1", "title": "Kinematics", "level": 1, "page_start": 0}
            ],
            "pages": [
                {
                    "page_index": 0,
                    "page_label": "1",
                    "type": "content",
                    "width": 100,
                    "height": 200,
                    "blocks": [
                        {
                            "block_id": "b1",
                            "type": "heading",
                            "role": "section_title",
                            "extraction_method": "native",
                            "bbox": [0, 0, 100, 20],
                            "reading_order": 0,
                            "section_id": "s1",
                            "content": {"text": "Kinematics", "text_raw": "Kinematics"},
                        },
                        {
                            "block_id": "b2",
                            "type": "paragraph",
                            "role": "body",
                            "extraction_method": "native",
                            "bbox": [0, 20, 100, 80],
                            "reading_order": 1,
                            "section_id": "s1",
                            "content": {
                                "text": "Displacement is the change in position.",
                                "text_raw": "Displacement is the change in position.",
                            },
                        },
                        {
                            "block_id": "b3",
                            "type": "figure",
                            "role": "body",
                            "extraction_method": "image_preserved",
                            "bbox": [0, 80, 100, 120],
                            "reading_order": 2,
                            "section_id": "s1",
                            "content": {"text": "a diagram", "text_raw": "a diagram"},
                        },
                        {
                            "block_id": "b4",
                            "type": "paragraph",
                            "role": "footer",
                            "extraction_method": "native",
                            "bbox": [0, 90, 100, 100],
                            "reading_order": 3,
                            "section_id": "s1",
                            "content": {"text": "confidential draft", "text_raw": "confidential"},
                        },
                    ],
                }
            ],
        }

    def test_reader_walks_the_document_in_reading_order(self):
        passages = passages_from_structured_document(self.document_dict())
        assert len(passages) == 1
        only = passages[0]
        assert only.text == "Kinematics Displacement is the change in position."
        assert only.section_title == "Kinematics"
        assert only.block_ids == ["b1", "b2"]  # image and footer never enter

    def test_reader_preserves_the_document_id(self):
        passages = passages_from_structured_document(self.document_dict())
        assert passages[0].source_id == "doc_phase1"

    def test_an_object_without_pages_is_rejected(self):
        class NotADocument:
            pass

        with pytest.raises(ValueError, match="pages"):
            passages_from_structured_document(NotADocument())

    def test_an_empty_but_valid_document_yields_no_passages(self):
        document = self.document_dict()
        document["pages"] = []
        assert passages_from_structured_document(document) == []

    def test_a_malformed_dict_is_rejected_loudly(self):
        with pytest.raises(ValueError, match="StructuredDocument"):
            passages_from_structured_document({"document_id": "x", "pages": "not-a-list"})


class TestNoExternalModelDependency:
    def test_curriculum_package_imports_no_llm_or_network_stack(self):
        package = pathlib.Path(__file__).resolve().parents[3] / "curriculum"
        forbidden = ("import llm", "from llm", "groq", "openai", "anthropic", "httpx", "requests")
        offenders = []
        for path in sorted(package.glob("*.py")):
            source = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                if token in source:
                    offenders.append(f"{path.name}: {token}")
        assert offenders == []
