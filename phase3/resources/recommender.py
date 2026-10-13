"""
Notation-Matched Video and Educational Resource Recommendation Engine.
Part of TAPROOT / LearnSense Phase 3/4 Resource Intelligence (§9).
"""

from typing import Dict, List, Optional
from phase3.resources.models import (
    ResourceRecord,
    ResourceMatchResult,
    RecommendationRankingWeights,
    TranscriptSegment,
)
from phase3.resources.notation_matcher import NotationMatcher


class ResourceRecommender:
    """
    Ranks candidate educational video/audio resources for a learner
    considering notation matching, timestamp jumping, prerequisite support,
    and learner mastery level.
    """

    def __init__(
        self,
        notation_matcher: Optional[NotationMatcher] = None,
        weights: Optional[RecommendationRankingWeights] = None,
    ):
        self.matcher = notation_matcher or NotationMatcher()
        self.weights = weights or RecommendationRankingWeights()

    def recommend_resources(
        self,
        target_concept_id: str,
        target_concept_name: str,
        source_formulas: List[str],
        candidate_resources: List[ResourceRecord],
        learner_mastery: float = 0.30,
        prerequisite_concept_ids: Optional[List[str]] = None,
        subject_domain: Optional[str] = None,
        context_glossary: Optional[Dict[str, str]] = None,
        top_k: int = 5,
    ) -> List[ResourceMatchResult]:
        """
        Ranks and returns top candidate resources for a target concept.
        """
        prereqs = prerequisite_concept_ids or []
        results: List[ResourceMatchResult] = []

        for res in candidate_resources:
            match = self._evaluate_resource(
                resource=res,
                target_concept_id=target_concept_id,
                target_concept_name=target_concept_name,
                source_formulas=source_formulas,
                learner_mastery=learner_mastery,
                prerequisite_concept_ids=prereqs,
                subject_domain=subject_domain,
                context_glossary=context_glossary,
            )
            results.append(match)

        # Sort descending by overall score
        results.sort(key=lambda r: r.overall_score, reverse=True)
        return results[:top_k]

    def _evaluate_resource(
        self,
        resource: ResourceRecord,
        target_concept_id: str,
        target_concept_name: str,
        source_formulas: List[str],
        learner_mastery: float,
        prerequisite_concept_ids: List[str],
        subject_domain: Optional[str],
        context_glossary: Optional[Dict[str, str]] = None,
    ) -> ResourceMatchResult:
        reasons: List[str] = []

        # 1. Concept Coverage & Transcript Timestamp Search
        concept_score, timestamp_sec, end_sec, segment_text = self._find_best_concept_timestamp(
            resource=resource,
            concept_id=target_concept_id,
            concept_name=target_concept_name,
        )
        if concept_score >= 0.8:
            reasons.append(f"Direct coverage of '{target_concept_name}' in transcript")
        elif concept_score >= 0.5:
            reasons.append(f"Resource addresses '{target_concept_name}'")

        # 2. Notation Compatibility
        res_formulas = [f.raw_formula for f in resource.formulas]
        notation_score, notation_expl, matched_formulas = self.matcher.calculate_notation_compatibility(
            source_formulas=source_formulas,
            resource_formulas=res_formulas,
            domain=subject_domain,
            context_glossary=context_glossary,
        )
        if notation_score >= 0.8:
            reasons.append("High notation compatibility with course material")
        if notation_expl and "uses" in notation_expl:
            reasons.append(notation_expl)

        # 3. Prerequisite Relevance
        prereq_score = 0.5
        if prerequisite_concept_ids and resource.prerequisite_concepts:
            covered_prereqs = set(prerequisite_concept_ids) & set(resource.prerequisite_concepts)
            if covered_prereqs:
                prereq_score = min(1.0, 0.5 + 0.25 * len(covered_prereqs))
                reasons.append(f"Reviews foundational concepts: {', '.join(list(covered_prereqs)[:2])}")

        # 4. Pedagogical Fit for Learner Mastery
        # Low mastery (<0.40) benefits from introductory resources (difficulty <= 0.50)
        # High mastery (>=0.70) benefits from deeper resources (difficulty >= 0.60)
        pedagogical_fit = 0.80
        if learner_mastery < 0.40:
            if resource.difficulty <= 0.55:
                pedagogical_fit = 1.0
                reasons.append("Intuitive pacing ideal for initial understanding")
            else:
                pedagogical_fit = 0.60
        elif learner_mastery >= 0.70:
            if resource.difficulty >= 0.50:
                pedagogical_fit = 1.0
                reasons.append("Challenging depth suitable for mastery consolidation")
            else:
                pedagogical_fit = 0.70

        # 5. Evidence Quality
        evidence_quality = resource.confidence * (1.0 if resource.transcript_available else 0.6)

        # Overall Weighted Score
        w = self.weights
        overall = (
            w.concept_match * concept_score
            + w.notation_compatibility * notation_score
            + w.prerequisite_relevance * prereq_score
            + w.learner_mastery_fit * pedagogical_fit
            + w.evidence_quality * evidence_quality
        )
        overall = round(max(0.0, min(1.0, overall)), 3)

        return ResourceMatchResult(
            resource_id=resource.resource_id,
            title=resource.title,
            url=resource.url,
            provider=resource.provider,
            channel=resource.channel,
            duration_seconds=resource.duration_seconds,
            overall_score=overall,
            concept_score=round(concept_score, 2),
            notation_score=round(notation_score, 2),
            prerequisite_score=round(prereq_score, 2),
            pedagogical_fit_score=round(pedagogical_fit, 2),
            recommended_timestamp_seconds=timestamp_sec,
            timestamp_end_seconds=end_sec,
            matched_segment_text=segment_text,
            notation_explanation=notation_expl,
            matched_formulas=matched_formulas,
            match_reasons=reasons,
        )

    def _find_best_concept_timestamp(
        self,
        resource: ResourceRecord,
        concept_id: str,
        concept_name: str,
    ) -> tuple[float, Optional[float], Optional[float], Optional[str]]:
        """
        Locates the best timestamp in the transcript for the target concept.
        Returns (score, start_sec, end_sec, segment_text).
        """
        c_name_lower = concept_name.lower().strip()
        c_words = [w for w in c_name_lower.split() if len(w) > 3]

        best_score = 0.0
        best_seg: Optional[TranscriptSegment] = None

        # Check explicit concept tags first
        if concept_id in resource.concepts_covered or c_name_lower in [c.lower() for c in resource.concepts_covered]:
            best_score = 0.70

        # Check title
        if c_name_lower in resource.title.lower():
            best_score = max(best_score, 0.85)

        # Scan transcript segments for exact or semantic discussion
        if resource.transcript:
            for seg in resource.transcript:
                seg_text_lower = seg.text.lower()
                seg_score = 0.0

                if concept_id in seg.concept_ids:
                    seg_score = 1.0
                elif c_name_lower in seg_text_lower:
                    seg_score = 0.95
                elif c_words and any(w in seg_text_lower for w in c_words):
                    overlap = sum(1 for w in c_words if w in seg_text_lower) / len(c_words)
                    seg_score = 0.50 + 0.30 * overlap

                if seg_score > best_score:
                    best_score = seg_score
                    best_seg = seg

        if best_seg:
            return best_score, best_seg.start_seconds, best_seg.end_seconds, best_seg.text

        # If no transcript segment matched, return whole video
        first_sec = 0.0 if resource.duration_seconds > 0 else None
        return best_score, first_sec, None, None
