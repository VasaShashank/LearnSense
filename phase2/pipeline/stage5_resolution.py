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


from phase2.pipeline.semantic_entity_resolver import SemanticEntityResolver


def run_stage5_entity_resolution(
    norm_doc: NormalizedDocumentContext,
    candidates: Stage4ExtractionResult
) -> Tuple[List[Concept], List[MergeRecord]]:
    # Acronym expansion pass before resolution
    for mention in candidates.mentions:
        raw_name = mention.surface_form
        norm_key = norm_doc.normalize_text_key(raw_name)
        if norm_key.upper() in candidates.acronyms:
            mention.surface_form = candidates.acronyms[norm_key.upper()]

    # Execute multi-stage semantic entity resolution
    resolver = SemanticEntityResolver()
    clusters, canonical_names, semantic_merge_records = resolver.resolve_mentions(
        candidates.mentions, candidates.evidence
    )

    # Second pass: merge singular/plural variants of the same term
    _merge_plural_variants(clusters, canonical_names)

    concepts: List[Concept] = []
    merge_records: List[MergeRecord] = list(semantic_merge_records)

    from phase2.pipeline.semantic_validator import SemanticConceptValidator
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

        # Check if an explicit definition was harvested for this concept
        matched_def = None
        for h_def in candidates.harvested_definitions:
            term_h = h_def["term"].strip().lower()
            if (
                term_h == can_name.lower()
                or any(term_h == m.surface_form.lower() for m in mentions)
                or term_h in can_name.lower()
                or can_name.lower() in term_h
            ):
                matched_def = h_def
                break

        if matched_def:
            def_text = matched_def["definition"]
            b_id = matched_def["block_id"]
            ev_id = generate_evidence_id(norm_doc.doc_id, b_id, 0, min(len(def_text), 250), "definition")
            ev = Evidence(
                evidence_id=ev_id,
                block_id=b_id,
                span=TextSpan(start=0, end=min(len(def_text), 250)),
                excerpt=def_text[:250],
                level=EvidenceLevelEnum.EXPLICIT,
                kind=EvidenceKindEnum.DEFINITION_PATTERN,
                source_confidence=0.98,
            )
            candidates.evidence.append(ev)
            ev_ids.append(ev_id)
            ev_ids = list(dict.fromkeys(ev_ids))

        existing = next((c for c in concepts if c.concept_id == c_id), None)
        if existing:
            existing.mention_ids = list(dict.fromkeys(existing.mention_ids + mention_ids))
            existing.evidence_ids = list(dict.fromkeys(existing.evidence_ids + ev_ids))
            new_aliases = [Alias(text=m.surface_form) for m in mentions if m.surface_form != existing.canonical_name]
            existing_alias_texts = {a.text for a in existing.aliases}
            for a in new_aliases:
                if a.text not in existing_alias_texts:
                    existing.aliases.append(a)
                    existing_alias_texts.add(a.text)
            if not existing.description and matched_def:
                existing.description = matched_def["definition"]
        else:
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
                evidence_ids=ev_ids,
                description=matched_def["definition"] if matched_def else "",
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

    # Ensure canonical acronym expansions take precedence for concept names
    acronym_expansions = {norm_doc.normalize_text_key(v): v for v in candidates.acronyms.values()}
    for c in concepts:
        n_k = norm_doc.normalize_text_key(c.canonical_name)
        if n_k in acronym_expansions:
            c.canonical_name = acronym_expansions[n_k]

    return concepts, merge_records
