"""
Evaluation metric arithmetic (Person 2).

Two properties are load-bearing and get explicit tests:

* every metric states its denominator or an ``undefined_reason`` -- a zero
  denominator reports ``None``, never a number that was not measured, and
* extraction/coverage failures stay visible separately from mapping failures,
  so end-to-end recall is never flattered and the mapping-only view never
  hides a miss by quietly dropping it.

The pilot fixture doubles as seed spec and gold reference; its
``expected_counts`` are hand-enumerated, so the tests assert every ``ok`` flag
rather than regenerating expectations from whatever the code produced.
"""

from __future__ import annotations

import copy

import pytest

from curriculum.mapping import ContentMapper, MappingContext, Passage
from curriculum.models import (
    CanonicalConcept,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    Subject,
)
from evaluation.curriculum_eval import (
    evaluate_alias_normalization,
    evaluate_concept_mapping,
    evaluate_curriculum,
    evaluate_prerequisite_direction,
    evaluate_relationships,
    precision_recall_f1,
)

ACCEPTED = "accepted"
PREREQ = "prerequisite_of"


def tiny_graph() -> tuple[CurriculumGraph, dict]:
    graph = CurriculumGraph(curriculum_id="t", syllabus_version="v1")
    nodes = {
        "distance": CanonicalConcept.create(
            "Distance",
            Subject.PHYSICS,
            stable_key="k/distance",
            curriculum_id="t",
            aliases=["path length"],
        ),
        "displacement": CanonicalConcept.create(
            "Displacement",
            Subject.PHYSICS,
            stable_key="k/displacement",
            curriculum_id="t",
            aliases=["change in position"],
        ),
        "velocity": CanonicalConcept.create(
            "Velocity", Subject.PHYSICS, stable_key="k/velocity", curriculum_id="t"
        ),
    }
    for node in nodes.values():
        graph.add_concept(node)
    return graph, nodes


def names_of(graph: CurriculumGraph) -> dict:
    return {
        concept_id: [concept.name] + list(concept.aliases)
        for concept_id, concept in graph.concepts.items()
    }


def mapped_run(graph: CurriculumGraph, texts: dict, document_id: str = "run1"):
    """One deterministic mapping run covering every supplied item id."""
    mapper = ContentMapper(graph, MappingContext(document_id=document_id))
    return mapper.map_passages(
        [
            Passage(
                passage_id=item_id,
                source_id=document_id,
                text=text,
                locator=f"item:{item_id}",
            )
            for item_id, text in sorted(texts.items())
        ]
    )


def pilot_run(graph: CurriculumGraph, raw: dict):
    return mapped_run(graph, {item["item_id"]: item["text"] for item in raw["items"]},
                      document_id="pilot_eval_run")


class TestPrfArithmetic:
    def test_documented_values_and_denominators(self):
        metrics = precision_recall_f1(4, 1, 0)
        assert metrics["precision"] == 0.8
        assert metrics["recall"] == 1.0
        assert metrics["f1"] == 0.8889
        assert metrics["precision_denominator"] == 5
        assert metrics["recall_denominator"] == 4

    def test_precision_is_none_when_there_were_no_predictions(self):
        metrics = precision_recall_f1(0, 0, 3)
        assert metrics["precision"] is None
        assert metrics["recall"] == 0.0
        assert metrics["f1"] is None  # one side undefined -> no f1 at all
        assert "precision" in metrics["undefined_reason"]

    def test_recall_is_none_when_there_was_no_gold(self):
        metrics = precision_recall_f1(0, 2, 0)
        assert metrics["precision"] == 0.0
        assert metrics["recall"] is None
        assert metrics["f1"] is None
        assert "gold" in metrics["undefined_reason"]

    def test_fully_empty_counts_are_none_not_zero(self):
        metrics = precision_recall_f1(0, 0, 0)
        assert metrics["precision"] is None
        assert metrics["recall"] is None
        assert metrics["f1"] is None
        assert metrics["precision_denominator"] == 0
        assert metrics["recall_denominator"] == 0

    def test_measured_zero_stays_a_number(self):
        metrics = precision_recall_f1(0, 3, 2)
        assert metrics["precision"] == 0.0
        assert metrics["recall"] == 0.0
        assert metrics["f1"] == 0.0
        assert "undefined_reason" not in metrics


