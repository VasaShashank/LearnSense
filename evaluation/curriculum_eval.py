"""
Curriculum knowledge-graph evaluation (Person 2).

Extends the conventions already in ``evaluation/phase2_eval.py`` (plain functions
returning a ``dict`` of counts plus derived metrics, golden data supplied by the
caller) to the *canonical curriculum* layer:

* concept mapping quality (the mapper's accepted/unmapped decisions vs a
  reviewed reference),
* relationship extraction quality (precision/recall/F1 over typed edges),
* prerequisite **direction** accuracy (is the edge the right way round?),
* alias / normalization correctness (does one idea stay one concept?),
* provenance and review coverage.

Reporting rules used throughout
-------------------------------

* Every rate states its **denominator**.
* Every metric states its **definition** in the returned ``definitions`` block.
* A metric whose denominator is zero returns ``null`` with ``undefined_reason``
  instead of a flattering ``1.0``.
* ``precision``/``recall``/``f1`` are undefined (not zero) when there is nothing
  to compare against.

**Separating the two failure modes.**  A wrong answer can mean the pipeline never
produced the content (an *extraction/coverage* failure) or the content was there
and the mapper did not match it (a *mapping* failure).  When the caller supplies
the source text for an item, items whose gold term does not appear in that text
are counted under ``source_coverage_failures`` and excluded from the mapping
precision/recall denominators -- so a weak extractor cannot be mistaken for a
weak mapper, and neither can hide behind the other.

Honesty note: these are deterministic comparisons against whatever reference the
caller supplies.  They are not expert-reviewed accuracy claims, and no benchmark
is asserted here that was not actually run.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from curriculum.mapping import ContentMappingResult
from curriculum.models import CurriculumGraph
from curriculum.normalization import normalize_term
from phase2.models import RelationshipTypeEnum

__all__ = [
    "evaluate_alias_normalization",
    "evaluate_concept_mapping",
    "evaluate_curriculum",
    "evaluate_prerequisite_direction",
    "evaluate_relationships",
    "precision_recall_f1",
]

PREREQUISITE_OF = RelationshipTypeEnum.PREREQUISITE_OF.value


# ------------------------------------------------------------------ primitives
def precision_recall_f1(tp: int, fp: int, fn: int) -> Dict[str, Any]:
    """
    Precision/recall/F1 with honest zero-denominator handling.

    Returns ``precision``/``recall`` as ``None`` when undefined, and ``f1`` as
    ``None`` when either input is undefined (rather than reporting a number that
    was not actually measured).
    """
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None:
        f1: Optional[float] = None
    elif (precision + recall) == 0:
        f1 = 0.0
    else:
        f1 = (2 * precision * recall) / (precision + recall)
    result: Dict[str, Any] = {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "precision_denominator": tp + fp,
        "recall_denominator": tp + fn,
    }
    if precision is None:
        result["undefined_reason"] = "no positive predictions to evaluate precision against"
    elif recall is None:
        result["undefined_reason"] = "no gold items to evaluate recall against"
    return result


def _edge_tuple(source: str, relationship_type: str, target: str) -> Tuple[str, str, str]:
    return (source, relationship_type, target)


def _edge_set(edges: Iterable[Any]) -> Set[Tuple[str, str, str]]:
    """Accept dicts, tuples or ``ConceptRelationship`` objects."""
    triples: Set[Tuple[str, str, str]] = set()
    for edge in edges:
        if isinstance(edge, (tuple, list)) and len(edge) == 3:
            triples.add(_edge_tuple(str(edge[0]), str(edge[1]), str(edge[2])))
            continue
        if isinstance(edge, Mapping):
            triples.add(
                _edge_tuple(
                    str(edge.get("source")),
                    str(edge.get("type")),
                    str(edge.get("target")),
                )
            )
            continue
        triples.add(
            _edge_tuple(
                str(getattr(edge, "source")),
                str(getattr(edge, "type_value", getattr(edge, "type"))),
                str(getattr(edge, "target")),
            )
        )
    return triples


def _resolve_key(key: str, key_to_id: Optional[Mapping[str, str]]) -> str:
    if key_to_id is None:
        return key
    return key_to_id.get(key, key)


# ----------------------------------------------------------- concept mapping
def evaluate_concept_mapping(
    mapping: ContentMappingResult,
    gold: Mapping[str, Sequence[str]],
    *,
    key_to_id: Optional[Mapping[str, str]] = None,
    source_texts: Optional[Mapping[str, str]] = None,
    canonical_names: Optional[Mapping[str, Sequence[str]]] = None,
    source_mentions_gold: Optional[Mapping[str, bool]] = None,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare a mapping run against reviewed expectations.

    ``gold`` maps ``item_id`` -> list of *acceptable* canonical concept ids (or
    stable keys when ``key_to_id`` is supplied).  An empty list means the item is
    expected to stay **unmapped**: getting nothing right there is a correct
    abstention, not a miss.

    Answerability (the extraction/mapping split)
    --------------------------------------------
    ``source_texts`` + ``canonical_names`` let the evaluator check whether the
    gold term is literally present in the source text.  An explicit
    ``source_mentions_gold`` mapping overrides that heuristic when the reference
    author already annotated it (the authoritative option; the substring test is
    only a fallback).

    Items whose gold term is absent are reported under
    ``source_coverage_failures`` -- the content never reached the mapper, so a
    miss there is an *extraction* failure.  They are excluded from
    ``recall_answerable`` (the mapping-only view) but **kept** in the primary
    ``recall`` (the end-to-end view), so the two failure modes are separated
    without letting the end-to-end number look better than reality.

    ``split`` is a label carried through to the report (``pilot``,
    ``held_out``, ...) so slices can never be pooled by accident.
    """
    predicted_by_item = {
        candidate.item_id: candidate for candidate in mapping.candidates
    }
    annotated = set(gold)
    unannotated_items = sorted(
        candidate.item_id for candidate in mapping.candidates if candidate.item_id not in annotated
    )

    correct: List[str] = []
    wrong: List[str] = []
    missed: List[str] = []
    correct_abstentions: List[str] = []
    source_coverage_failures: List[str] = []
    answerability_unknown: List[str] = []
    items_missing_from_run: List[str] = []
    predicted_positive = 0
    gold_positive = 0

    for item_id in sorted(gold):
        gold_ids: List[str] = []
        for raw in gold[item_id]:
            resolved = _resolve_key(raw, key_to_id)
            if resolved:
                gold_ids.append(resolved)
        candidate = predicted_by_item.get(item_id)
        if candidate is None:
            items_missing_from_run.append(item_id)
            continue
        predicted_id = candidate.predicted_concept_id
        if predicted_id is not None:
            predicted_positive += 1

        if not gold_ids:
            if predicted_id is None:
                correct_abstentions.append(item_id)
            else:
                wrong.append(item_id)
            continue

        gold_positive += 1

        # Is the gold term even present in the source text?
        source_has_gold: Optional[bool] = None
        if source_mentions_gold is not None and item_id in source_mentions_gold:
            source_has_gold = bool(source_mentions_gold[item_id])
        elif source_texts is not None and canonical_names is not None:
            text_key = normalize_term(source_texts.get(item_id, ""))
            surfaces = [
                normalize_term(surface)
                for gold_id in gold_ids
                for surface in (canonical_names.get(gold_id) or [])
            ]
            source_has_gold = any(surface in text_key for surface in surfaces if surface)
        else:
            answerability_unknown.append(item_id)
        if source_has_gold is False:
            source_coverage_failures.append(item_id)

        if predicted_id is None:
            missed.append(item_id)
        elif predicted_id in gold_ids:
            correct.append(item_id)
        else:
            wrong.append(item_id)

    # Primary (end-to-end) counts: a source-coverage failure is still a miss.
    tp = len(correct)
    fp = len(wrong)
    fn = len(missed) + len(items_missing_from_run)
    metrics = precision_recall_f1(tp, fp, fn)

    # Mapping-only view: misses the mapper could have made (content was present).
    tp_answerable = len([item for item in correct if item not in source_coverage_failures])
    answerable_misses = [
        item for item in missed if item not in source_coverage_failures
    ]
    answerable_denominator = tp_answerable + len(answerable_misses)
    recall_answerable = (
        round(tp_answerable / answerable_denominator, 4) if answerable_denominator else None
    )

    split_items = [
        item_id
        for item_id in sorted(gold)
        if item_id in predicted_by_item
    ]
    items_evaluated = len(split_items)
    abstained = sum(
        1 for item_id in split_items if predicted_by_item[item_id].predicted_concept_id is None
    )
    status_counts: Dict[str, int] = {}
    for item_id in split_items:
        status = predicted_by_item[item_id].status.value
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "metric": "concept_mapping",
        "split": split,
        "items_in_run": items_evaluated,
        "items_with_gold": gold_positive,
        "items_evaluated": items_evaluated,
        "gold_positive_items": gold_positive,
        "predicted_positive_items": predicted_positive,
        **metrics,
        "recall_answerable": recall_answerable,
        "recall_answerable_denominator": answerable_denominator,
        "tp_answerable": tp_answerable,
        "answerable_misses": answerable_misses,
        "status_counts": status_counts,
        "abstention_rate": round(abstained / items_evaluated, 4) if items_evaluated else None,
        "abstention_denominator": items_evaluated,
        "exact_match_accuracy": (
            round((tp + len(correct_abstentions)) / items_evaluated, 4)
            if items_evaluated
            else None
        ),
        "exact_match_denominator": items_evaluated,
        "correct_items": correct,
        "wrong_items": wrong,
        "missed_items": missed,
        "correct_abstentions": correct_abstentions,
        "source_coverage_failures": source_coverage_failures,
        "items_missing_from_run": items_missing_from_run,
        "answerability_unknown": answerability_unknown,
        "unannotated_items": unannotated_items,
        "fingerprints": [mapping.fingerprint],
        "definitions": {
            "precision": (
                "items mapped to an acceptable gold concept / items given any mapping "
                "(end-to-end; source-coverage failures included)"
            ),
            "recall": (
                "items mapped to an acceptable gold concept / items with non-empty gold "
                "(end-to-end, so source-coverage failures count as misses)"
            ),
            "recall_answerable": (
                "items mapped to an acceptable gold concept / (that + misses where the gold "
                "term was actually present in the source); the mapping-only view"
            ),
            "f1": "harmonic mean of precision and recall (both end-to-end)",
            "abstention_rate": "items with no predicted concept / annotated items in this run",
            "exact_match_accuracy": (
                "items with the right answer, including correct abstentions / annotated items "
                "in this run"
            ),
            "source_coverage_failures": (
                "gold items whose expected term does not appear in the supplied source text; "
                "these are extraction/coverage failures. Excluded from recall_answerable, "
                "kept in recall."
            ),
            "items_missing_from_run": (
                "annotated items the run produced no candidate for; counted as end-to-end misses"
            ),
        },
    }


