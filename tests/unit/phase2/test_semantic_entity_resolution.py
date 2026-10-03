"""
Unit and evaluation tests for Semantic Entity Resolution in Phase 2.
Verifies Section 15 of TAPROOT:
- True aliases: Newton's Second Law / Newton's 2nd Law / Newton II law
- Semantic equivalents: rate of change of velocity <-> acceleration
- Strict non-merging of near-misses: Speed vs Velocity, Newton's 1st vs Newton's 2nd, Mass vs Weight
- Non-merging of unrelated concepts
- Verification of MergeRecord details
- Measures precision, recall, and false merge rate (FMR = 0.0)
"""

import pytest
from phase2.models import ConceptMention, TextSpan
from phase2.pipeline.semantic_entity_resolver import SemanticEntityResolver


class TestSemanticEntityResolution:
    def test_syntactic_and_ordinal_aliases_merged(self):
        resolver = SemanticEntityResolver()
        mentions = [
            ConceptMention(
                mention_id="m1",
                concept_id="c1",
                block_id="b1",
                span=TextSpan(start=0, end=18),
                surface_form="Newton's Second Law",
            ),
            ConceptMention(
                mention_id="m2",
                concept_id="c2",
                block_id="b2",
                span=TextSpan(start=0, end=15),
                surface_form="Newton's 2nd Law",
            ),
            ConceptMention(
                mention_id="m3",
                concept_id="c3",
                block_id="b3",
                span=TextSpan(start=0, end=13),
                surface_form="Newton II law",
            ),
        ]

        clusters, canonical_names, merge_records = resolver.resolve_mentions(mentions)

        # All 3 mentions should resolve into a single unified cluster
        assert len(clusters) == 1
        cluster_key = list(clusters.keys())[0]
        assert len(clusters[cluster_key]) == 3
        # Canonical name should be one of the clean authoritative forms
        assert "Newton" in canonical_names[cluster_key]
        assert "Law" in canonical_names[cluster_key]

    def test_domain_semantic_equivalences_merged(self):
        resolver = SemanticEntityResolver()
        mentions = [
            ConceptMention(
                mention_id="m1",
                concept_id="c1",
                block_id="b1",
                span=TextSpan(start=0, end=12),
                surface_form="Acceleration",
            ),
            ConceptMention(
                mention_id="m2",
                concept_id="c2",
                block_id="b2",
                span=TextSpan(start=0, end=27),
                surface_form="rate of change of velocity",
            ),
        ]

        clusters, canonical_names, merge_records = resolver.resolve_mentions(mentions)

        # Should merge into the Acceleration cluster
        assert len(clusters) == 1
        cluster_key = list(clusters.keys())[0]
        assert len(clusters[cluster_key]) == 2
        assert "Acceleration" in canonical_names[cluster_key]

        # Verify structured MergeRecord
        assert len(merge_records) >= 1
        rec = merge_records[0]
        assert rec.signals["reason"] == "SEMANTIC_DOMAIN_EQUIVALENCE"
        assert rec.signals["verification_status"] == "VERIFIED"
        assert rec.score >= 0.85

    def test_near_misses_are_strictly_not_merged(self):
        resolver = SemanticEntityResolver()

        near_miss_pairs = [
            ("Newton's First Law", "Newton's Second Law"),
            ("Speed", "Velocity"),
            ("Mass", "Weight"),
            ("Distance", "Displacement"),
            ("Linear Momentum", "Angular Momentum"),
            ("Potential Energy", "Kinetic Energy"),
        ]

        for term_a, term_b in near_miss_pairs:
            mentions = [
                ConceptMention(mention_id="m1", concept_id="c1", block_id="b1", span=TextSpan(start=0, end=len(term_a)), surface_form=term_a),
                ConceptMention(mention_id="m2", concept_id="c2", block_id="b2", span=TextSpan(start=0, end=len(term_b)), surface_form=term_b),
            ]
            clusters, canonical_names, merge_records = resolver.resolve_mentions(mentions)

            # Must NEVER merge distinct near-miss physical concepts!
            assert len(clusters) == 2, f"FAILED: Near-miss pair ('{term_a}', '{term_b}') was incorrectly merged!"
            assert len(merge_records) == 0, f"FAILED: Generated merge record for near-miss ('{term_a}', '{term_b}')"

    def test_unrelated_concepts_are_not_merged(self):
        resolver = SemanticEntityResolver()
        mentions = [
            ConceptMention(mention_id="m1", concept_id="c1", block_id="b1", span=TextSpan(start=0, end=14), surface_form="Photosynthesis"),
            ConceptMention(mention_id="m2", concept_id="c2", block_id="b2", span=TextSpan(start=0, end=10), surface_form="Derivative"),
        ]
        clusters, canonical_names, merge_records = resolver.resolve_mentions(mentions)
        assert len(clusters) == 2
        assert len(merge_records) == 0

    def test_semantic_evaluation_dataset_metrics(self):
        """
        Evaluation benchmark evaluating:
        - precision
        - recall
        - false merge rate (FMR)
        over an expert-labelled benchmark set.
        """
        resolver = SemanticEntityResolver()

        # Expert labelled pairs: (term1, term2, should_merge: bool)
        test_dataset = [
            # True aliases (should merge)
            ("Newton's Second Law", "Newton's 2nd Law", True),
            ("Newton's Second Law", "Newton II law", True),
            ("Gauss's Law", "Gauss flux theorem", True),
            ("First law of thermodynamics", "Conservation of energy", True),
            ("Acceleration", "Rate of change of velocity", True),
            ("Velocity", "Rate of change of displacement", True),

            # Near-misses & distinct concepts (must NOT merge)
            ("Newton's First Law", "Newton's Second Law", False),
            ("Newton's Second Law", "Newton's Third Law", False),
            ("Speed", "Velocity", False),
            ("Mass", "Weight", False),
            ("Distance", "Displacement", False),
            ("Linear Momentum", "Angular Momentum", False),
            ("Heat", "Temperature", False),
            ("Photosynthesis", "Cellular Respiration", False),
            ("Calculus", "Linear Algebra", False),
        ]

        true_positives = 0
        false_positives = 0
        true_negatives = 0
        false_negatives = 0

        for term_a, term_b, expected_merge in test_dataset:
            mentions = [
                ConceptMention(mention_id="m1", concept_id="c1", block_id="b1", span=TextSpan(start=0, end=len(term_a)), surface_form=term_a),
                ConceptMention(mention_id="m2", concept_id="c2", block_id="b2", span=TextSpan(start=0, end=len(term_b)), surface_form=term_b),
            ]
            clusters, _, _ = resolver.resolve_mentions(mentions)
            actual_merge = (len(clusters) == 1)

            if expected_merge and actual_merge:
                true_positives += 1
            elif expected_merge and not actual_merge:
                false_negatives += 1
            elif not expected_merge and actual_merge:
                false_positives += 1
            else:
                true_negatives += 1

        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 1.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 1.0
        false_merge_rate = false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) > 0 else 0.0

        assert precision == 1.0, f"Precision was {precision:.2f}, expected 1.0 (no false merges)"
        assert recall >= 0.85, f"Recall was {recall:.2f}, expected >= 0.85"
        assert false_merge_rate == 0.0, f"False Merge Rate was {false_merge_rate:.2f}, expected strictly 0.0"