class TestConceptMappingSplits:
    def test_item_missing_from_the_run_is_an_end_to_end_miss(self):
        graph, nodes = tiny_graph()
        run = mapped_run(graph, {"i1": "Displacement is the change in position."})
        gold = {
            "i1": [nodes["displacement"].concept_id],
            "i2": [nodes["distance"].concept_id],
        }
        result = evaluate_concept_mapping(
            run,
            gold,
            source_texts={
                "i1": "Displacement is the change in position.",
                "i2": "Nothing in this sentence names any physical quantity.",
            },
            canonical_names=names_of(graph),
            split="pilot",
        )
        assert result["tp"] == 1
        assert result["fp"] == 0
        assert result["fn"] == 1
        assert result["items_missing_from_run"] == ["i2"]
        assert result["precision"] == 1.0
        assert result["recall"] == 0.5
        assert result["precision_denominator"] == 1
        assert result["recall_denominator"] == 2
        # Only annotated items the run actually produced are scored.
        assert result["items_evaluated"] == 1
        assert result["exact_match_accuracy"] == 1.0
        assert result["split"] == "pilot"

    def test_in_run_miss_without_source_coverage_leaves_the_mapping_view_empty(self):
        graph, nodes = tiny_graph()
        text = "Nothing here names any physical quantity."
        run = mapped_run(graph, {"i1": text})
        result = evaluate_concept_mapping(
            run,
            {"i1": [nodes["distance"].concept_id]},
            source_texts={"i1": text},
            canonical_names=names_of(graph),
        )
        assert result["tp"] == 0
        assert result["fp"] == 0
        assert result["fn"] == 1
        assert result["recall"] == 0.0  # end-to-end keeps the miss
        # extraction failure, kept visible and excluded from the mapping-only view
        assert result["source_coverage_failures"] == ["i1"]
        assert result["answerable_misses"] == []
        assert result["recall_answerable"] is None
        assert result["recall_answerable_denominator"] == 0

    def test_explicit_answerability_annotation_beats_the_substring_heuristic(self):
        graph, nodes = tiny_graph()
        text = "Nothing here names any physical quantity."
        run = mapped_run(graph, {"i1": text})
        gold = {"i1": [nodes["distance"].concept_id]}

        heuristic = evaluate_concept_mapping(
            run, gold, source_texts={"i1": text}, canonical_names=names_of(graph)
        )
        asserted = evaluate_concept_mapping(
            run,
            gold,
            source_texts={"i1": text},
            canonical_names=names_of(graph),
            source_mentions_gold={"i1": True},
        )
        # the reviewer says the term was present: the item becomes an answerable miss
        assert heuristic["recall_answerable"] is None
        assert asserted["recall_answerable"] == 0.0
        assert asserted["answerable_misses"] == ["i1"]
        assert asserted["source_coverage_failures"] == []
        assert asserted["recall"] == 0.0 == heuristic["recall"]

    def test_correct_abstention_scores_full_marks(self):
        graph, _ = tiny_graph()
        run = mapped_run(graph, {"i1": "The school closed early for the festival holiday."})
        result = evaluate_concept_mapping(run, {"i1": []})
        assert result["tp"] == 0
        assert result["fp"] == 0
        assert result["fn"] == 0
        assert result["correct_abstentions"] == ["i1"]
        assert result["exact_match_accuracy"] == 1.0
        assert result["abstention_rate"] == 1.0
        assert result["status_counts"] == {"unmapped": 1}
        assert result["precision"] is None  # nothing measured, not a measured zero

    def test_a_wrong_prediction_is_never_counted_as_an_abstention(self):
        graph, nodes = tiny_graph()
        run = mapped_run(graph, {"i1": "Distance is a scalar quantity."})
        result = evaluate_concept_mapping(run, {"i1": []})
        assert result["wrong_items"] == ["i1"]
        assert result["correct_abstentions"] == []
        assert result["fp"] == 1
        assert result["precision"] == 0.0
        assert result["exact_match_accuracy"] == 0.0
        assert result["abstention_rate"] == 0.0
        assert result["status_counts"] == {"accepted": 1}
        assert result["predicted_positive_items"] == 1
        _ = nodes

    def test_status_counts_and_denominators_ignore_unannotated_run_items(self):
        graph, _ = tiny_graph()
        run = mapped_run(
            graph,
            {
                "i1": "A different sentence with nothing to annotate.",
                "i2": "Displacement is the change in position.",
            },
        )
        result = evaluate_concept_mapping(run, {"i1": []})
        # i2 maps to a concept but has no gold entry: reported, never silently scored
        assert result["unannotated_items"] == ["i2"]
        assert result["items_evaluated"] == 1
        assert result["abstention_denominator"] == 1
        assert result["fp"] == 0  # an unannotated wrong guess cannot become fp
        assert result["predicted_positive_items"] == 0
        assert result["status_counts"] == {"unmapped": 1}

    def test_no_gold_at_all_is_undefined_not_zero(self):
        graph, _ = tiny_graph()
        run = mapped_run(graph, {"i1": "Displacement is the change in position."})
        result = evaluate_concept_mapping(run, {})
        assert result["items_evaluated"] == 0
        assert result["abstention_rate"] is None
        assert result["exact_match_accuracy"] is None
        assert result["precision"] is None
        assert result["recall"] is None
        assert result["f1"] is None
        assert result["unannotated_items"] == ["i1"]
        assert "undefined_reason" in result


