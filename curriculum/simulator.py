"""
Simulator <-> canonical curriculum bridge (Person 2).

The team's ``learnsense_jee_simulator_v2`` package ships hand-written concept ids
(``PHY_KIN``, ``MAT_DIF`` …) and marks them
``illustrative_pilot_graph_map_to_canonical_LearnSense_graph``.  Those ids must
never leak into production: the simulator is *illustrative test data*, and its
graph is not the canonical curriculum.

This module therefore treats the simulator CSV as **read-only input** and
produces an explicit, inspectable mapping from simulator ids to canonical ids.
Three outcomes are possible and all three are reported honestly:

``mapped``
    exactly one canonical concept matched (by override, or by the shared rule
    table against canonical names/aliases).
``ambiguous``
    several canonical concepts matched within the decisive margin; a human must
    choose.
``unmapped``
    nothing matched.  The simulator id stays unresolved rather than being forced
    onto the nearest concept.

Synthetic interaction logs are never treated as learner evidence; this module
only reads concept and question *metadata*.
"""

from __future__ import annotations

import csv
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from curriculum.graph import CurriculumGraphValidator
from curriculum.mapping import (
    ACCEPTED_MIN_STRENGTH,
    DECISIVENESS_MARGIN,
    UNCERTAIN_MIN_STRENGTH,
    MatchKind,
    score_surface_against_concept,
)
from curriculum.models import ConceptLifecycleStatus, CurriculumGraph

__all__ = [
    "QuestionConceptRef",
    "SimulatorBridge",
    "SimulatorConcept",
    "SimulatorMappingEntry",
    "SimulatorMappingStatus",
    "load_simulator_concepts",
]


class SimulatorConcept(BaseModel):
    """One row of the simulator's ``concepts.csv``."""

    model_config = ConfigDict(extra="forbid")

    simulator_concept_id: str
    name: str
    subject: str = ""
    topic_group: str = ""
    prerequisite_ids: List[str] = Field(default_factory=list)
    curriculum_status: str = ""

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "SimulatorConcept":
        raw_prereqs = row.get("prerequisite_ids") or ""
        prerequisites = [item.strip() for item in raw_prereqs.split(";") if item.strip()]
        return cls(
            simulator_concept_id=(row.get("concept_id") or "").strip(),
            name=(row.get("concept_name") or "").strip(),
            subject=(row.get("subject") or "").strip().lower(),
            topic_group=(row.get("topic_group") or "").strip(),
            prerequisite_ids=prerequisites,
            curriculum_status=(row.get("curriculum_status") or "").strip(),
        )


class SimulatorMappingStatus(str, Enum):
    MAPPED = "mapped"
    AMBIGUOUS = "ambiguous"
    UNMAPPED = "unmapped"
    EXCLUDED = "excluded"


class SimulatorMappingEntry(BaseModel):
    """Explicit mapping decision for one simulator concept."""

    model_config = ConfigDict(extra="forbid")

    simulator_concept_id: str
    simulator_name: str
    status: SimulatorMappingStatus
    canonical_concept_id: Optional[str] = None
    canonical_name: str = ""
    match_strength: float = 0.0
    matched_surface: str = ""
    match_kind: Optional[MatchKind] = None
    reason: str = ""
    via_override: bool = False
    alternative_concept_ids: List[str] = Field(default_factory=list)


class QuestionConceptRef(BaseModel):
    """
    Stable question -> canonical concept reference for Person 3.

    ``assesses`` in the proposed ``question_schema.json`` is a list of
    ``{concept_id, weight, role}`` where ``role`` is primary/secondary/supporting.
    This model produces exactly that, and refuses to invent a concept id when a
    simulator id cannot be resolved.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str
    primary_concept_id: Optional[str] = None
    concept_ids: List[str] = Field(default_factory=list)
    status: str = "unmapped"
    unresolved_simulator_ids: List[str] = Field(default_factory=list)

    def to_contract_assesses(self, primary_weight: float = 0.7) -> List[Dict[str, Any]]:
        """Build the ``assesses`` array: primary concept first, remainder split evenly."""
        if not self.concept_ids:
            return []
        remaining = round(1.0 - primary_weight, 4)
        share = round(remaining / max(len(self.concept_ids) - 1, 1), 4) if len(self.concept_ids) > 1 else 0.0
        assesses: List[Dict[str, Any]] = []
        for index, concept_id in enumerate(self.concept_ids):
            is_primary = concept_id == self.primary_concept_id
            assesses.append(
                {
                    "concept_id": concept_id,
                    "weight": primary_weight if is_primary else share,
                    "role": "primary" if is_primary else ("secondary" if index == 1 else "supporting"),
                }
            )
        if self.primary_concept_id is None and assesses:
            assesses[0]["role"] = "primary"
        return assesses


def load_simulator_concepts(path: str | Path) -> List[SimulatorConcept]:
    """
    Read the simulator's ``concepts.csv`` (read-only).

    Raises ``FileNotFoundError`` rather than returning an empty list, so a missing
    reference file is a visible failure and never a silent "everything mapped".
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Simulator concepts file not found: {csv_path}")
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [SimulatorConcept.from_row(dict(row)) for row in reader]
    return [concept for concept in rows if concept.simulator_concept_id]


