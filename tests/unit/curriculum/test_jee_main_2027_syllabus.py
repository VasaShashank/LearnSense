"""
Unit tests for official JEE Main 2027 Paper 1 PCM Syllabus Extraction and Inventory.
"""

import json
from pathlib import Path
import pytest

SYLLABUS_PATH = Path("curriculum/data/source/jee_main_2027_syllabus.json")
EXPECTED_SHA256 = "823EC5AFAF30F19D4F0DC375159D8B843B944633E4EDDA58C9D910C145C32CCD"


@pytest.fixture
def syllabus_inventory():
    assert SYLLABUS_PATH.exists(), f"Syllabus file missing at {SYLLABUS_PATH}"
    with open(SYLLABUS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_source_provenance_and_metadata(syllabus_inventory):
    meta = syllabus_inventory["metadata"]
    assert meta["examination"] == "JEE (Main) - 2027"
    assert meta["paper"] == "Paper 1 (B.E./B.Tech.)"
    assert meta["official_url"] == "https://jeemain.nta.nic.in/document/syllabus-2027/"
    assert meta["source"]["sha256"] == EXPECTED_SHA256
    assert meta["total_units"] == 54
    assert meta["unit_distribution"]["mathematics"] == 14
    assert meta["unit_distribution"]["physics"] == 20
    assert meta["unit_distribution"]["chemistry"] == 20


def test_exclusion_of_paper_2a_and_2b(syllabus_inventory):
    meta = syllabus_inventory["metadata"]
    excluded = meta.get("excluded_papers", [])
    assert any("Paper 2A" in p for p in excluded)
    assert any("Paper 2B" in p for p in excluded)

    # Verify no Paper 2 items leaked into syllabus_items
    for item in syllabus_inventory["syllabus_items"]:
        assert item["paper"] == "Paper 1 (B.E./B.Tech.)"
        assert item["subject"] in {"mathematics", "physics", "chemistry"}
        assert "Aptitude" not in item["official_unit_title"]
        assert "Drawing" not in item["official_unit_title"]
        assert "Planning" not in item["official_unit_title"]


def test_unit_and_item_counts(syllabus_inventory):
    items = syllabus_inventory["syllabus_items"]
    assert len(items) == 135

    math_items = [i for i in items if i["subject"] == "mathematics"]
    phy_items = [i for i in items if i["subject"] == "physics"]
    chem_items = [i for i in items if i["subject"] == "chemistry"]

    assert len(math_items) == 29
    assert len(phy_items) == 62
    assert len(chem_items) == 44

    # Verify unit codes
    math_units = {i["official_unit_code"] for i in math_items}
    phy_units = {i["official_unit_code"] for i in phy_items}
    chem_units = {i["official_unit_code"] for i in chem_items}

    assert len(math_units) == 14
    assert len(phy_units) == 20
    assert len(chem_units) == 20


def test_physics_experimental_skills_unit_20(syllabus_inventory):
    items = syllabus_inventory["syllabus_items"]
    exp_items = [i for i in items if i["official_unit_code"] == "PHY_U20"]
    assert len(exp_items) == 18, "Physics Unit 20 must represent all 18 official experiments"

    exp_topics = [i["official_topic"] for i in exp_items]
    assert "Vernier Calipers" in exp_topics
    assert "Screw Gauge" in exp_topics
    assert "Simple Pendulum" in exp_topics
    assert "Metre Scale" in exp_topics
    assert "Young's Modulus" in exp_topics
    assert "Surface Tension" in exp_topics
    assert "Speed of Sound" in exp_topics
    assert "Metre Bridge Resistivity" in exp_topics
    assert "Ohm's Law Resistance" in exp_topics
    assert "p-n Diode Characteristics" in exp_topics
    assert "Zener Diode Breakdown" in exp_topics


def test_chemistry_practical_principles_unit_20(syllabus_inventory):
    items = syllabus_inventory["syllabus_items"]
    chem_prac = [i for i in items if i["official_unit_code"] == "CHEM_U20"]
    assert len(chem_prac) == 5

    topics = [i["official_topic"] for i in chem_prac]
    assert "Detection of Elements and Functional Groups" in topics
    assert "Chemical Preparations" in topics
    assert "Titrimetric Analysis" in topics
    assert "Qualitative Salt Analysis" in topics
    assert "Physical Chemistry Experiments" in topics