class TestRelationshipExtraction:
    def test_edge_metrics_resolve_stable_keys_on_the_gold_side(self):
        gold = [("k/a", PREREQ, "k/b"), ("k/b", PREREQ, "k/c")]
        predicted = [("cc_a", PREREQ, "cc_b"), ("cc_x", "part_of", "cc_y")]
        key_to_id = {"k/a": "cc_a", "k/b": "cc_b", "k/c": "cc_c"}
        result = evaluate_relationships(predicted, gold, key_to_id=key_to_id)
        assert result["tp"] == 1
        assert result["fp"] == 1
        assert result["fn"] == 1
        assert result["false_positive_edges"] == [("cc_x", "part_of", "cc_y")]
        assert result["false_negative_edges"] == [("cc_b", PREREQ, "cc_c")]
        assert result["per_type"][PREREQ]["tp"] == 1
        assert result["per_type"]["part_of"]["fp"] == 1
        assert result["definitions"]  # every number ships with its meaning

    def test_graph_relationships_evaluate_cleanly_against_their_gold(self):
        graph, nodes = tiny_graph()
        relationship = ConceptRelationship.create(
            nodes["distance"].concept_id,
            PREREQ,
            nodes["displacement"].concept_id,
            curriculum_id="t",
            status="accepted",
            extraction_method="curriculum_review",
        )
        graph.add_relationship(relationship)
        nodes["displacement"].add_prerequisite(nodes["distance"].concept_id)
        key_to_id = {c.stable_key: c.concept_id for c in graph.concepts.values()}

        result = evaluate_relationships(
            graph.relationships.values(),
            [("k/distance", PREREQ, "k/displacement")],
            key_to_id=key_to_id,
        )
        assert result["tp"] == 1
        assert result["fp"] == 0
        assert result["fn"] == 0
        assert result["precision"] == 1.0

    def test_empty_on_both_sides_reports_none(self):
        result = evaluate_relationships([], [])
        assert result["tp"] == 0 and result["fp"] == 0 and result["fn"] == 0
        assert result["precision"] is None
        assert result["recall"] is None
        assert result["per_type"] == {}