# ------------------------------------------------------------ relationships
def evaluate_relationships(
    predicted: Iterable[Any],
    gold: Iterable[Any],
    *,
    key_to_id: Optional[Mapping[str, str]] = None,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Precision/recall/F1 over typed edges, overall and per relationship type.

    Gold edges may be given as tuples ``(source, type, target)``, dicts, or
    ``ConceptRelationship`` objects.  Sources/targets may be stable keys when
    ``key_to_id`` maps keys to canonical ids.
    """
    gold_resolved = [
        _edge_tuple(
            _resolve_key(edge[0] if isinstance(edge, (tuple, list)) else edge.get("source"), key_to_id),
            edge[1] if isinstance(edge, (tuple, list)) else str(edge.get("type")),
            _resolve_key(edge[2] if isinstance(edge, (tuple, list)) else edge.get("target"), key_to_id),
        )
        for edge in gold
    ]
    gold_set = _edge_set(gold_resolved)
    predicted_set = _edge_set(predicted)

    overall = precision_recall_f1(
        len(predicted_set & gold_set),
        len(predicted_set - gold_set),
        len(gold_set - predicted_set),
    )

    per_type: Dict[str, Dict[str, Any]] = {}
    relationship_types = sorted({edge[1] for edge in gold_set | predicted_set})
    for relationship_type in relationship_types:
        gold_of_type = {edge for edge in gold_set if edge[1] == relationship_type}
        predicted_of_type = {edge for edge in predicted_set if edge[1] == relationship_type}
        per_type[relationship_type] = precision_recall_f1(
            len(predicted_of_type & gold_of_type),
            len(predicted_of_type - gold_of_type),
            len(gold_of_type - predicted_of_type),
        )

    return {
        "metric": "relationship_extraction",
        "split": split,
        **overall,
        "predicted_edges": len(predicted_set),
        "gold_edges": len(gold_set),
        "false_positive_edges": sorted(predicted_set - gold_set),
        "false_negative_edges": sorted(gold_set - predicted_set),
        "per_type": per_type,
        "definitions": {
            "precision": "predicted edges that are gold / all predicted edges",
            "recall": "gold edges that were predicted / all gold edges",
            "per_type": "same computation restricted to one relationship type",
        },
    }


def evaluate_prerequisite_direction(
    predicted: Iterable[Any],
    gold: Iterable[Any],
    *,
    key_to_id: Optional[Mapping[str, str]] = None,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Is each prerequisite edge oriented the right way?

    An edge whose endpoints are right but reversed counts as a **direction
    error**, not as a match: the pair {A, B} being known is a different skill
    from knowing that A must come before B, and pooling them would flatter the
    result.

    Denominators are stated explicitly: ``direction_accuracy`` is over pairs that
    were recognised at all (correct orientation + reversed orientation).
    """
    gold_prereqs = {
        edge
        for edge in _edge_set(
            [
                _edge_tuple(
                    _resolve_key(
                        e[0] if isinstance(e, (tuple, list)) else e.get("source"), key_to_id
                    ),
                    e[1] if isinstance(e, (tuple, list)) else str(e.get("type")),
                    _resolve_key(
                        e[2] if isinstance(e, (tuple, list)) else e.get("target"), key_to_id
                    ),
                )
                for e in gold
            ]
        )
        if edge[1] == PREREQUISITE_OF
    }
    predicted_prereqs = {
        edge
        for edge in _edge_set(predicted)
        if edge[1] == PREREQUISITE_OF
    }

    gold_pairs = {(edge[0], edge[2]) for edge in gold_prereqs}
    correct_orientation = {edge for edge in predicted_prereqs if edge in gold_prereqs}
    reversed_pairs: List[Dict[str, str]] = []
    for source, _, target in predicted_prereqs:
        if source == target:
            continue
        if (target, source) in gold_pairs and (source, target) not in gold_pairs:
            reversed_pairs.append({"source": source, "target": target})
    recognised = len(correct_orientation) + len(reversed_pairs)
    reversed_edges = _reversed_set(reversed_pairs, predicted_prereqs)
    edge_prf = precision_recall_f1(
        len(correct_orientation),
        len(predicted_prereqs - correct_orientation - reversed_edges),
        len(gold_prereqs - correct_orientation),
    )

    return {
        "metric": "prerequisite_direction",
        "split": split,
        "correct_orientation": len(correct_orientation),
        "reversed_orientation": len(reversed_pairs),
        "reversed_examples": sorted(
            reversed_pairs, key=lambda item: (item["source"], item["target"])
        )[:10],
        "gold_prerequisite_edges": len(gold_prereqs),
        "predicted_prerequisite_edges": len(predicted_prereqs),
        "direction_accuracy": (
            round(len(correct_orientation) / recognised, 4) if recognised else None
        ),
        "direction_accuracy_denominator": recognised,
        "undefined_reason": None if recognised else "no prerequisite pairs were recognised",
        "edge_precision": edge_prf["precision"],
        "edge_recall": edge_prf["recall"],
        "edge_f1": edge_prf["f1"],
        "definitions": {
            "direction_accuracy": (
                "correctly oriented prerequisite pairs / (correctly oriented + reversed) pairs"
            ),
            "reversed_orientation": (
                "predicted prerequisite pairs whose endpoints match a gold pair but point the "
                "wrong way"
            ),
            "edge_precision": "predicted prerequisite edges that are gold / all predicted prerequisite edges",
            "edge_recall": "gold prerequisite edges that were predicted / all gold prerequisite edges",
        },
    }


def _reversed_set(
    reversed_pairs: Sequence[Dict[str, str]], predicted_prereqs: Set[Tuple[str, str, str]]
) -> Set[Tuple[str, str, str]]:
    reversed_edges = {
        edge
        for edge in predicted_prereqs
        if any(edge[0] == pair["source"] and edge[2] == pair["target"] for pair in reversed_pairs)
    }
    return reversed_edges


# ------------------------------------------------------------- alias/normalization
def evaluate_alias_normalization(
    canonical_concepts: Iterable[Any],
    gold_alias_groups: Sequence[Sequence[str]],
    *,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Does one idea stay exactly one canonical concept?

    ``gold_alias_groups`` is a list of surface-form groups that are known to
    denote the same concept (e.g. ``[["velocity", "speed with direction"]]``).

    * ``merged_correctly`` -- all surfaces of a group resolve to one concept.
    * ``split_concepts`` -- the group's surfaces resolve to different concepts
      (the bug alias handling exists to prevent).
    * ``false_merges`` -- two surfaces that gold says are *different* concepts
      but resolve to the same id.  These are supplied via
      ``distinct_groups``.

    ``spurious_duplicate_rate`` reports active concept pairs in the same subject
    that share a normalized name; a validated graph must be 0.
    """
    from collections import defaultdict

    surface_to_concept: Dict[str, Set[str]] = defaultdict(set)
    concept_names: Dict[str, str] = {}
    subject_by_concept: Dict[str, str] = {}
    active = []
    for concept in canonical_concepts:
        if getattr(getattr(concept, "status", None), "value", None) == "deprecated":
            continue
        active.append(concept)
        concept_names[concept.concept_id] = concept.name
        subject_by_concept[concept.concept_id] = concept.subject_value
        for entry in concept.surface_keys():
            surface_to_concept[entry["surface"]].add(concept.concept_id)

    merged: List[List[str]] = []
    split: List[Dict[str, Any]] = []
    for group in gold_alias_groups:
        surfaces = [normalize_term(surface) for surface in group if normalize_term(surface)]
        resolved: Set[str] = set()
        for surface in surfaces:
            resolved |= surface_to_concept.get(surface, set())
        if len(resolved) == 1:
            merged.append(surfaces)
        elif not resolved:
            split.append({"surfaces": surfaces, "resolved": [], "reason": "no canonical match"})
        else:
            split.append(
                {
                    "surfaces": surfaces,
                    "resolved": sorted(resolved),
                    "resolved_names": sorted(concept_names[cid] for cid in resolved),
                    "reason": "surfaces mapped to different canonical concepts",
                }
            )

    # Spurious duplicates: active pairs in one subject sharing a normalized name.
    by_subject_name: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for concept in active:
        by_subject_name[(concept.subject_value, concept.normalized_name)].append(concept.concept_id)
    duplicates = {
        f"{subject}:{name}": sorted(ids)
        for (subject, name), ids in by_subject_name.items()
        if len(ids) > 1
    }

    total_groups = len(gold_alias_groups)
    return {
        "metric": "alias_normalization",
        "split": split,
        "gold_groups": total_groups,
        "merged_correctly": len(merged),
        "split_concepts": len(split),
        "split_details": split,
        "merge_accuracy": round(len(merged) / total_groups, 4) if total_groups else None,
        "merge_accuracy_denominator": total_groups,
        "active_concepts": len(active),
        "spurious_duplicate_groups": len(duplicates),
        "spurious_duplicate_details": duplicates,
        "spurious_duplicate_rate": (
            round(len(duplicates) / len(active), 4) if active else None
        ),
        "spurious_duplicate_denominator": len(active),
        "undefined_reason": None if total_groups else "no gold alias groups supplied",
        "definitions": {
            "merge_accuracy": "gold alias groups resolving to exactly one concept / gold alias groups",
            "spurious_duplicate_rate": (
                "active same-subject concept pairs sharing a normalized name / active concepts"
            ),
        },
    }


# ------------------------------------------------------------------ combined
def evaluate_curriculum(
    graph: CurriculumGraph,
    reference: Mapping[str, Any],
    mapping_runs: Optional[Sequence[ContentMappingResult]] = None,
) -> Dict[str, Any]:
    """
    Evaluate a canonical graph against a reference dataset.

    ``reference`` is a dict with (all optional, evaluated only when present):

    * ``concepts`` / ``relationships`` -- gold curriculum,
    * ``items`` -- ``{item_id, text, expected: [stable_key, ...], split}``,
    * ``alias_groups`` -- gold alias groups,
    * ``expected_counts`` -- hand-enumerated TP/FP/FN per split, used as a
      regression guard on the metric arithmetic itself.

    Returns per-split and pooled results with definitions attached.
    """
    key_to_id = {
        concept.stable_key: concept.concept_id
        for concept in graph.concepts.values()
        if concept.stable_key
    }
    canonical_names = {
        concept_id: [concept.name] + list(concept.aliases)
        for concept_id, concept in graph.concepts.items()
    }

    gold_edges = [
        (
            item.get("source_key") or item.get("source"),
            item.get("type", PREREQUISITE_OF),
            item.get("target_key") or item.get("target"),
        )
        for item in reference.get("relationships", [])
    ]

    items = reference.get("items", [])
    splits: Dict[str, List[Mapping[str, Any]]] = {}
    for item in items:
        splits.setdefault(str(item.get("split", "default")), []).append(item)

    runs_by_document = {
        run.document_id: run for run in (mapping_runs or []) if run.document_id
    }

    results: Dict[str, Any] = {
        "curriculum_id": graph.curriculum_id,
        "syllabus_version": graph.syllabus_version,
        "graph_fingerprint": graph.content_fingerprint(),
        "reference_name": reference.get("name", ""),
        "reference_note": reference.get("note", ""),
        "splits": {},
    }

    for split_name, split_items in sorted(splits.items()):
        gold: Dict[str, Sequence[str]] = {
            item["item_id"]: item.get("expected", []) for item in split_items
        }
        texts = {item["item_id"]: item.get("text", "") for item in split_items}
        # Explicit answerability annotations win over the substring heuristic.
        mentions = {
            item["item_id"]: bool(item["source_mentions_gold"])
            for item in split_items
            if "source_mentions_gold" in item
        }
        # Choose the run that covers these item ids.
        run = _pick_run(runs_by_document, gold)
        split_result: Dict[str, Any] = {"item_count": len(split_items)}
        if run is not None:
            split_result["concept_mapping"] = evaluate_concept_mapping(
                run,
                gold,
                key_to_id=key_to_id,
                source_texts=texts,
                canonical_names=canonical_names,
                source_mentions_gold=mentions or None,
                split=split_name,
            )
        elif gold:
            split_result["concept_mapping"] = {
                "metric": "concept_mapping",
                "split": split_name,
                "undefined_reason": "no mapping run supplied for this split's items",
                "items_with_gold": len(gold),
            }
        results["splits"][split_name] = split_result

    # Graph-level metrics (not split specific).
    results["relationship_extraction"] = evaluate_relationships(
        graph.relationships.values(), gold_edges, key_to_id=key_to_id
    )
    results["prerequisite_direction"] = evaluate_prerequisite_direction(
        graph.relationships.values(), gold_edges, key_to_id=key_to_id
    )
    alias_groups = reference.get("alias_groups") or []
    results["alias_normalization"] = evaluate_alias_normalization(
        graph.concepts.values(), alias_groups
    )

    expected_counts = reference.get("expected_counts")
    if expected_counts:
        results["expected_count_checks"] = _check_expected_counts(results, expected_counts)
    return results


def _pick_run(
    runs_by_document: Mapping[str, ContentMappingResult], gold: Mapping[str, Any]
) -> Optional[ContentMappingResult]:
    if not runs_by_document:
        return None
    item_ids = set(gold)
    for run in runs_by_document.values():
        if item_ids & {candidate.item_id for candidate in run.candidates}:
            return run
    return None


def _check_expected_counts(
    results: Mapping[str, Any], expected: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """
    Compare hand-enumerated counts against the computed ones.

    Supported sections (all optional)::

        {
          "concept_mapping": {"<split>": {"tp": .., "fp": .., "fn": ..}, ...},
          "relationship_extraction": {"tp": .., "fp": .., "fn": ..},
          "prerequisite_direction": {"correct_orientation": .., "reversed_orientation": ..},
          "alias_normalization": {"merged_correctly": .., "split_concepts": ..}
        }

    A mismatch is *reported*, not raised, so a caller can print the whole table;
    tests assert every ``ok`` flag, which keeps the hand counts honest rather
    than silently regenerated from whatever the code happens to produce.
    """
    checks: List[Dict[str, Any]] = []

    def record(metric: str, expected_value: Any, computed: Any) -> None:
        checks.append(
            {
                "metric": metric,
                "expected": expected_value,
                "computed": computed,
                "ok": expected_value == computed,
            }
        )

    mapping_expected = expected.get("concept_mapping") or {}
    if isinstance(mapping_expected, Mapping):
        for split_name, split_expected in sorted(mapping_expected.items()):
            actual = ((results.get("splits") or {}).get(split_name) or {}).get(
                "concept_mapping"
            ) or {}
            for key, value in sorted((split_expected or {}).items()):
                record(f"concept_mapping.{split_name}.{key}", value, actual.get(key))

    for section, keys in (
        ("relationship_extraction", ("tp", "fp", "fn")),
        ("prerequisite_direction", ("correct_orientation", "reversed_orientation")),
        ("alias_normalization", ("merged_correctly", "split_concepts")),
    ):
        section_expected = expected.get(section) or {}
        actual = results.get(section) or {}
        for key in keys:
            if key in section_expected:
                record(f"{section}.{key}", section_expected[key], actual.get(key))
    return checks
