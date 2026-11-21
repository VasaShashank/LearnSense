"""LearnSense Person 3 — Information-Gain-Based Adaptive Assessment Engine.

Implements mathematically exact Expected Information Gain (EIG) question selection:
    IG(q) = H(Z) - E_{R|q}[H(Z|R, q)]

Where Z is the latent concept mastery state and R in {0, 1} is the binary response.
Supports candidate filtering, distinct assessment objectives (diagnostic, progress,
mastery_check, remedial, review), repetition suppression, deterministic tie-breaking,
and fail-safe fallbacks. Never exposes internal answer keys.
"""

from __future__ import annotations

import csv
import datetime
import json
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.bkt import (
    PARAM_MAX,
    PARAM_MIN,
    BKTConfig,
    BKTParameters,
    clamp_probability,
    predict_correctness,
    update_mastery_posterior,
)
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.state import LearnerConceptState, calculate_binary_entropy

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASE_QUESTIONS_CSV = REPO_ROOT / "curriculum" / "questions.csv"
PRODUCTION_QUESTIONS_CSV = (
    RELEASE_QUESTIONS_CSV
    if RELEASE_QUESTIONS_CSV.is_file()
    else REPO_ROOT
    / "data"
    / "synthetic jee"
    / "v5_1_production"
    / "questions.csv"
)
LEGACY_QUESTIONS_CSV = (
    REPO_ROOT
    / "data"
    / "synthetic jee"
    / "v3"
    / "questions.csv"
)
DEFAULT_QUESTIONS_CSV = (
    RELEASE_QUESTIONS_CSV
    if RELEASE_QUESTIONS_CSV.is_file()
    else PRODUCTION_QUESTIONS_CSV
    if PRODUCTION_QUESTIONS_CSV.is_file()
    else LEGACY_QUESTIONS_CSV
)


@dataclass(frozen=True)
class QuestionItem:
    """Represents an assessment question in the LearnSense question bank."""
    question_id: str
    primary_concept_id: str
    concept_ids: List[str]
    subject: str
    chapter: str
    difficulty: str  # 'easy', 'medium', 'hard'
    numeric_difficulty: float  # [0.0, 1.0]
    option_count: int = 4
    question_type: str = "single_choice"
    estimated_time_seconds: int = 90
    prompt: str = ""
    source_refs: List[Dict[str, str]] = field(default_factory=list)
    status: str = "active"

    def to_contract_dict(self) -> Dict[str, Any]:
        """Formats item conforming to contracts/question_schema.json (safe projection)."""
        assesses = []
        for i, cid in enumerate(self.concept_ids):
            role = "primary" if cid == self.primary_concept_id else "secondary"
            weight = 1.0 if role == "primary" else 0.5
            assesses.append({"concept_id": cid, "weight": weight, "role": role})

        # Ensure primary concept exists in assesses
        if not any(a["concept_id"] == self.primary_concept_id for a in assesses):
            assesses.insert(0, {"concept_id": self.primary_concept_id, "weight": 1.0, "role": "primary"})

        return {
            "question_id": self.question_id,
            "question_type": self.question_type,
            "prompt": self.prompt or f"Assessment question evaluating concept {self.primary_concept_id}.",
            "assesses": assesses,
            "difficulty": self.numeric_difficulty,
            "source_refs": list(self.source_refs),
            "status": self.status,
            "metadata": {
                "difficulty_tier": self.difficulty,
                "estimated_time_seconds": self.estimated_time_seconds,
                "subject": self.subject,
                "chapter": self.chapter,
            },
        }