class TestPrerequisiteDirection:
    def test_a_reversed_edge_is_a_direction_error_not_a_match(self):
        gold = [("k/a", PREREQ, "k/b")]
        predicted = [("cc_b", PREREQ, "cc_a")]
        key_to_id = {"k/a": "cc_a", "k/b": "cc_b"}
        result = evaluate_prerequisite_direction(predicted, gold, key_to_id=key_to_id)
        assert result["correct_orientation"] == 0
        assert result["reversed_orientation"] == 1
        assert result["reversed_examples"] == [{"source": "cc_b", "target": "cc_a"}]
        assert result["direction_accuracy"] == 0.0
        assert result["direction_accuracy_denominator"] == 1
        # the reversed edge is also a wrong predicted edge, with no undefined escape
        assert result["edge_precision"] is None  # tp=0 fp=0: nothing to divide
        assert result["edge_recall"] == 0.0

    def test_both_orientations_share_a_stated_denominator(self):
        gold = [("k/a", PREREQ, "k/b")]
        predicted = [("cc_a", PREREQ, "cc_b"), ("cc_b", PREREQ, "cc_a")]
        key_to_id = {"k/a": "cc_a", "k/b": "cc_b"}
        result = evaluate_prerequisite_direction(predicted, gold, key_to_id=key_to_id)
        assert result["correct_orientation"] == 1
        assert result["reversed_orientation"] == 1
        assert result["direction_accuracy"] == 0.5
        assert result["direction_accuracy_denominator"] == 2

    def test_unrecognised_pairs_make_the_accuracy_undefined(self):
        gold = [("k/a", PREREQ, "k/b")]
        predicted = [("cc_c", PREREQ, "cc_d")]
        key_to_id = {"k/a": "cc_a", "k/b": "cc_b"}
        result = evaluate_prerequisite_direction(predicted, gold, key_to_id=key_to_id)
        assert result["direction_accuracy"] is None
        assert result["undefined_reason"] == "no prerequisite pairs were recognised"
        assert result["edge_precision"] == 0.0
        assert result["edge_recall"] == 0.0

    def test_non_prerequisite_types_are_out_of_scope_for_direction(self):
        gold = [("k/a", "part_of", "k/b")]
        predicted = [("cc_a", "part_of", "cc_b")]
        key_to_id = {"k/a": "cc_a", "k/b": "cc_b"}
        direction = evaluate_prerequisite_direction(predicted, gold, key_to_id=key_to_id)
        assert direction["undefined_reason"] == "no prerequisite pairs were recognised"
        # ...while the extraction metric still scores the edge itself
        extraction = evaluate_relationships(predicted, gold, key_to_id=key_to_id)
        assert extraction["tp"] == 1


class TestAliasNormalization:
    def test_group_resolving_to_one_concept_is_merged(self):
        graph, _ = tiny_graph()
        result = evaluate_alias_normalization(
            graph.concepts.values(),
            [["Distance", "path length"], ["Displacement", "change in position"]],
            split="pilot",
        )
        assert result["merged_correctly"] == 2
        assert result["split_concepts"] == 0
        assert result["merge_accuracy"] == 1.0
        assert result["merge_accuracy_denominator"] == 2
        assert result["spurious_duplicate_rate"] == 0.0

    def test_group_resolving_to_two_concepts_is_a_split(self):
        graph, _ = tiny_graph()
        result = evaluate_alias_normalization(graph.concepts.values(), [["Distance", "Velocity"]])
        assert result["merged_correctly"] == 0
        assert result["split_concepts"] == 1
        detail = result["split_details"][0]
        assert detail["reason"] == "surfaces mapped to different canonical concepts"
        assert detail["resolved_names"] == ["Distance", "Velocity"]

    def test_unknown_surface_is_reported_as_a_failed_group(self):
        graph, _ = tiny_graph()
        result = evaluate_alias_normalization(graph.concepts.values(), [["Phlogiston"]])
        assert result["split_concepts"] == 1
        assert result["split_details"][0]["reason"] == "no canonical match"

    def test_no_gold_groups_is_undefined_not_a_pass(self):
        graph, _ = tiny_graph()
        result = evaluate_alias_normalization(graph.concepts.values(), [])
        assert result["merge_accuracy"] is None
        assert result["undefined_reason"] == "no gold alias groups supplied"

    def test_spurious_duplicates_count_active_concepts_only(self):
        graph, _ = tiny_graph()
        duplicate = CanonicalConcept.create(
            "Distance",
            Subject.PHYSICS,
            stable_key="k/distance-copy",
            curriculum_id="t",
            status=ConceptLifecycleStatus.DEPRECATED,
        )
        concepts = list(graph.concepts.values()) + [duplicate]

        deprecated_view = evaluate_alias_normalization(concepts, [])
        assert deprecated_view["spurious_duplicate_groups"] == 0

        duplicate.status = ConceptLifecycleStatus.ACTIVE
        active_view = evaluate_alias_normalization(concepts, [])
        assert active_view["spurious_duplicate_groups"] == 1
        assert active_view["spurious_duplicate_details"]["physics:distance"] == sorted(
            [graph.concepts[next(
                cid for cid, c in graph.concepts.items() if c.name == "Distance"
            )].concept_id, duplicate.concept_id]
        )


