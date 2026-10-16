"""
Unit tests for Notation-Matched Video and External Resource Intelligence (§9).
"""

import pytest
from phase3.resources.models import (
    ResourceRecord,
    TranscriptSegment,
    FormulaVariant,
    NotationVariant,
)
from phase3.resources.notation_matcher import NotationMatcher
from phase3.resources.recommender import ResourceRecommender
from backend.services.resource_service import ResourceService


def test_notation_matcher_symbol_normalization():
    matcher = NotationMatcher()
    assert matcher.normalize_symbol("u", domain="kinematics") == "initial_velocity"
    assert matcher.normalize_symbol("v_0", domain="kinematics") == "initial_velocity"
    assert matcher.normalize_symbol("v0", domain="kinematics") == "initial_velocity"
    assert matcher.normalize_symbol("v", domain="kinematics") == "final_velocity"
    assert matcher.normalize_symbol("a", domain="kinematics") == "acceleration"
    assert matcher.normalize_symbol("F", domain="mechanics") == "force"
    assert matcher.normalize_symbol("\\Sigma F", domain="mechanics") == "net_force"


def test_notation_matcher_formula_equivalence_kinematics():
    matcher = NotationMatcher()
    # British/Indian convention vs US convention
    f_source = "v = u + at"
    f_resource = "v = v_0 + a*\\Delta t"

    is_equiv, score, expl = matcher.are_formulas_equivalent(f_source, f_resource, domain="kinematics")
    assert is_equiv is True
    assert score >= 0.85
    assert "v_0" in expl or "initial velocity" in expl or "Equivalent" in expl


def test_notation_matcher_formula_equivalence_newton():
    matcher = NotationMatcher()
    f1 = "F = m*a"
    f2 = "\\Sigma F = m*a"
    is_equiv, score, expl = matcher.are_formulas_equivalent(f1, f2, domain="mechanics")
    assert is_equiv is True
    assert score >= 0.85


def test_notation_matcher_different_formulas_not_equivalent():
    matcher = NotationMatcher()
    f1 = "v = u + at"
    f2 = "E = m*c^2"
    is_equiv, score, expl = matcher.are_formulas_equivalent(f1, f2)
    assert is_equiv is False
    assert score < 0.50


def test_notation_matcher_economics_generalization():
    """Verifies that notation matcher works for non-STEM disciplines like Macroeconomics."""
    matcher = NotationMatcher()
    f1 = "Y = C + I + G + NX"
    f2 = "GDP = C + I + G + (X - M)"
    is_equiv, score, expl = matcher.are_formulas_equivalent(f1, f2, domain="economics")
    assert is_equiv is True
    assert score >= 0.85
    assert "macro_gdp_expenditure" in expl or "Equivalent" in expl


def test_notation_matcher_computer_science_generalization():
    """Verifies that notation matcher works for Computer Science algorithms."""
    matcher = NotationMatcher()
    f1 = "T(n) = 2T(n/2) + O(n)"
    f2 = "T(n) = 2T(n/2) + \\Theta(n)"
    is_equiv, score, expl = matcher.are_formulas_equivalent(f1, f2, domain="computer_science")
    assert is_equiv is True
    assert score >= 0.85


def test_notation_matcher_document_derived_glossary():
    """Verifies zero hardcoded dependency: uses arbitrary document-defined variables."""
    matcher = NotationMatcher()
    # E.g. Law or Economics paper defining custom variable shorthand
    doc_glossary = {
        "K_cap": "capital_stock",
        "L_lab": "labor_input",
        "Q_out": "total_production",
    }
    f1 = "Q_out = K_cap * L_lab"
    f2 = "total_production = capital_stock * labor_input"
    is_equiv, score, expl = matcher.are_formulas_equivalent(f1, f2, context_glossary=doc_glossary)
    assert is_equiv is True
    assert score >= 0.70


def test_resource_recommender_timestamp_and_ranking():
    recommender = ResourceRecommender()

    res1 = ResourceRecord(
        resource_id="res_test_1",
        url="https://youtube.com/watch?v=111",
        title="Kinematics and Uniform Acceleration",
        duration_seconds=600,
        concepts_covered=["c_accel", "acceleration", "velocity"],
        formulas=[
            FormulaVariant(
                raw_formula="v = v_0 + a*t",
                normalized_formula="v = v_0 + a*t",
                canonical_formula_id="kinematics_velocity_time",
            )
        ],
        transcript=[
            TranscriptSegment(
                start_seconds=45.0,
                end_seconds=180.0,
                text="Now let us derive the velocity equation under constant acceleration.",
                concept_ids=["c_accel"],
            )
        ],
        difficulty=0.40,
    )

    res2 = ResourceRecord(
        resource_id="res_test_2",
        url="https://youtube.com/watch?v=222",
        title="Quantum Mechanics Wave Functions",
        duration_seconds=900,
        concepts_covered=["wave_functions", "schrodinger"],
        difficulty=0.90,
    )

    results = recommender.recommend_resources(
        target_concept_id="c_accel",
        target_concept_name="Uniform Acceleration",
        source_formulas=["v = u + at"],
        candidate_resources=[res1, res2],
        learner_mastery=0.25,
        subject_domain="kinematics",
    )

    assert len(results) >= 1
    top = results[0]
    assert top.resource_id == "res_test_1"
    assert top.recommended_timestamp_seconds == 45.0
    assert top.notation_score >= 0.80
    assert top.overall_score > 0.70
    assert any("transcript" in r.lower() or "notation" in r.lower() for r in top.match_reasons)


def test_resource_service_seed_and_retrieval(tmp_path):
    svc = ResourceService(storage_dir=str(tmp_path))
    resources = svc.list_all_resources()
    assert len(resources) >= 3

    r = svc.get_resource("res_3b1b_calculus_essence")
    assert r is not None
    assert r.channel == "3Blue1Brown"
    assert r.transcript_available is True