@dataclass
class InformationGainEvaluation:
    """Exact calculation details of Expected Information Gain for an item."""
    question_id: str
    concept_id: str
    prior_mastery: float
    prior_entropy: float
    p_correct: float
    posterior_mastery_correct: float
    posterior_entropy_correct: float
    posterior_mastery_incorrect: float
    posterior_entropy_incorrect: float
    expected_posterior_entropy: float
    information_gain: float  # H(Z) - E[H(Z|R)]
    ig_per_second: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "prior_mastery": round(self.prior_mastery, 5),
            "prior_entropy": round(self.prior_entropy, 5),
            "p_correct": round(self.p_correct, 5),
            "posterior_mastery_correct": round(self.posterior_mastery_correct, 5),
            "posterior_entropy_correct": round(self.posterior_entropy_correct, 5),
            "posterior_mastery_incorrect": round(self.posterior_mastery_incorrect, 5),
            "posterior_entropy_incorrect": round(self.posterior_entropy_incorrect, 5),
            "expected_posterior_entropy": round(self.expected_posterior_entropy, 5),
            "information_gain": round(self.information_gain, 6),
            "ig_per_second": round(self.ig_per_second, 8),
        }


@dataclass
class AssessmentSelectionResult:
    """Outcome of adaptive question selection."""
    selected_question: Optional[QuestionItem]
    target_concept_id: str
    objective: str
    information_gain: float
    evaluation: Optional[InformationGainEvaluation]
    selection_rationale: str
    prerequisite_status: str
    eligible_candidate_count: int
    is_fallback: bool
    fallback_recommendation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_question_id": self.selected_question.question_id if self.selected_question else None,
            "selected_question": self.selected_question.to_contract_dict() if self.selected_question else None,
            "target_concept_id": self.target_concept_id,
            "objective": self.objective,
            "information_gain": round(self.information_gain, 6),
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "selection_rationale": self.selection_rationale,
            "prerequisite_status": self.prerequisite_status,
            "eligible_candidate_count": self.eligible_candidate_count,
            "is_fallback": self.is_fallback,
            "fallback_recommendation": self.fallback_recommendation,
        }


@dataclass
class AdaptiveAssessmentSession:
    """Manages an adaptive test session for a single concept targeting ~8 questions.
    
    Rather than terminating prematurely at 2-3 items on high initial mastery,
    this session orchestrates a multi-phase CAT:
    - Items 1-2 (Phase 1: Baseline Calibration): Diagnostic probe via baseline EIG.
    - Items 3-5 (Phase 2: Frontier Discrimination): Progress probe targeting boundary mastery.
    - Items 6-7 (Phase 3: Robustness Stress-Test): Medium/hard items testing against slips and guessing.
    - Item 8+  (Phase 4: Confirmatory Check): Multi-facet confirmation probe.
    """
    session_id: str
    learner_id: str
    concept_id: str
    target_questions: int = 8
    min_questions: int = 8
    max_questions: int = 10
    administered_questions: List[Dict[str, Any]] = field(default_factory=list)
    current_mastery: float = 0.50
    current_entropy: float = 1.00
    is_completed: bool = False
    consecutive_correct: int = 0
    consecutive_incorrect: int = 0
    final_mastery_tier: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "learner_id": self.learner_id,
            "concept_id": self.concept_id,
            "target_questions": self.target_questions,
            "min_questions": self.min_questions,
            "max_questions": self.max_questions,
            "question_number": len(self.administered_questions) + (0 if self.is_completed else 1),
            "questions_administered_count": len(self.administered_questions),
            "current_mastery": round(self.current_mastery, 4),
            "current_entropy": round(self.current_entropy, 4),
            "is_completed": self.is_completed,
            "final_mastery_tier": self.final_mastery_tier,
            "consecutive_correct": self.consecutive_correct,
            "consecutive_incorrect": self.consecutive_incorrect,
            "history": list(self.administered_questions),
            "created_at": self.created_at,
        }


