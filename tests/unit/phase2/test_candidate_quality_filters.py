"""Unit tests for concept-extraction quality filters.

Garbage previously mined from slides/references/tables:
  - person names  : "Revanth Vishnu Reddy", "Ramakrishnan", "Gehrke"
  - table headers : "Entity", "PK", "Purpose", "Takeaway"
  - citations     : "Malkov, Y. A., & Yashunin, D. A. (2020). ..."
  - slide titles  : "Akasic", "Presenter", "Guide"
"""

import pytest

from phase2.pipeline.stage4_candidates import (
    MIN_TERM_OCCURRENCES,
    _is_bibliography_entry,
    _is_markdown_table,
    _is_person_name,
    _person_name_keys,
)


def test_markdown_table_detected():
    assert _is_markdown_table("| # | Title | Takeaway |\n| --- | --- | --- |\n| 1 | A | B |")
    assert _is_markdown_table("| Data | Store | Role |\n| --- | --- | --- |\n| a | b | c |")
    # Ordinary prose is not a table.
    assert not _is_markdown_table("A limit describes the value a function approaches.")


def test_bibliography_detected():
    assert _is_bibliography_entry(
        "Malkov, Y. A., & Yashunin, D. A. (2020). Efficient and robust approximate "
        "nearest neighbor search. IEEE TPAMI, 42(4)."
    )
    assert _is_bibliography_entry(
        "Selinger, P. G., et al. (1979). Access path selection in a relational "
        "database management system. ACM SIGMOD."
    )
    # A year mentioned in teaching prose is not a reference line.
    assert not _is_bibliography_entry(
        "The 2020 cohort completed the course, and the deadline is fixed."
    )


def test_person_name_keys_and_matching():
    text = "Team: Revanth Vishnu Reddy C B (1RV24CS227), Punith A M (1RV24CS208)"
    keys = _person_name_keys(text)
    assert "revanth" in keys
    assert "1rv24cs227" not in keys  # the ID itself is not a name token

    assert _is_person_name("Revanth Vishnu Reddy", keys)
    assert _is_person_name("Punith", keys)
    # A genuine domain term that shares no tokens with any person name.
    assert not _is_person_name("Vector Embedding", keys)


def test_author_list_names_detected():
    keys = _person_name_keys("Ramakrishnan, R., & Gehrke, J. Database Management Systems.")
    assert "ramakrishnan" in keys
    assert "gehrke" in keys
    assert _is_person_name("Ramakrishnan", keys)


def test_min_occurrences_threshold_is_enforced():
    # A one-off slide title must not be promoted to a concept.
    assert MIN_TERM_OCCURRENCES >= 2
