"""
Simulator-ID -> canonical-ID mastery translation (Person 2).

Person 3's AKT + concept-mastery head emits a mastery profile keyed by *simulator*
concept IDs (``PHY_*`` / ``CHE_*`` / ``MAT_*``), while the canonical curriculum
graph is keyed by ``cc_`` IDs.  This module is the single, explicit translation
boundary between those two namespaces.

It reuses the existing ``SimulatorBridge`` (``curriculum/simulator.py``) for the
actual id mapping; it does not introduce a competing matcher.  What it adds is
the *mastery-specific* contract:

* the original simulator profile is preserved verbatim for traceability;
* every translated canonical ID is validated against the selected graph version;
* ambiguous, unmapped, deprecated and merged concepts are reported, never
  silently dropped;
* a canonical ID reached by more than one simulator ID is reported as a
  ``duplicate_target_conflict`` and is **not** aggregated (no averaging or
  max-taking) unless an aggregation policy is explicitly approved;
* partial translation is explicit in the result (``is_complete``, ``coverage_rate``,
  ``unresolved_simulator_ids``).

Ownership: Person 2 owns this service and its contract; Person 3 must invoke it
before writing mastery values into canonical learner state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from curriculum.models import ConceptLifecycleStatus, CurriculumGraph
from curriculum.simulator import (
    SimulatorBridge,
    SimulatorMappingEntry,
    SimulatorMappingStatus,
)


class UnknownSimulatorIdError(ValueError):
    """Raised when a simulator ID is not present in the approved vocabulary."""


@dataclass(frozen=True)
class MasteryTranslationEntry:
    """Per-simulator-id translation decision for one mastery value."""

    simulator_concept_id: str
    simulator_mastery: float
    status: str  # translated | ambiguous | unmapped | deprecated_target | invalid_target | duplicate_target_conflict
    canonical_concept_id: Optional[str] = None
    canonical_name: str = ""
    match_strength: float = 0.0
    via_override: bool = False
    reason: str = ""


@dataclass
class MasteryTranslationResult:
    """Result of translating a simulator-keyed mastery profile to canonical IDs."""

    original_profile: Dict[str, float]
    canonical_mastery: Dict[str, float]
    entries: List[MasteryTranslationEntry] = field(default_factory=list)
    graph_curriculum_id: str = ""
    graph_fingerprint: str = ""
    translated_count: int = 0
    total_count: int = 0
    coverage_rate: float = 0.0
    is_complete: bool = False
    unresolved_simulator_ids: List[str] = field(default_factory=list)
    duplicate_targets: List[str] = field(default_factory=list)


def _status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def validate_simulator_ids(
    ids: Iterable[str],
    vocabulary: Any,
) -> List[str]:
    """\n    Validate simulator IDs against an approved vocabulary.

    ``vocabulary`` may be a mapping (concept_id -> index), a path-like/str to an
    ``akt_vocabulary.json`` file, or an object exposing ``concept_to_index``.
    Returns the list of unknown IDs (empty when all are known).  Raises
    ``UnknownSimulatorIdError`` listing them so callers cannot silently proceed
    with an implicit index-zero fallback.
    """
    if hasattr(vocabulary, "concept_to_index"):
        known = set(vocabulary.concept_to_index)
    elif isinstance(vocabulary, Mapping):
        known = set(vocabulary)
        # Accept either a full vocabulary dict or a concept_to_index sub-dict.
        if "concept_to_index" in known and isinstance(vocabulary.get("concept_to_index"), Mapping):
            known = set(vocabulary["concept_to_index"])
    else:
        import json
        from pathlib import Path

        path = Path(vocabulary)
        payload = json.loads(path.read_text(encoding="utf-8"))
        known = set(payload.get("concept_to_index", {}))

    unknown = sorted({str(item).strip() for item in ids if str(item).strip() not in known})
    if unknown:
        raise UnknownSimulatorIdError(
            "Unknown simulator concept ID(s) not present in the approved vocabulary; "
            "refusing to fall back to vocabulary index 0: " + ", ".join(unknown)
        )
    return unknown


def index_to_simulator_id(vocabulary: Any) -> Dict[int, str]:
    """Reverse map: vocabulary index -> simulator concept ID."""
    if hasattr(vocabulary, "concept_to_index"):
        mapping = vocabulary.concept_to_index
    elif isinstance(vocabulary, Mapping) and isinstance(vocabulary.get("concept_to_index"), Mapping):
        mapping = vocabulary["concept_to_index"]
    elif isinstance(vocabulary, Mapping):
        mapping = vocabulary
    else:
        import json
        from pathlib import Path

        payload = json.loads(Path(vocabulary).read_text(encoding="utf-8"))
        mapping = payload.get("concept_to_index", {})
    return {int(idx): str(cid) for cid, idx in mapping.items()}


def mastery_profile_from_indexed_output(
    values: Sequence[float],
    vocabulary: Any,
) -> Dict[str, float]:
    """Convert a model output vector (indexed by vocabulary) into a simulator-keyed profile.

    The index-to-simulator-id mapping is taken from ``vocabulary``; index 0 is
    only used when the vocabulary itself declares concept 0, never as an
    implicit unknown fallback.
    """
    reverse = index_to_simulator_id(vocabulary)
    profile: Dict[str, float] = {}
    for index, value in enumerate(values):
        if index in reverse:
            profile[reverse[index]] = float(value)
    return profile


def translate_mastery_profile(
    profile: Mapping[str, float],
    *,
    graph: CurriculumGraph,
    concept_map: Optional[Mapping[str, str]] = None,
    mapping_entries: Optional[Sequence[SimulatorMappingEntry]] = None,
    bridge: Optional[SimulatorBridge] = None,
) -> MasteryTranslationResult:
    """\n    Translate a simulator-keyed mastery profile into canonical IDs.

    Supply either ``concept_map`` (simulator -> canonical, already approved) or
    ``mapping_entries`` (from ``SimulatorBridge.map_concepts``) or a ``bridge``
    plus the simulator concepts.  When ``mapping_entries`` are supplied they
    drive the per-entry status classification; ``concept_map`` alone classifies
    present IDs as translated.

    Duplicate canonical targets are reported and excluded (no aggregation).
    """
    original = {str(key).strip(): float(value) for key, value in (profile or {}).items()}

    if mapping_entries is None and concept_map is None:
        raise ValueError(
            "translate_mastery_profile requires a concept_map or mapping_entries; "
            "refusing to translate without an approved simulator->canonical mapping"
        )
    status_by_sim: Dict[str, str] = {}
    strength_by_sim: Dict[str, float] = {}
    via_override_by_sim: Dict[str, bool] = {}
    canonical_name_by_sim: Dict[str, str] = {}

    if mapping_entries is not None:
        for entry in mapping_entries:
            status_by_sim[entry.simulator_concept_id] = entry.status.value
            strength_by_sim[entry.simulator_concept_id] = float(entry.match_strength)
            via_override_by_sim[entry.simulator_concept_id] = bool(entry.via_override)
            canonical_name_by_sim[entry.simulator_concept_id] = entry.canonical_name or ""
            if entry.status == SimulatorMappingStatus.MAPPED and entry.canonical_concept_id:
                if concept_map is None:
                    concept_map = {}
                concept_map = dict(concept_map)
                concept_map[entry.simulator_concept_id] = entry.canonical_concept_id
    if concept_map is None:
        concept_map = {}
    concept_map = {str(k).strip(): str(v).strip() for k, v in concept_map.items()}

    # Duplicate-target detection (many sim -> one canonical).
    target_counts: Dict[str, int] = {}
    for sim_id, canonical_id in concept_map.items():
        if sim_id in original:
            target_counts[canonical_id] = target_counts.get(canonical_id, 0) + 1
    duplicate_targets = sorted(cid for cid, count in target_counts.items() if count > 1)

    entries_out: List[MasteryTranslationEntry] = []
    canonical_mastery: Dict[str, float] = {}
    unresolved: List[str] = []

    for sim_id in sorted(original):
        mastery_value = original[sim_id]
        canonical_id = concept_map.get(sim_id)
        entry_status = status_by_sim.get(sim_id)

        if canonical_id is None:
            # Not in concept_map: classify using provided status or unmapped.
            if entry_status in (SimulatorMappingStatus.AMBIGUOUS.value, "ambiguous"):
                status = "ambiguous"
            elif entry_status in (SimulatorMappingStatus.EXCLUDED.value, "excluded"):
                status = "excluded"
            else:
                status = "unmapped"
            entries_out.append(
                MasteryTranslationEntry(
                    simulator_concept_id=sim_id,
                    simulator_mastery=mastery_value,
                    status=status,
                    match_strength=strength_by_sim.get(sim_id, 0.0),
                    via_override=via_override_by_sim.get(sim_id, False),
                    reason=(
                        "no approved simulator->canonical mapping; mastery value preserved "
                        "in original_profile but not translated"
                    ),
                )
            )
            unresolved.append(sim_id)
            continue

        # canonical_id present in concept_map: validate against graph.
        if canonical_id not in graph.concepts:
            entries_out.append(
                MasteryTranslationEntry(
                    simulator_concept_id=sim_id,
                    simulator_mastery=mastery_value,
                    status="invalid_target",
                    canonical_concept_id=canonical_id,
                    match_strength=strength_by_sim.get(sim_id, 0.0),
                    via_override=via_override_by_sim.get(sim_id, False),
                    reason=f"mapped canonical id '{canonical_id}' is not in graph '{graph.curriculum_id}'",
                )
            )
            unresolved.append(sim_id)
            continue

        concept = graph.concepts[canonical_id]
        if _status(concept.status) == ConceptLifecycleStatus.DEPRECATED.value:
            entries_out.append(
                MasteryTranslationEntry(
                    simulator_concept_id=sim_id,
                    simulator_mastery=mastery_value,
                    status="deprecated_target",
                    canonical_concept_id=canonical_id,
                    canonical_name=concept.name,
                    match_strength=strength_by_sim.get(sim_id, 0.0),
                    via_override=via_override_by_sim.get(sim_id, False),
                    reason=f"canonical target '{canonical_id}' is deprecated; not used for mastery",
                )
            )
            unresolved.append(sim_id)
            continue

        if canonical_id in duplicate_targets:
            entries_out.append(
                MasteryTranslationEntry(
                    simulator_concept_id=sim_id,
                    simulator_mastery=mastery_value,
                    status="duplicate_target_conflict",
                    canonical_concept_id=canonical_id,
                    canonical_name=concept.name,
                    match_strength=strength_by_sim.get(sim_id, 0.0),
                    via_override=via_override_by_sim.get(sim_id, False),
                    reason=(
                        f"canonical target '{canonical_id}' is reached by multiple simulator IDs; "
                        "mastery not aggregated (no approved aggregation policy)"
                    ),
                )
            )
            unresolved.append(sim_id)
            continue

        # Successful, unique translation.
        canonical_mastery[canonical_id] = mastery_value
        entries_out.append(
            MasteryTranslationEntry(
                simulator_concept_id=sim_id,
                simulator_mastery=mastery_value,
                status="translated",
                canonical_concept_id=canonical_id,
                canonical_name=concept.name or canonical_name_by_sim.get(sim_id, ""),
                match_strength=strength_by_sim.get(sim_id, 1.0),
                via_override=via_override_by_sim.get(sim_id, False),
                reason="translated via approved simulator->canonical mapping",
            )
        )

    translated_count = len(canonical_mastery)
    total_count = len(original)
    coverage_rate = (translated_count / total_count) if total_count else 1.0
    is_complete = (translated_count == total_count) and total_count >= 0 and not duplicate_targets and not unresolved

    return MasteryTranslationResult(
        original_profile=original,
        canonical_mastery=canonical_mastery,
        entries=entries_out,
        graph_curriculum_id=graph.curriculum_id,
        graph_fingerprint=graph.content_fingerprint(),
        translated_count=translated_count,
        total_count=total_count,
        coverage_rate=round(coverage_rate, 4),
        is_complete=is_complete,
        unresolved_simulator_ids=sorted(unresolved),
        duplicate_targets=duplicate_targets,
    )
