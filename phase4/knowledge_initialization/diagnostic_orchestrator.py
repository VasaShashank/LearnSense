"""
Diagnostic Assessment Orchestrator.
Builds and evaluates initial diagnostic assessments restricted strictly to concepts
marked "KNOW" by the learner.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
import uuid
from phase3.assessment.adaptive_policy import ChapterAssessmentEngine
from phase3.learner.kt import KnowledgeTracer
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem
from phase4.config import phase4_config
from phase4.models import (
    ConfidenceLevel,
    KnowledgeInitializationSession,
    KnowledgeSufficiencyStatus,
    SelfAssessmentStatus,
)

# Deterministic verification priority per (self-assessment, confidence).
# Higher = probe earlier. Unsure+low-confidence first (uncertainty reduction);
# claimed-strong concepts precede unsure ones at equal confidence so that
# verification confirms claimed knowledge before exploring uncertainty.
# Confident-strong (KNOW+HIGH) is still probed, but capped to one quick check.
_VERIFICATION_PRIORITY: Dict[tuple, float] = {
    (SelfAssessmentStatus.UNANSWERED, ConfidenceLevel.LOW): 1.0,
    (SelfAssessmentStatus.KNOW, ConfidenceLevel.LOW): 0.9,
    (SelfAssessmentStatus.KNOW, ConfidenceLevel.MEDIUM): 0.8,
    (SelfAssessmentStatus.KNOW, ConfidenceLevel.HIGH): 0.7,
    (SelfAssessmentStatus.UNANSWERED, ConfidenceLevel.MEDIUM): 0.6,
    (SelfAssessmentStatus.UNANSWERED, ConfidenceLevel.HIGH): 0.55,
}

# Per-concept question caps: confident-strong claims get a single quick check;
# shaky/unsure claims get up to two probes.
_QUESTIONS_PER_CONCEPT: Dict[tuple, int] = {
    (SelfAssessmentStatus.KNOW, ConfidenceLevel.HIGH): 1,
    (SelfAssessmentStatus.KNOW, ConfidenceLevel.MEDIUM): 2,
    (SelfAssessmentStatus.KNOW, ConfidenceLevel.LOW): 2,
    (SelfAssessmentStatus.UNANSWERED, ConfidenceLevel.LOW): 2,
    (SelfAssessmentStatus.UNANSWERED, ConfidenceLevel.MEDIUM): 2,
    (SelfAssessmentStatus.UNANSWERED, ConfidenceLevel.HIGH): 2,
}

CALIBRATION_THRESHOLD = 0.5
STRONG_THRESHOLD = 0.7


class DiagnosticOrchestrator:
    """Orchestrates diagnostic quiz creation for verification concepts and updates initial KT state."""

    def __init__(
        self,
        assessment_engine: Optional[ChapterAssessmentEngine] = None,
        tracer: Optional[KnowledgeTracer] = None,
        config=None,
    ):
        self.assessment_engine = assessment_engine or ChapterAssessmentEngine()
        self.tracer = tracer or KnowledgeTracer()
        self.config = config or phase4_config

    def verification_concepts(self, init_session: KnowledgeInitializationSession) -> List[str]:
        """Concepts the diagnostic verifies: KNOW + UNANSWERED. DONT_KNOW excluded."""
        return list(init_session.know_concept_ids) + [
            cid for cid in init_session.unanswered_concept_ids
            if cid not in init_session.know_concept_ids
        ]

    def concept_priority(self, init_session: KnowledgeInitializationSession, concept_id: str) -> float:
        """Deterministic probe priority from self-assessment x confidence."""
        assessment = init_session.self_assessments.get(concept_id)
        status = assessment.status if assessment else SelfAssessmentStatus.UNANSWERED
        conf = init_session.confidences.get(concept_id, ConfidenceLevel.MEDIUM)
        if isinstance(conf, str):
            try:
                conf = ConfidenceLevel(conf)
            except ValueError:
                conf = ConfidenceLevel.MEDIUM
        return _VERIFICATION_PRIORITY.get((status, conf), 0.5)

    def concept_question_cap(self, init_session: KnowledgeInitializationSession, concept_id: str) -> int:
        assessment = init_session.self_assessments.get(concept_id)
        status = assessment.status if assessment else SelfAssessmentStatus.UNANSWERED
        conf = init_session.confidences.get(concept_id, ConfidenceLevel.MEDIUM)
        if isinstance(conf, str):
            try:
                conf = ConfidenceLevel(conf)
            except ValueError:
                conf = ConfidenceLevel.MEDIUM
        return _QUESTIONS_PER_CONCEPT.get((status, conf), 2)

    def filter_question_bank_for_know_concepts(
        self,
        question_bank: QuestionBank,
        know_concept_ids: List[str],
    ) -> List[QuestionBankItem]:
        """
        Filters candidate questions from Phase 3 QuestionBank that assess ONLY the concepts
        in the verification set (KNOW + UNANSWERED).
        Kept for backward compatibility; new code prefers verification_concepts().
        """
        verify_set = set(know_concept_ids)
        eligible = []
        for q_id, item in question_bank.questions.items():
            # Item is eligible if at least one of its assessed concepts is in verify_set
            item_concepts = set(item.concept_ids)
            if item_concepts.intersection(verify_set):
                eligible.append(item)
        return eligible

    def create_diagnostic_quiz(
        self,
        init_session: KnowledgeInitializationSession,
        question_bank: QuestionBank,
    ) -> List[QuestionBankItem]:
        """
        Creates diagnostic assessment question list over the verification set
        (KNOW + UNANSWERED), ordered by self-assessment x confidence priority
        with per-concept caps. DONT_KNOW concepts are never probed.
        If the verification set is empty, returns [] (no diagnostic run).
        """
        verify_ids = self.verification_concepts(init_session)
        if not verify_ids:
            # No KNOW and no UNANSWERED concepts -> No diagnostic assessment
            init_session.diagnostic_completed = True
            init_session.sufficiency_status = KnowledgeSufficiencyStatus.UNINITIALIZED
            init_session.verify_concept_ids = []
            init_session.diagnostic_priorities = {}
            init_session.diagnostic_question_ids = []
            return []

        verify_set = set(verify_ids)
        candidates = self.filter_question_bank_for_know_concepts(
            question_bank, verify_ids
        )

        if not candidates:
            # Diagnostic has insufficient question candidates -> graceful handling
            init_session.diagnostic_completed = True
            init_session.sufficiency_status = KnowledgeSufficiencyStatus.INSUFFICIENT_EVIDENCE
            init_session.verify_concept_ids = verify_ids
            init_session.diagnostic_priorities = {
                cid: self.concept_priority(init_session, cid) for cid in verify_ids
            }
            init_session.diagnostic_question_ids = []
            return []

        priorities = {cid: self.concept_priority(init_session, cid) for cid in verify_ids}

        # Prioritize candidates by verification priority first, then information
        # gain (coverage of verification concepts + difficulty discriminability).
        def calculate_item_info_gain(item: QuestionBankItem) -> float:
            score = 1.0
            if item.concept_ids:
                matching = [cid for cid in item.concept_ids if cid in verify_set]
                score += len(matching) * 2.0
            diff = getattr(item, "difficulty", 0.5)
            # Maximum informational discriminability around difficulty 0.5
            score += 1.0 - abs(diff - 0.5) * 1.5
            return score

        def sort_key(item: QuestionBankItem) -> tuple:
            item_prio = max(
                (priorities.get(cid, 0.0) for cid in (item.concept_ids or []) if cid in verify_set),
                default=0.0,
            )
            return (item_prio, calculate_item_info_gain(item))

        candidates.sort(key=sort_key, reverse=True)

        # Greedy selection respecting per-concept caps, then the global max.
        caps = {cid: self.concept_question_cap(init_session, cid) for cid in verify_ids}
        used: Dict[str, int] = {cid: 0 for cid in verify_ids}
        selected_questions = []
        max_q = min(self.config.DIAGNOSTIC_MAX_QUESTIONS, len(candidates))
        for item in candidates:
            if len(selected_questions) >= max_q:
                break
            item_concepts = [cid for cid in (item.concept_ids or []) if cid in verify_set]
            if not item_concepts:
                continue
            if all(used.get(cid, 0) >= caps.get(cid, 2) for cid in item_concepts):
                continue
            item_copy = item.model_copy()
            if item_copy.options is not None and "I don't know" not in item_copy.options:
                item_copy.options = list(item_copy.options) + ["I don't know"]
            selected_questions.append(item_copy)
            for cid in item_concepts:
                used[cid] = used.get(cid, 0) + 1

        init_session.diagnostic_session_id = f"diag_{uuid.uuid4().hex[:10]}"
        init_session.verify_concept_ids = verify_ids
        init_session.diagnostic_priorities = priorities
        init_session.diagnostic_question_ids = [q.question_id for q in selected_questions]
        return selected_questions

    # ------------------------------------------------------------------
    # Adaptive (one-question-at-a-time) selection
    # ------------------------------------------------------------------
    #
    # The existing design already ranked the diagnostic with two terms, in this
    # order:
    #   1. deterministic verification priority (self-assessment x confidence)
    #   2. information gain
    # .. but it computed both ONCE, up front, over an unprobed learner, so the
    # order never reacted to the learner's answers. ``select_next_diagnostic_question``
    # keeps the exact same two terms and the same priority-first ordering, but
    # recomputes the information-gain term from the learner's LIVE BKT state
    # after every recorded answer. That is what makes the verification quiz
    # adaptive rather than a fixed list, without inventing a second algorithm.

    def diagnostic_candidate_pool(
        self,
        init_session: KnowledgeInitializationSession,
        question_bank: QuestionBank,
    ) -> List[QuestionBankItem]:
        """Every question that touches the verification set (KNOW + UNANSWERED)."""
        verify_set = set(self.verification_concepts(init_session))
        if not verify_set:
            return []
        return self.filter_question_bank_for_know_concepts(question_bank, list(verify_set))

    def _diagnostic_usage(
        self,
        init_session: KnowledgeInitializationSession,
        question_bank: QuestionBank,
    ) -> Dict[str, int]:
        """Per-concept count of questions actually answered so far."""
        usage: Dict[str, int] = {}
        for q_id in init_session.diagnostic_responses.keys():
            item = question_bank.questions.get(q_id)
            if not item:
                continue
            for cid in item.concept_ids or []:
                usage[cid] = usage.get(cid, 0) + 1
        return usage

    def calculate_mathematical_information_gain(
        self,
        item: QuestionBankItem,
        learner_state: LearnerState,
    ) -> float:
        """
        Computes mathematically exact Shannon Information Gain in bits:
        IG(Q) = H_prior - E[H_posterior]
        via InformationGainPolicy per Section 25.
        """
        from phase3.assessment.information_gain import InformationGainPolicy
        return InformationGainPolicy.calculate_information_gain(item, learner_state).information_gain

    def _verification_probe_policy_score(
        self,
        item: QuestionBankItem,
        learner_state: LearnerState,
        item_concepts: List[str],
    ) -> float:
        """
        Separately named policy feature (Section 4): balances mathematical Shannon
        information gain with unprobed concept coverage.
        """
        shannon_ig = self.calculate_mathematical_information_gain(item, learner_state)
        # Explicit policy coverage factor: prioritize unprobed verification concepts
        unprobed_bonus = 0.0
        for cid in item_concepts:
            cs = learner_state.concept_states.get(cid)
            attempts = cs.attempt_count if cs is not None else 0
            if attempts == 0:
                unprobed_bonus += 0.5
            elif attempts < self.config.MIN_EVIDENCE_COUNT:
                unprobed_bonus += 0.1
        return round(shannon_ig + unprobed_bonus, 6)

    def _live_information_gain(
        self,
        item: QuestionBankItem,
        learner_state: LearnerState,
        item_concepts: List[str],
    ) -> float:
        """Backward-compatible delegate to _verification_probe_policy_score."""
        return self._verification_probe_policy_score(item, learner_state, item_concepts)

    def select_next_diagnostic_question(
        self,
        init_session: KnowledgeInitializationSession,
        question_bank: QuestionBank,
        learner_state: LearnerState,
    ) -> Optional[QuestionBankItem]:
        """
        Pick the next verification question given everything already answered.

        Returns ``None`` when the assessment must stop: the stopping condition is
        unchanged from the batch path (max questions reached, or no candidate
        left that respects the per-concept probe caps).
        """
        verify_ids = self.verification_concepts(init_session)
        if not verify_ids:
            return None
        verify_set = set(verify_ids)
        priorities = {cid: self.concept_priority(init_session, cid) for cid in verify_ids}
        caps = {cid: self.concept_question_cap(init_session, cid) for cid in verify_ids}
        asked = set(init_session.diagnostic_responses.keys())
        usage = self._diagnostic_usage(init_session, question_bank)

        if len(asked) >= self.config.DIAGNOSTIC_MAX_QUESTIONS:
            return None

        best_item: Optional[QuestionBankItem] = None
        best_key: Optional[tuple] = None
        for item in self.diagnostic_candidate_pool(init_session, question_bank):
            if item.question_id in asked:
                continue
            item_concepts = [cid for cid in (item.concept_ids or []) if cid in verify_set]
            if not item_concepts:
                continue
            if all(usage.get(cid, 0) >= caps.get(cid, 2) for cid in item_concepts):
                continue
            key = (
                max((priorities.get(cid, 0.0) for cid in item_concepts), default=0.0),
                self._live_information_gain(item, learner_state, item_concepts),
            )
            # Highest (priority, live information gain) wins. Ties break on the
            # smallest question_id so selection stays reproducible.
            if best_key is None or key > best_key or (key == best_key and item.question_id < best_item.question_id):
                best_key = key
                best_item = item
        return best_item

    def apply_diagnostic_response(
        self,
        init_session: KnowledgeInitializationSession,
        learner_state: LearnerState,
        question_bank: QuestionBank,
        question_id: str,
        correctness: float,
    ) -> Optional[Dict[str, float]]:
        """
        Apply ONE authoritative response to the KnowledgeTracer and record it.

        Idempotent: a ``question_id`` already present in
        ``init_session.diagnostic_responses`` returns ``None`` and never touches
        the learner model, so a duplicated or retried submission cannot double
        count.
        """
        if question_id in init_session.diagnostic_responses:
            return None
        item = question_bank.questions.get(question_id)
        if not item or not item.concept_ids:
            return None
        updates = self.tracer.update(
            learner_state=learner_state,
            concept_ids=item.concept_ids,
            correctness=correctness,
        )
        init_session.diagnostic_responses[question_id] = float(correctness)
        init_session.diagnostic_answer_records[question_id] = {
            "correctness": float(correctness),
            "concept_ids": list(item.concept_ids),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        init_session.diagnostic_answered_count = len(init_session.diagnostic_responses)
        return updates

    def submit_diagnostic_responses(
        self,
        init_session: KnowledgeInitializationSession,
        learner_state: LearnerState,
        question_responses: Dict[str, float],  # question_id -> correctness (0.0 to 1.0)
        question_bank: QuestionBank,
    ) -> Dict[str, float]:
        """
        Applies objective performance responses to Phase 3 KnowledgeTracer to establish initial KT state.
        Returns map of updated concept mastery probabilities.

        Only responses not already recorded on the session are applied to the
        learner model, so calling this twice (batch submit after per-answer
        submits, or a retried submit) never applies the same evidence twice.
        """
        if not question_responses and not init_session.diagnostic_responses:
            init_session.diagnostic_completed = True
            return {}

        total_score = 0.0
        updated_masteries = {}

        for q_id, correctness in question_responses.items():
            total_score += correctness
            concept_updates = self.apply_diagnostic_response(
                init_session, learner_state, question_bank, q_id, correctness
            )
            if concept_updates:
                updated_masteries.update(concept_updates)

        if not init_session.diagnostic_responses:
            # No bank-backed evidence at all -> nothing was scored.
            init_session.diagnostic_completed = True
            return updated_masteries

        # Per-concept evidence is rebuilt from EVERYTHING recorded on the session,
        # so a per-answer run and a batch run reach identical calibration verdicts.
        per_concept_scores: Dict[str, List[float]] = {}
        covered: Set[str] = set()
        for q_id, correctness in init_session.diagnostic_responses.items():
            item = question_bank.questions.get(q_id)
            if item and item.concept_ids:
                covered.update(item.concept_ids)
                for cid in item.concept_ids:
                    per_concept_scores.setdefault(cid, []).append(float(correctness))

        avg_score = round(total_score / len(question_responses), 4)
        # §2 #23: KNOW concepts without direct question coverage are recorded as
        # self_claim_unverified. We do NOT manufacture BKT evidence from the session
        # average — that would fabricate mastery evidence for untested concepts.
        for cid in init_session.know_concept_ids:
            if cid not in updated_masteries:
                # Record the claim without altering BKT mastery probability.
                # The concept state keeps its prior (default 0.15).
                updated_masteries[cid] = learner_state.get_concept_state(cid).mastery_probability
                per_concept_scores.setdefault(cid, [])  # empty = no evidence

        init_session.diagnostic_completed = True
        init_session.diagnostic_score = avg_score
        init_session.sufficiency_status = KnowledgeSufficiencyStatus.INITIALIZED
        init_session.diagnostic_answered_count = len(init_session.diagnostic_responses)

        # Confidence x competence calibration (CC / CI / UC / UI) over the full
        # verification set (KNOW + UNANSWERED).
        calibration: Dict[str, str] = {}
        confirmed: List[str] = []
        contradicted: List[str] = []
        verify_ids = self.verification_concepts(init_session)
        for cid in verify_ids:
            scores = per_concept_scores.get(cid)
            avg = round(sum(scores) / len(scores), 4) if scores else avg_score
            assessment = init_session.self_assessments.get(cid)
            status = assessment.status if assessment else SelfAssessmentStatus.UNANSWERED
            conf = init_session.confidences.get(cid, ConfidenceLevel.MEDIUM)
            if isinstance(conf, str):
                try:
                    conf = ConfidenceLevel(conf)
                except ValueError:
                    conf = ConfidenceLevel.MEDIUM
            confident = conf == ConfidenceLevel.HIGH
            correct = avg >= CALIBRATION_THRESHOLD
            if confident and correct:
                calibration[cid] = "CC"
            elif confident and not correct:
                calibration[cid] = "CI"
            elif not confident and correct:
                calibration[cid] = "UC"
            else:
                calibration[cid] = "UI"
            if status == SelfAssessmentStatus.KNOW and avg < CALIBRATION_THRESHOLD:
                contradicted.append(cid)
            elif status == SelfAssessmentStatus.KNOW and avg >= CALIBRATION_THRESHOLD:
                confirmed.append(cid)
            elif status != SelfAssessmentStatus.KNOW and avg >= STRONG_THRESHOLD:
                contradicted.append(cid)
            elif status != SelfAssessmentStatus.KNOW and avg < CALIBRATION_THRESHOLD:
                confirmed.append(cid)
        init_session.calibration = calibration
        init_session.confirmed_concept_ids = confirmed
        init_session.contradicted_concept_ids = contradicted

        return updated_masteries
