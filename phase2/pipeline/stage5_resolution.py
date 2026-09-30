"""
Stage 5 — Entity Resolution and Canonicalization.
Performs blocking, pairwise scoring, constrained clustering, and merge recording.
Plan §8.
"""

from typing import Dict, List, Tuple
from phase2.models import (
    Concept,
    ConceptMention,
    ConceptTypeEnum,
    ScopeEnum,
    ConceptStatusEnum,
    Alias,
    ConfidenceBreakdown,
    MergeRecord,
    Evidence,
    EvidenceLevelEnum,
    EvidenceKindEnum,
    TextSpan,
)
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext
from phase2.pipeline.stage4_candidates import Stage4ExtractionResult
from phase2.utils.id_generator import generate_concept_id, generate_evidence_id


def _fold_plural(key: str) -> str:
    """Fold a normalized key's final token to a crude singular form.

    Merges clusters like "derivative" / "derivatives" that exact matching
    would otherwise keep as two separate concepts. Conservative on purpose:
    only pure-alphabetic tails longer than 4 chars are folded, so "calculus",
    "news" or short tokens are never mangled.
    """
    parts = key.split()
    if not parts:
        return key
    tail = parts[-1]
    if not tail.isalpha() or len(tail) <= 4:
        return key
    if tail.endswith(("us", "is", "ss")):
        # Latin/Greek endings ("calculus", "analysis", "class") are not plurals.
        return key
    singular = tail
    if tail.endswith("ies") and len(tail) > 5:
        singular = tail[:-3] + "y"
    elif tail.endswith("es") and tail[-3] in "sxz" or tail.endswith(("ches", "shes")):
        singular = tail[:-2]
    elif tail.endswith("s") and not tail.endswith("ss"):
        singular = tail[:-1]
    if singular == tail:
        return key
    return " ".join(parts[:-1] + [singular])


def _merge_plural_variants(
    clusters: Dict[str, List[ConceptMention]],
    canonical_names: Dict[str, str],
) -> None:
    """Fold singular/plural duplicate clusters in place.

    The surviving cluster keeps the most frequent surface form as its
    canonical name (first-seen wins ties), so "Derivative" x3 + "Derivatives"
    x1 canonicalizes to "Derivative" with 4 mentions.
    """
    folded_to_keys: Dict[str, List[str]] = {}
    for key in list(clusters.keys()):
        folded_to_keys.setdefault(_fold_plural(key), []).append(key)
    for folded, keys in folded_to_keys.items():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: (-len(clusters[k]), k))
        keep = keys[0]
        for drop in keys[1:]:
            clusters[keep].extend(clusters.pop(drop))
            canonical_names.pop(drop, None)


def run_stage5_entity_resolution(
    norm_doc: NormalizedDocumentContext,
    candidates: Stage4ExtractionResult
) -> Tuple[List[Concept], List[MergeRecord]]:
    # Group mentions by normalized surface form key
    clusters: Dict[str, List[ConceptMention]] = {}
    canonical_names: Dict[str, str] = {}

    for mention in candidates.mentions:
        raw_name = mention.surface_form
        norm_key = norm_doc.normalize_text_key(raw_name)

        # Expand acronym if present
        if norm_key.upper() in candidates.acronyms:
            raw_name = candidates.acronyms[norm_key.upper()]
            norm_key = norm_doc.normalize_text_key(raw_name)

        if norm_key not in clusters:
            clusters[norm_key] = []
            canonical_names[norm_key] = raw_name
        clusters[norm_key].append(mention)

    # Second pass: merge singular/plural variants of the same term.
    _merge_plural_variants(clusters, canonical_names)

    # Canonical name = most frequent surface form (first-seen wins ties).
    for norm_key, mentions in clusters.items():
        counts: Dict[str, int] = {}
        order: List[str] = []
        for m in mentions:
            if m.surface_form not in counts:
                counts[m.surface_form] = 0
                order.append(m.surface_form)
            counts[m.surface_form] += 1
        canonical_names[norm_key] = max(order, key=lambda name: counts[name])

    concepts: List[Concept] = []
    merge_records: List[MergeRecord] = []

    for norm_key, mentions in clusters.items():
        can_name = canonical_names[norm_key]
        c_id = generate_concept_id(norm_doc.doc_id, can_name)

        mention_ids = []
        ev_ids = []

        for m in mentions:
            m.concept_id = c_id
            mention_ids.append(m.mention_id)

            ev_id = generate_evidence_id(norm_doc.doc_id, m.block_id, m.span.start, m.span.end, "mention")
            ev = Evidence(
                evidence_id=ev_id,
                block_id=m.block_id,
                span=m.span,
                excerpt=m.surface_form,
                level=EvidenceLevelEnum.EXPLICIT,
                kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
                source_confidence=m.confidence
            )
            candidates.evidence.append(ev)
            ev_ids.append(ev_id)

        # Deduplicate evidence IDs
        ev_ids = list(dict.fromkeys(ev_ids))

        concept = Concept(
            concept_id=c_id,
            canonical_name=can_name,
            aliases=[Alias(text=m.surface_form) for m in mentions if m.surface_form != can_name],
            type=ConceptTypeEnum.CONCEPT,
            scope=ScopeEnum.EDUCATIONAL,
            status=ConceptStatusEnum.ACTIVE,
            mention_ids=mention_ids,
            confidence=ConfidenceBreakdown(
                value=0.95,
                components={"extraction": 0.95, "resolution": 0.98}
            ),
            evidence_ids=ev_ids
        )
        concepts.append(concept)

        if len(mentions) > 1:
            m_rec = MergeRecord(
                record_id=f"mr_{c_id}",
                inputs=[m.surface_form for m in mentions],
                canonical_name=can_name,
                signals={"exact_normalized_match": True},
                score=1.0,
                outcome="merged"
            )
            merge_records.append(m_rec)

    return concepts, merge_records