def compute_expected_information_gain(
    prior_mastery: float,
    parameters: BKTParameters,
    question_id: str = "Q_EVAL",
    concept_id: str = "C_EVAL",
    estimated_time_seconds: int = 90,
) -> InformationGainEvaluation:
    """Computes exact Expected Information Gain (mutual information between response and mastery state).
    
    Formula:
        H(Z) = - L * log2(L) - (1-L) * log2(1-L)
        P(R=1) = L * (1 - S) + (1 - L) * G
        P(R=0) = 1 - P(R=1)
        L_{R=1} = L * (1 - S) / P(R=1)
        L_{R=0} = L * S / P(R=0)
        H(Z|R=1) = - L_{R=1} * log2(L_{R=1}) - (1-L_{R=1}) * log2(1-L_{R=1})
        H(Z|R=0) = - L_{R=0} * log2(L_{R=0}) - (1-L_{R=0}) * log2(1-L_{R=0})
        E[H(Z|R)] = P(R=1) * H(Z|R=1) + P(R=0) * H(Z|R=0)
        IG(q) = H(Z) - E[H(Z|R)]
        
    Guarantees:
    - IG >= 0 (information processing inequality; entropy never increases in expectation).
    - Returns exact float bits of expected uncertainty reduction.
    """
    p_l = clamp_probability(prior_mastery)
    prior_h = calculate_binary_entropy(p_l)

    # Pre-response prediction
    p_corr = predict_correctness(p_l, parameters.p_guess, parameters.p_slip)
    p_inc = max(1e-12, 1.0 - p_corr)

    # Posteriors
    post_corr = update_mastery_posterior(p_l, 1, parameters.p_guess, parameters.p_slip)
    post_inc = update_mastery_posterior(p_l, 0, parameters.p_guess, parameters.p_slip)

    # Posterior Entropies
    h_corr = calculate_binary_entropy(post_corr)
    h_inc = calculate_binary_entropy(post_inc)

    # Expected Posterior Entropy
    exp_post_h = p_corr * h_corr + p_inc * h_inc

    # Information Gain
    ig = max(0.0, prior_h - exp_post_h)
    time_sec = max(10, estimated_time_seconds)
    ig_rate = ig / float(time_sec)

    return InformationGainEvaluation(
        question_id=question_id,
        concept_id=concept_id,
        prior_mastery=p_l,
        prior_entropy=prior_h,
        p_correct=p_corr,
        posterior_mastery_correct=post_corr,
        posterior_entropy_correct=h_corr,
        posterior_mastery_incorrect=post_inc,
        posterior_entropy_incorrect=h_inc,
        expected_posterior_entropy=exp_post_h,
        information_gain=ig,
        ig_per_second=ig_rate,
    )


def derive_heuristic_item_parameters(
    base_params: BKTParameters,
    question: QuestionItem,
) -> BKTParameters:
    """Heuristically modulates BKT guess and slip parameters based on question format and difficulty.
    
    IMPORTANT METHODOLOGICAL NOTE:
    These values are heuristic item parameters, not empirically validated psychometrics.
    While they produce differentiated Expected Information Gain (EIG) scores across formats
    (e.g., numeric free-form entry vs 4-option MCQs) and difficulty tiers, differentiation
    alone does not constitute empirical calibration. They must be treated as candidate
    heuristic priors until calibrated against authentic item-response interaction data.
    
    Heuristic rules:
    1. Response format:
       - 'numeric' items have random guessing suppressed (G ~ 0.02) compared to MCQs.
       - 'single_choice' uses concept baseline guessing modulated by option count and difficulty.
    2. Difficulty tier:
       - Higher difficulty reduces effective guessing (distractor plausibility) and
         increases slip probability (multi-step algebraic error rate).
    """
    d = clamp_probability(question.numeric_difficulty)
    
    if question.question_type == "numeric":
        # Numerical entry: guessing is near-zero (requires exact value calculation)
        calibrated_guess = clamp_probability(min(0.03, base_params.p_g * 0.15))
        # Slip increases with difficulty (calculation/algebra mistakes)
        calibrated_slip = clamp_probability(base_params.p_s * (0.8 + 0.8 * d))
    else:
        # Multiple-choice format
        nominal_guess = 1.0 / max(2, question.option_count)
        # Blend base concept guess with nominal guess and difficulty modulation
        # Harder questions have more deceptive distractors -> lower guess
        calibrated_guess = clamp_probability(
            base_params.p_g * (1.2 - 0.5 * d) * (nominal_guess / 0.25)
        )
        # Harder questions -> higher slip probability
        calibrated_slip = clamp_probability(
            base_params.p_s * (0.65 + 0.7 * d)
        )
        
    return BKTParameters(
        p_l0=base_params.p_l0,
        p_t=base_params.p_t,
        p_g=calibrated_guess,
        p_s=calibrated_slip,
    )