class TestPilotEvaluation:
    """The fixture's hand-enumerated counts, checked exactly as written."""

    @pytest.fixture
    def results(self, pilot_graph, pilot_raw):
        return evaluate_curriculum(pilot_graph, pilot_raw, mapping_runs=[pilot_run(pilot_graph, pilot_raw)])

    def test_all_thirteen_hand_counts_match(self, results):
        checks = results["expected_count_checks"]
        assert len(checks) == 13
        assert [check for check in checks if not check["ok"]] == []

    def test_pilot_split_metrics(self, results):
        assert results["splits"]["pilot"]["item_count"] == 6
        mapping = results["splits"]["pilot"]["concept_mapping"]
        assert (mapping["tp"], mapping["fp"], mapping["fn"]) == (4, 1, 0)
        assert mapping["precision"] == 0.8
        assert mapping["recall"] == 1.0
        assert mapping["f1"] == 0.8889
        assert mapping["exact_match_accuracy"] == 0.8333
        assert mapping["abstention_rate"] == 0.1667
        assert mapping["items_missing_from_run"] == []
        assert mapping["split"] == "pilot"

    def test_held_out_split_separates_coverage_from_mapping(self, results):
        mapping = results["splits"]["held_out"]["concept_mapping"]
        assert (mapping["tp"], mapping["fp"], mapping["fn"]) == (2, 0, 1)
        assert mapping["recall"] == 0.6667
        # the one miss never received the gold term: extraction, not mapping
        assert mapping["source_coverage_failures"] == ["held_out_03"]
        assert mapping["recall_answerable"] == 1.0
        assert mapping["exact_match_accuracy"] == 0.75

    def test_graph_level_metrics(self, results):
        extraction = results["relationship_extraction"]
        assert (extraction["tp"], extraction["fp"], extraction["fn"]) == (8, 0, 0)
        direction = results["prerequisite_direction"]
        assert direction["correct_orientation"] == 7
        assert direction["reversed_orientation"] == 0
        aliases = results["alias_normalization"]
        assert aliases["merged_correctly"] == 9
        assert aliases["split_concepts"] == 0
        assert aliases["spurious_duplicate_rate"] == 0.0

    def test_every_reported_metric_states_its_definition(self, results):
        mapping = results["splits"]["pilot"]["concept_mapping"]
        assert {"precision", "recall", "f1", "exact_match_accuracy", "items_missing_from_run"} <= set(
            mapping["definitions"]
        )
        assert {"precision_denominator", "recall_denominator", "abstention_denominator",
                "exact_match_denominator"} <= set(mapping)
        assert "direction_accuracy" in results["prerequisite_direction"]["definitions"]
        assert results["prerequisite_direction"]["direction_accuracy_denominator"] == 7
        assert "merge_accuracy" in results["alias_normalization"]["definitions"]

    def test_a_wrong_hand_count_is_reported_not_raised(self, pilot_graph, pilot_raw):
        tampered = copy.deepcopy(pilot_raw)
        tampered["expected_counts"]["concept_mapping"]["pilot"]["tp"] = 99
        results = evaluate_curriculum(pilot_graph, tampered, mapping_runs=[pilot_run(pilot_graph, tampered)])
        checks = results["expected_count_checks"]
        failed = [check for check in checks if not check["ok"]]
        assert [check["metric"] for check in failed] == ["concept_mapping.pilot.tp"]
        assert failed[0]["expected"] == 99
        assert failed[0]["computed"] == 4
        # the honest checks around it still pass
        assert len(checks) == 13

    def test_no_mapping_run_is_undefined_not_a_zero(self, pilot_graph, pilot_raw):
        results = evaluate_curriculum(pilot_graph, pilot_raw)
        mapping = results["splits"]["pilot"]["concept_mapping"]
        assert mapping["undefined_reason"] == "no mapping run supplied for this split's items"
        assert "precision" not in mapping
        # graph-level sections do not depend on a run at all
        assert results["relationship_extraction"]["tp"] == 8
