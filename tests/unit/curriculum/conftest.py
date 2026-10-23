"""
Shared fixtures for the canonical curriculum tests (Person 2).

The pilot dataset lives in ``tests/fixtures/curriculum/pilot_dataset.json``.  It
serves two roles at once: its ``concepts`` / ``relationships`` sections are the
``CurriculumSpec`` that seeds the graph, and the whole file is the evaluation
reference (``items``, ``alias_groups``, ``expected_counts``) handed to
``evaluate_curriculum``.  :func:`dataset_spec` keeps the two views in sync so a
test can never evaluate against gold edges that differ from the seeded graph.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from curriculum.seed import CurriculumSpec, seed_curriculum

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "curriculum"
DATASET_PATH = FIXTURE_DIR / "pilot_dataset.json"

#: Dataset keys that belong to the seed spec; everything else is evaluation
#: reference material (items, alias_groups, expected_counts, notes).
SPEC_KEYS = (
    "curriculum_id",
    "syllabus_version",
    "title",
    "concepts",
    "relationships",
    "metadata",
)


def load_dataset() -> Dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def dataset_spec(raw: Optional[Dict[str, Any]] = None) -> CurriculumSpec:
    raw = load_dataset() if raw is None else raw
    return CurriculumSpec.model_validate({key: raw[key] for key in SPEC_KEYS if key in raw})


@pytest.fixture
def pilot_raw() -> Dict[str, Any]:
    """The raw pilot dataset, including the evaluation reference sections."""
    return load_dataset()


@pytest.fixture
def pilot_spec() -> CurriculumSpec:
    """The seed-spec view of the pilot dataset."""
    return dataset_spec()


@pytest.fixture
def pilot_graph():
    """A freshly seeded pilot graph; safe for a test to mutate."""
    return seed_curriculum(dataset_spec())