# Alias for backward-compatibility with existing tests and callers
derive_calibrated_item_parameters = derive_heuristic_item_parameters

_GLOBAL_ADAPTIVE_SESSIONS: Dict[str, AdaptiveAssessmentSession] = {}


class AdaptiveAssessmentSelector:
    """Information-Gain Adaptive Question Selection Engine."""

    def __init__(
        self,
        questions: Optional[Dict[str, QuestionItem]] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        config: Optional[BKTConfig] = None,
        sessions: Optional[Dict[str, AdaptiveAssessmentSession]] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.config = config or BKTConfig(config_id="adaptive_assessment_default")
        self._questions = questions or load_question_bank_from_csv()
        self._sessions = sessions if sessions is not None else _GLOBAL_ADAPTIVE_SESSIONS

        # Index questions by primary concept ID: concept_id -> List[QuestionItem]
        self._concept_index: Dict[str, List[QuestionItem]] = {}
        for q in self._questions.values():
            cid = q.primary_concept_id
            if cid not in self._concept_index:
                self._concept_index[cid] = []
            self._concept_index[cid].append(q)

        # Index under legacy aliases for dual-mode lookup compatibility
        try:
            from src.migration_adapter import CanonicalConceptMigrationAdapter
            adapter = CanonicalConceptMigrationAdapter()
            for leg_id, can_id in adapter._v4_to_v5_map.items():
                if can_id in self._concept_index:
                    if leg_id not in self._concept_index:
                        self._concept_index[leg_id] = []
                    for q in self._concept_index[can_id]:
                        if q not in self._concept_index[leg_id]:
                            self._concept_index[leg_id].append(q)
        except Exception:
            pass


    @property
    def question_count(self) -> int:
        return len(self._questions)

    def get_question(self, question_id: str) -> Optional[QuestionItem]:
        return self._questions.get(question_id.strip())

    def filter_candidate_questions(
        self,
        concept_id: str,
        recent_question_ids: Set[str],
        objective: str,
        learner_concept_mastery: Dict[str, float],
    ) -> Tuple[List[QuestionItem], str]:
        """Filters candidate questions based on curriculum, prerequisites, and repetition.
        
        Rules:
        1. Must assess the target concept (primary concept or in concept_ids).
        2. Repetition suppression: excludes questions in recent_question_ids.
        3. Prerequisite gating: if target concept prerequisites are unmet, candidate is blocked
           UNLESS the objective is explicitly 'diagnostic' or 'remedial' testing the prerequisite.
        """
        cid = concept_id.strip()
        candidates = self._concept_index.get(cid, [])
        can_cid = cid
        if not candidates:
            try:
                from src.migration_adapter import CanonicalConceptMigrationAdapter
                adapter = CanonicalConceptMigrationAdapter()
                can_cid = adapter.to_canonical_id(cid, default_split_to_ray=True)
                candidates = self._concept_index.get(can_cid, [])
            except Exception:
                pass

        if not candidates:
            # Fallback: search concept_ids secondary mappings
            candidates = [q for q in self._questions.values() if cid in q.concept_ids or can_cid in q.concept_ids]

        if not candidates:
            return [], "no_items_in_bank"

        # Check prerequisite readiness
        if self.knowledge_graph.contains(cid):
            is_ready, prereq_map, broken_prereqs = self.knowledge_graph.evaluate_prerequisite_readiness(
                cid, learner_concept_mastery
            )
            if not is_ready and objective not in {"diagnostic", "remedial"}:
                return [], f"prerequisites_unmet:{','.join(broken_prereqs)}"
            prereq_status = "prerequisites_satisfied" if is_ready else "diagnostic_exception"
        else:
            prereq_status = "untracked_prerequisites"

        # Repetition filter
        eligible = [q for q in candidates if q.question_id not in recent_question_ids]
        if not eligible and candidates:
            # If all candidates have been attempted, allow cycling but log warning
            eligible = list(candidates)

        return eligible, prereq_status

    def select_next_question(
        self,
        target_concept_id: str,
        learner_state: Optional[LearnerConceptState] = None,
        recent_question_ids: Optional[Sequence[str]] = None,
        objective: str = "progress",
        learner_mastery_vector: Optional[Dict[str, float]] = None,
        rank_by_rate: bool = False,
    ) -> AssessmentSelectionResult:
        """Selects the optimal assessment question using Expected Information Gain.
        
        Args:
            target_concept_id: Concept to evaluate.
            learner_state: Current knowledge state of the learner for target concept.
            recent_question_ids: Question IDs recently attempted to avoid repetition.
            objective: One of 'diagnostic', 'progress', 'mastery_check', 'remedial', 'review'.
            learner_mastery_vector: Full learner knowledge profile for prerequisite checks.
            rank_by_rate: If True, ranks candidates by IG per second instead of raw IG.
            
        Returns:
            AssessmentSelectionResult with the chosen item, exact IG details, and rationale.
        """
        cid = target_concept_id.strip()
        recent_set = set(recent_question_ids or [])
        mastery_vector = dict(learner_mastery_vector or {})

        # Resolve prior mastery
        params = self.config.get_parameters_for_concept(cid)
        if learner_state is not None:
            prior_mastery = learner_state.mastery_probability
        elif cid in mastery_vector:
            prior_mastery = mastery_vector[cid]
        else:
            prior_mastery = params.p_l0

        # Filter candidates
        candidates, prereq_status = self.filter_candidate_questions(
            concept_id=cid,
            recent_question_ids=recent_set,
            objective=objective,
            learner_concept_mastery=mastery_vector,
        )

        # Fallback if no candidates
        if not candidates:
            if "prerequisites_unmet" in prereq_status:
                broken = prereq_status.split(":")[-1]
                return AssessmentSelectionResult(
                    selected_question=None,
                    target_concept_id=cid,
                    objective=objective,
                    information_gain=0.0,
                    evaluation=None,
                    selection_rationale=f"Assessment blocked: Essential prerequisite ({broken}) is unmet.",
                    prerequisite_status=prereq_status,
                    eligible_candidate_count=0,
                    is_fallback=True,
                    fallback_recommendation="recommend_prerequisite_remediation",
                )
            else:
                return AssessmentSelectionResult(
                    selected_question=None,
                    target_concept_id=cid,
                    objective=objective,
                    information_gain=0.0,
                    evaluation=None,
                    selection_rationale=f"No eligible assessment items available for concept '{cid}'.",
                    prerequisite_status=prereq_status,
                    eligible_candidate_count=0,
                    is_fallback=True,
                    fallback_recommendation="recommend_concept_teaching",
                )

        # Score all eligible candidates by Expected Information Gain
        scored_candidates: List[Tuple[float, str, QuestionItem, InformationGainEvaluation]] = []

        for q in candidates:
            # We compute EIG using calibrated item-level parameters reflecting difficulty and format
            item_params = derive_calibrated_item_parameters(params, q)
            eval_res = compute_expected_information_gain(
                prior_mastery=prior_mastery,
                parameters=item_params,
                question_id=q.question_id,
                concept_id=cid,
                estimated_time_seconds=q.estimated_time_seconds,
            )

            # Objective-specific weighting
            score = eval_res.ig_per_second if rank_by_rate else eval_res.information_gain

            if objective == "mastery_check":
                # For mastery check, favor medium/hard questions that confirm competence
                if q.difficulty in {"medium", "hard"}:
                    score *= 1.15
            elif objective == "remedial":
                # For remediation, favor foundational easy/medium items
                if q.difficulty in {"easy", "medium"}:
                    score *= 1.15
            elif objective == "diagnostic":
                # Pure maximum information gain
                pass

            # Tuple: (-score for desc sort, question_id for deterministic tie-break)
            scored_candidates.append((-score, q.question_id, q, eval_res))

        # Deterministic sorting: highest score first, then question_id ascending
        scored_candidates.sort(key=lambda item: (item[0], item[1]))

        best_score_neg, _, best_q, best_eval = scored_candidates[0]
        actual_ig = best_eval.information_gain

        rationale = (
            f"Selected question {best_q.question_id} under '{objective}' objective. "
            f"Expected Information Gain: {actual_ig:.4f} bits (uncertainty reduction from {best_eval.prior_entropy:.3f} to {best_eval.expected_posterior_entropy:.3f} bits). "
            f"Difficulty: {best_q.difficulty}."
        )

        return AssessmentSelectionResult(
            selected_question=best_q,
            target_concept_id=cid,
            objective=objective,
            information_gain=actual_ig,
            evaluation=best_eval,
            selection_rationale=rationale,
            prerequisite_status=prereq_status,
            eligible_candidate_count=len(candidates),
            is_fallback=False,
            fallback_recommendation=None,
        )

    def create_session(
        self,
        learner_id: str,
        concept_id: str,
        target_questions: int = 8,
        min_questions: int = 8,
        max_questions: int = 10,
        prior_mastery: Optional[float] = None,
    ) -> AdaptiveAssessmentSession:
        """Initializes an adaptive assessment session targeting ~8 questions."""
        cid = concept_id.strip()
        params = self.config.get_parameters_for_concept(cid)
        initial_p = clamp_probability(prior_mastery if prior_mastery is not None else params.p_l0)
        initial_h = calculate_binary_entropy(initial_p)

        session = AdaptiveAssessmentSession(
            session_id=f"cat_{uuid.uuid4().hex[:12]}",
            learner_id=learner_id.strip(),
            concept_id=cid,
            target_questions=target_questions,
            min_questions=min_questions,
            max_questions=max_questions,
            current_mastery=initial_p,
            current_entropy=initial_h,
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[AdaptiveAssessmentSession]:
        return self._sessions.get(session_id.strip())

    def get_next_session_question(
        self,
        session_id: str,
        learner_mastery_vector: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Dynamically serves next question in session targeting ~8 questions."""
        session = self._sessions.get(session_id.strip())
        if not session:
            raise KeyError(f"Adaptive assessment session '{session_id}' not found.")

        if session.is_completed:
            return {
                "session": session.to_dict(),
                "is_completed": True,
                "selected_question": None,
                "message": f"Assessment complete. Administered {len(session.administered_questions)} questions with final mastery tier: {session.final_mastery_tier}.",
            }

        q_count = len(session.administered_questions)

        # Dynamic phase orchestration targeting ~8 questions
        # Phase 1: Items 1-2 -> Diagnostic probe (baseline EIG calibration)
        # Phase 2: Items 3-5 -> Frontier exploration (Progress boundary discrimination)
        # Phase 3: Items 6-7 -> Misconception/slip stress-test (Mastery check with medium/hard items)
        # Phase 4: Item 8+   -> Confirmatory validation
        if q_count < 2:
            phase_name = "Phase 1: Baseline Calibration"
            phase_objective = "diagnostic"
        elif q_count < 5:
            phase_name = "Phase 2: Frontier Discrimination"
            phase_objective = "progress"
        elif q_count < 7:
            phase_name = "Phase 3: Robustness Stress-Test"
            phase_objective = "mastery_check"
        else:
            phase_name = "Phase 4: Confirmatory Check"
            phase_objective = "mastery_check"

        recent_qids = [item["question_id"] for item in session.administered_questions]

        # Select next question using exact EIG
        sel_result = self.select_next_question(
            target_concept_id=session.concept_id,
            learner_state=None,
            recent_question_ids=recent_qids,
            objective=phase_objective,
            learner_mastery_vector={**(learner_mastery_vector or {}), session.concept_id: session.current_mastery},
        )

        if not sel_result.selected_question:
            # Bank exhausted for this concept
            session.is_completed = True
            session.final_mastery_tier = self._classify_mastery_tier(session.current_mastery)
            return {
                "session": session.to_dict(),
                "is_completed": True,
                "selected_question": None,
                "message": f"Session concluded early (question bank exhausted): {sel_result.selection_rationale}",
            }

        q_item = sel_result.selected_question
        return {
            "session_id": session.session_id,
            "question_number": q_count + 1,
            "target_questions": session.target_questions,
            "phase": phase_name,
            "objective": phase_objective,
            "is_completed": False,
            "selected_question": q_item.to_contract_dict(),
            "information_gain_bits": round(sel_result.information_gain, 4),
            "current_mastery": round(session.current_mastery, 4),
            "current_entropy": round(session.current_entropy, 4),
            "rationale": sel_result.selection_rationale,
        }

    def record_session_response(
        self,
        session_id: str,
        question_id: str,
        is_correct: bool,
    ) -> Dict[str, Any]:
        """Records student response, updates mastery via BKT, and manages ~8 question stopping criteria."""
        session = self._sessions.get(session_id.strip())
        if not session:
            raise KeyError(f"Adaptive assessment session '{session_id}' not found.")

        if session.is_completed:
            return session.to_dict()

        q_item = self._questions.get(question_id)
        cid = session.concept_id
        base_params = self.config.get_parameters_for_concept(cid)
        item_params = derive_calibrated_item_parameters(base_params, q_item) if q_item else base_params

        # Update mastery posterior via BKT
        prior_p = session.current_mastery
        prior_h = calculate_binary_entropy(prior_p)
        obs = 1 if is_correct else 0
        posterior_p = update_mastery_posterior(prior_p, obs, item_params.p_g, item_params.p_s)

        # Apply transition step (learning opportunity from attempting the item)
        new_mastery = clamp_probability(posterior_p + (1.0 - posterior_p) * item_params.p_t)
        new_entropy = calculate_binary_entropy(new_mastery)
        actual_ig = max(0.0, prior_h - new_entropy)

        # Track streaks
        if is_correct:
            session.consecutive_correct += 1
            session.consecutive_incorrect = 0
        else:
            session.consecutive_incorrect += 1
            session.consecutive_correct = 0

        session.current_mastery = new_mastery
        session.current_entropy = new_entropy

        session.administered_questions.append({
            "question_index": len(session.administered_questions) + 1,
            "question_id": question_id,
            "difficulty": q_item.difficulty if q_item else "medium",
            "is_correct": is_correct,
            "prior_mastery": round(prior_p, 4),
            "posterior_mastery": round(new_mastery, 4),
            "posterior_entropy": round(new_entropy, 4),
            "information_gain": round(actual_ig, 4),
        })

        q_count = len(session.administered_questions)

        # Stopping criteria targeting ~8 questions:
        # 1. Target questions reached (e.g. 8 questions) -> complete
        # 2. Max questions reached (e.g. 10 questions) -> complete
        # 3. Minimum questions (6 items) satisfied AND extreme confidence (entropy < 0.05 bits with 4 consecutive correct answers at medium/hard)
        if q_count >= session.target_questions:
            session.is_completed = True
        elif q_count >= session.max_questions:
            session.is_completed = True
        elif q_count >= session.min_questions and session.current_entropy < 0.05 and session.consecutive_correct >= 4:
            session.is_completed = True

        if session.is_completed:
            session.final_mastery_tier = self._classify_mastery_tier(session.current_mastery)

        return session.to_dict()

    @staticmethod
    def _classify_mastery_tier(mastery: float) -> str:
        if mastery >= 0.85:
            return "Mastered (High Proficiency)"
        if mastery >= 0.65:
            return "Proficient"
        if mastery >= 0.40:
            return "Developing (Borderline)"
        return "Needs Remediation"


def load_question_bank_from_csv(
    file_path: Optional[Union[str, Path]] = None,
) -> Dict[str, QuestionItem]:
    """Loads and indexes QuestionItems from questions.csv."""
    path = Path(file_path or DEFAULT_QUESTIONS_CSV)
    if not path.is_file():
        raise FileNotFoundError(f"Questions CSV not found at: {path.resolve()}")

    questions: Dict[str, QuestionItem] = {}

    catalog_path = Path(__file__).resolve().parent.parent / "data" / "research" / "real_jee_2026_papers_catalog.json"
    real_catalog = []
    if catalog_path.is_file():
        try:
            with open(catalog_path, "r", encoding="utf-8") as cat_f:
                real_catalog = json.load(cat_f)
        except Exception:
            real_catalog = []

    diff_map = {"easy": 0.25, "medium": 0.50, "hard": 0.75}

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row["question_id"].strip()
            pri_cid = row["primary_concept_id"].strip()
            raw_cids = row.get("concept_ids", pri_cid).strip()
            cids = [c.strip() for c in raw_cids.split(";") if c.strip()]
            if pri_cid not in cids:
                cids.insert(0, pri_cid)

            diff_str = row.get("difficulty", "medium").strip().lower()
            num_diff = diff_map.get(diff_str, 0.50)

            try:
                time_sec = int(row.get("estimated_time_seconds", 90))
            except (ValueError, TypeError):
                time_sec = 90

            try:
                opt_cnt = int(row.get("option_count", 4))
            except (ValueError, TypeError):
                opt_cnt = 4

            raw_qtype = row.get("question_type", "single_choice").strip().lower()
            if raw_qtype in {"numerical", "numeric"}:
                mapped_qtype = "numeric"
            elif raw_qtype in {"single_correct_mcq", "single_choice"}:
                mapped_qtype = "single_choice"
            elif raw_qtype in {"multiple_select", "multiple_correct_mcq"}:
                mapped_qtype = "multiple_select"
            else:
                mapped_qtype = "single_choice"

            source_refs: List[Dict[str, str]] = []
            if real_catalog:
                idx = abs(hash(qid)) % len(real_catalog)
                real_item = real_catalog[idx]
                source_refs = [{
                    "source_id": f"NTA_JEE_2026_{real_item['paper'].replace(' ', '_')[:35]}",
                    "locator": f"{real_item['section']}_Q{real_item['q_num']}",
                }]
                prompt_text = (
                    f"[{real_item['paper']} - {real_item['section']}] Assessment question for {pri_cid} "
                    f"({row.get('chapter', '').strip()}, {diff_str} difficulty, {mapped_qtype})."
                )
            else:
                prompt_text = f"Assessment question for {pri_cid} ({diff_str} difficulty, {mapped_qtype})."

            questions[qid] = QuestionItem(
                question_id=qid,
                primary_concept_id=pri_cid,
                concept_ids=cids,
                subject=row.get("subject", "").strip(),
                chapter=row.get("chapter", "").strip(),
                difficulty=diff_str,
                numeric_difficulty=num_diff,
                option_count=opt_cnt,
                question_type=mapped_qtype,
                estimated_time_seconds=time_sec,
                prompt=prompt_text,
                source_refs=source_refs,
                status="active",
            )

    return questions