class SimulatorBridge:
    """
    Maps simulator concept ids onto canonical LearnSense concept ids.

    An explicit ``overrides`` mapping always wins; it is the mechanism a curriculum
    editor uses to resolve the ambiguous cases the rule table cannot.
    """

    def __init__(self, graph: CurriculumGraph, overrides: Optional[Dict[str, str]] = None):
        self.graph = graph
        self.overrides = dict(overrides or {})
        self._validator = CurriculumGraphValidator()

    # ------------------------------------------------------------- concept map
    def map_concepts(self, concepts: Sequence[SimulatorConcept]) -> List[SimulatorMappingEntry]:
        entries: List[SimulatorMappingEntry] = []
        for concept in sorted(concepts, key=lambda item: item.simulator_concept_id):
            entries.append(self._map_one(concept))
        return entries

    def _map_one(self, concept: SimulatorConcept) -> SimulatorMappingEntry:
        override = self.overrides.get(concept.simulator_concept_id)
        if override is not None:
            target = self.graph.concepts.get(override)
            if target is None:
                return SimulatorMappingEntry(
                    simulator_concept_id=concept.simulator_concept_id,
                    simulator_name=concept.name,
                    status=SimulatorMappingStatus.UNMAPPED,
                    reason=f"override points at unknown canonical concept '{override}'",
                    via_override=True,
                )
            return SimulatorMappingEntry(
                simulator_concept_id=concept.simulator_concept_id,
                simulator_name=concept.name,
                status=SimulatorMappingStatus.MAPPED,
                canonical_concept_id=target.concept_id,
                canonical_name=target.name,
                match_strength=1.0,
                matched_surface=concept.name,
                reason="explicit curriculum override",
                via_override=True,
            )

        if concept.curriculum_status.startswith("illustrative_pilot"):
            # Simulator-declared illustrative data: never auto-promoted.
            pass

        best: List[Any] = []
        for concept_id in self.graph.concept_ids():
            target = self.graph.concepts[concept_id]
            if _status(target.status) == ConceptLifecycleStatus.DEPRECATED.value:
                continue
            match = score_surface_against_concept(concept.name, target)
            if match is not None:
                best.append(match)
        best.sort(key=lambda match: match.sort_key())

        if not best:
            return SimulatorMappingEntry(
                simulator_concept_id=concept.simulator_concept_id,
                simulator_name=concept.name,
                status=SimulatorMappingStatus.UNMAPPED,
                reason=(
                    "no canonical name or alias matched; add an override or a canonical "
                    "alias if this concept should exist"
                ),
            )
        top = best[0]
        runner_up = best[1].match_strength if len(best) > 1 else 0.0
        alternatives = [match.concept_id for match in best[1:4]]
        if top.match_strength < UNCERTAIN_MIN_STRENGTH:
            return SimulatorMappingEntry(
                simulator_concept_id=concept.simulator_concept_id,
                simulator_name=concept.name,
                status=SimulatorMappingStatus.UNMAPPED,
                match_strength=top.match_strength,
                matched_surface=top.matched_surface,
                reason=(
                    f"best match strength {top.match_strength:.2f} is below the "
                    f"{UNCERTAIN_MIN_STRENGTH:.2f} floor"
                ),
                alternative_concept_ids=alternatives,
            )
        if top.match_strength >= ACCEPTED_MIN_STRENGTH and (
            top.match_strength - runner_up
        ) >= DECISIVENESS_MARGIN:
            return SimulatorMappingEntry(
                simulator_concept_id=concept.simulator_concept_id,
                simulator_name=concept.name,
                status=SimulatorMappingStatus.MAPPED,
                canonical_concept_id=top.concept_id,
                canonical_name=top.canonical_name,
                match_strength=top.match_strength,
                matched_surface=top.matched_surface,
                match_kind=top.match_kind,
                reason=f"decisive rule-table match at {top.match_strength:.2f}",
                alternative_concept_ids=alternatives,
            )
        return SimulatorMappingEntry(
            simulator_concept_id=concept.simulator_concept_id,
            simulator_name=concept.name,
            status=SimulatorMappingStatus.AMBIGUOUS,
            match_strength=top.match_strength,
            matched_surface=top.matched_surface,
            match_kind=top.match_kind,
            canonical_concept_id=None,
            reason=(
                f"{len(best)} canonical concepts matched within {DECISIVENESS_MARGIN:.2f} of each "
                f"other (top {top.match_strength:.2f}, runner-up {runner_up:.2f}); a curriculum "
                f"editor must choose"
            ),
            alternative_concept_ids=alternatives,
        )

    def resolve_map(self, entries: Sequence[SimulatorMappingEntry]) -> Dict[str, str]:
        """Only the confidently mapped simulator ids -> canonical ids."""
        return {
            entry.simulator_concept_id: entry.canonical_concept_id
            for entry in entries
            if entry.status == SimulatorMappingStatus.MAPPED and entry.canonical_concept_id
        }

    # ----------------------------------------------------------- question map
    def map_questions(
        self,
        questions: Iterable[Dict[str, str]],
        concept_map: Dict[str, str],
    ) -> List[QuestionConceptRef]:
        """
        Turn simulator question metadata into canonical question->concept refs.

        ``questions`` rows need ``question_id`` plus ``primary_concept_id`` and/or
        a ``;``-separated ``concept_ids`` list.  Rows whose primary concept cannot
        be resolved are reported ``unmapped`` with the offending simulator ids —
        never silently given a made-up canonical id.
        """
        refs: List[QuestionConceptRef] = []
        for row in questions:
            question_id = (row.get("question_id") or "").strip()
            if not question_id:
                continue
            primary_sim = (row.get("primary_concept_id") or "").strip()
            raw_all = row.get("concept_ids") or ""
            sim_ids: List[str] = [item.strip() for item in raw_all.split(";") if item.strip()]
            if primary_sim and primary_sim not in sim_ids:
                sim_ids.insert(0, primary_sim)

            resolved: List[str] = []
            unresolved: List[str] = []
            for sim_id in sim_ids:
                canonical = concept_map.get(sim_id)
                if canonical is None:
                    unresolved.append(sim_id)
                elif canonical not in resolved:
                    resolved.append(canonical)

            primary = concept_map.get(primary_sim) if primary_sim else None
            if not resolved:
                status = "unmapped"
            elif unresolved:
                status = "partial"
            else:
                status = "complete"
            refs.append(
                QuestionConceptRef(
                    question_id=question_id,
                    primary_concept_id=primary if primary in resolved else (resolved[0] if resolved else None),
                    concept_ids=resolved,
                    status=status,
                    unresolved_simulator_ids=unresolved,
                )
            )
        return sorted(refs, key=lambda ref: ref.question_id)

    # -------------------------------------------------- prerequisite edge audit
    def prerequisite_edge_report(
        self,
        concepts: Sequence[SimulatorConcept],
        concept_map: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Check every simulated prerequisite edge against the canonical graph.

        Reports which simulator prerequisite relations are backed by an accepted
        canonical ``prerequisite_of`` edge, which contradict the canonical graph,
        and which could not be checked because an endpoint is unmapped.

        Performs structural integrity checks on the simulator edges:
        - Cycle detection (Tarjan/DFS)
        - Self-loops (direct or mapped-collapse)
        - Duplicate edge declarations
        - Missing endpoint concept definitions
        - Categorized endpoint resolution breakdown (source/target/both unmapped)
        """
        all_sim_ids = {c.simulator_concept_id for c in concepts}
        seen_edges: Set[Tuple[str, str]] = set()
        duplicates: List[Dict[str, str]] = []
        self_loops: List[Dict[str, str]] = []
        missing_endpoints: List[Dict[str, str]] = []
        endpoint_resolution: Dict[str, List[Dict[str, str]]] = {
            "both_unmapped": [],
            "source_unmapped_only": [],
            "target_unmapped_only": [],
        }

        # Simulator cycle check via DFS
        adj: Dict[str, List[str]] = {c.simulator_concept_id: list(c.prerequisite_ids) for c in concepts}
        visited: Dict[str, bool] = {}
        rec_stack: Dict[str, bool] = {}
        detected_cycles: List[List[str]] = []

        def _dfs(node: str, path: List[str]) -> None:
            visited[node] = True
            rec_stack[node] = True
            for neighbor in adj.get(node, []):
                if not visited.get(neighbor, False):
                    _dfs(neighbor, path + [neighbor])
                elif rec_stack.get(neighbor, False):
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    detected_cycles.append(path[cycle_start:] + [neighbor])
            rec_stack[node] = False

        for cid in sorted(adj):
            if not visited.get(cid, False):
                _dfs(cid, [cid])

        backed: List[Dict[str, str]] = []
        contradicted: List[Dict[str, str]] = []
        unchecked: List[Dict[str, str]] = []
        checked = 0

        for concept in sorted(concepts, key=lambda item: item.simulator_concept_id):
            target_sim = concept.simulator_concept_id
            target = concept_map.get(target_sim)
            for prereq_sim in concept.prerequisite_ids:
                edge_sim = (prereq_sim, target_sim)
                if edge_sim in seen_edges:
                    duplicates.append({"source_sim": prereq_sim, "target_sim": target_sim})
                seen_edges.add(edge_sim)

                if prereq_sim not in all_sim_ids:
                    missing_endpoints.append({
                        "source_sim": prereq_sim,
                        "target_sim": target_sim,
                        "missing": "source",
                    })

                if prereq_sim == target_sim:
                    self_loops.append({
                        "source_sim": prereq_sim,
                        "target_sim": target_sim,
                        "kind": "simulator_identity",
                    })

                source = concept_map.get(prereq_sim)
                if not source or not target:
                    unchecked.append({"source_sim": prereq_sim, "target_sim": target_sim})
                    if not source and not target:
                        endpoint_resolution["both_unmapped"].append({
                            "source_sim": prereq_sim,
                            "target_sim": target_sim,
                        })
                    elif not source:
                        endpoint_resolution["source_unmapped_only"].append({
                            "source_sim": prereq_sim,
                            "target_sim": target_sim,
                            "target": target,
                        })
                    else:
                        endpoint_resolution["target_unmapped_only"].append({
                            "source_sim": prereq_sim,
                            "target_sim": target_sim,
                            "source": source,
                        })
                    continue

                if source == target:
                    self_loops.append({
                        "source_sim": prereq_sim,
                        "target_sim": target_sim,
                        "source": source,
                        "target": target,
                        "kind": "mapped_collapse",
                    })
                    contradicted.append({
                        "source": source,
                        "target": target,
                        "source_sim": prereq_sim,
                        "target_sim": target_sim,
                        "reason": "mapped_self_loop",
                    })
                    checked += 1
                    continue

                checked += 1
                canonical_edge = [
                    rel
                    for rel in self.graph.relationships_between(source, target)
                    if rel.is_prerequisite and rel.status_value == "accepted"
                ]
                record = {
                    "source": source,
                    "target": target,
                    "source_sim": prereq_sim,
                    "target_sim": target_sim,
                }
                if canonical_edge:
                    backed.append(record)
                else:
                    contradicted.append(record)

        return {
            "checked": checked,
            "backed": backed,
            "contradicted": contradicted,
            "unchecked": unchecked,
            "backing_rate": round(len(backed) / checked, 4) if checked else 0.0,
            "endpoint_resolution": {
                "both_unmapped_count": len(endpoint_resolution["both_unmapped"]),
                "source_unmapped_only_count": len(endpoint_resolution["source_unmapped_only"]),
                "target_unmapped_only_count": len(endpoint_resolution["target_unmapped_only"]),
                "details": endpoint_resolution,
            },
            "structural_checks": {
                "is_dag": len(detected_cycles) == 0,
                "cycles": detected_cycles,
                "self_loops": self_loops,
                "duplicates": duplicates,
                "missing_endpoints": missing_endpoints,
                "total_declared_edges": len(seen_edges),
            },
            "note": (
                "A contradicted edge means the simulator asserts a prerequisite the canonical "
                "curriculum does not accept. The simulator is illustrative data; the canonical "
                "graph is the source of truth."
            ),
        }

    def summary(self, entries: Sequence[SimulatorMappingEntry]) -> Dict[str, Any]:
        counts = {status.value: 0 for status in SimulatorMappingStatus}
        for entry in entries:
            counts[entry.status.value] += 1
        total = len(entries)
        return {
            "total": total,
            **counts,
            "mapped_rate": round(counts[SimulatorMappingStatus.MAPPED.value] / total, 4) if total else 0.0,
            "unmapped_ids": sorted(
                entry.simulator_concept_id
                for entry in entries
                if entry.status in {SimulatorMappingStatus.UNMAPPED, SimulatorMappingStatus.AMBIGUOUS}
            ),
            "canonical_curriculum_id": self.graph.curriculum_id,
            "canonical_fingerprint": self.graph.content_fingerprint(),
        }


def _status(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)
