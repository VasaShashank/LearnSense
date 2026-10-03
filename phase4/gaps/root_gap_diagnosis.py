"""
Root-Gap Diagnostic Engine and Information-Theoretic Selection for Phase 4.
Implements Sections 23, 24, 25, and 26 of TAPROOT master specification:
- Competing diagnostic hypotheses across prerequisite ancestor hierarchy
- Mathematically correct Shannon Information Gain (prior entropy - expected posterior entropy)
- Bayesian posterior belief updates upon observation
- DecisionTrace generation for full observability
- Deterministic adaptive policy with deterministic tie-breaking
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import uuid
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem
from phase4.models import DecisionTrace, DiagnosticHypothesis

POLICY_VERSION = "2026.09.0"


def compute_entropy(distribution: Sequence[float]) -> float:
    """
    Computes Shannon entropy in bits for a discrete probability distribution:
    H(P) = - sum_i p_i * log2(p_i)
    Enforces 0 * log2(0) = 0.
    """
    ent = 0.0
    for p in distribution:
        if p > 0.0:
            ent -= p * math.log2(p)
    return round(max(0.0, ent), 6)


class MathematicalInformationGain:
    """
    Exact Shannon Information Gain implementation per Section 25.
    H(H) = - sum_i p(h_i) * log2(p(h_i))
    IG(Q) = H(H) - sum_r P(r|Q) * H(H | r, Q)
    """

    @staticmethod
    def calculate_ig(
        hypotheses: Sequence[DiagnosticHypothesis],
        question: QuestionBankItem,
        prereq_graph: Dict[str, Set[str]],  # concept -> set of its prerequisite concept_ids
        learner_state: Optional[LearnerState] = None,
        guess_prob: float = 0.25,
        slip_prob: float = 0.10,
        question_time_seconds: Optional[float] = None,
    ) -> Tuple[float, float, Dict[str, float]]:
        """
        Calculates exact Shannon Information Gain of candidate question Q against hypotheses H.
        Returns:
            (information_gain, ig_rate, details)
        Raises ValueError if probabilities cannot be reliably determined.
        """
        if not hypotheses:
            raise ValueError("Cannot calculate information gain with empty hypothesis set.")

        priors = [h.prior_probability for h in hypotheses]
        total_p = sum(priors)
        if total_p <= 0.0:
            raise ValueError("Sum of hypothesis prior probabilities must be positive.")

        # Normalize priors if needed
        norm_priors = [p / total_p for p in priors]
        h_prior = compute_entropy(norm_priors)

        if not question.concept_ids:
            raise ValueError(f"Question '{question.question_id}' has no associated concept_ids.")

        q_concept = question.concept_ids[0]

        # Compute transitive ancestor closure for q_concept
        q_ancestors: Set[str] = set()
        stack = list(prereq_graph.get(q_concept, set()))
        while stack:
            parent = stack.pop()
            if parent not in q_ancestors:
                q_ancestors.add(parent)
                stack.extend(prereq_graph.get(parent, set()))

        # For each hypothesis h_i, evaluate P(correct | h_i, Q)
        p_correct_given_h: List[float] = []
        for h in hypotheses:
            gap_concept = h.concept_id

            if q_concept == gap_concept:
                p_c = guess_prob
            elif gap_concept in q_ancestors:
                p_c = guess_prob
            else:
                if learner_state and q_concept in learner_state.concept_states:
                    m = learner_state.concept_states[q_concept].mastery_probability
                    p_c = m * (1.0 - slip_prob) + (1.0 - m) * guess_prob
                else:
                    p_c = 1.0 - slip_prob

            p_correct_given_h.append(max(0.001, min(0.999, p_c)))

        # Marginal response probabilities P(r=correct) and P(r=incorrect)
        p_correct = sum(norm_priors[i] * p_correct_given_h[i] for i in range(len(hypotheses)))
        p_incorrect = 1.0 - p_correct

        # Responses R = [correct, incorrect]
        expected_posterior_entropy = 0.0

        for r_name, p_r, r_is_correct in [("correct", p_correct, True), ("incorrect", p_incorrect, False)]:
            if p_r <= 0.0:
                continue

            # Posterior P(h_i | r, Q) via Bayes' Rule
            posteriors: List[float] = []
            for i in range(len(hypotheses)):
                likelihood = p_correct_given_h[i] if r_is_correct else (1.0 - p_correct_given_h[i])
                posteriors.append(norm_priors[i] * likelihood / p_r)

            post_entropy = compute_entropy(posteriors)
            expected_posterior_entropy += p_r * post_entropy

        information_gain = max(0.0, round(h_prior - expected_posterior_entropy, 6))

        ig_rate = (
            information_gain / question_time_seconds
            if (question_time_seconds and question_time_seconds > 0)
            else information_gain
        )

        details = {
            "prior_entropy": h_prior,
            "expected_posterior_entropy": round(expected_posterior_entropy, 6),
            "marginal_p_correct": round(p_correct, 4),
            "information_gain": information_gain,
        }

        return information_gain, ig_rate, details


class RootGapDiagnoser:
    """
    Orchestrates root-gap diagnosis for failed target concepts.
    Constructs competing hypotheses, ranks questions by mathematical information gain,
    and updates posterior beliefs post-observation.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.75,
        entropy_threshold: float = 0.40,
        policy_version: str = POLICY_VERSION,
    ):
        self.confidence_threshold = confidence_threshold
        self.entropy_threshold = entropy_threshold
        self.policy_version = policy_version

    @staticmethod
    def get_ancestor_prerequisites(
        target_concept_id: str,
        learning_context: LearningContext,
    ) -> List[str]:
        """
        Recursively extracts all ancestor prerequisites of target_concept_id from CKG.
        Returns ordered list from deepest foundations to immediate prerequisites.
        """
        prereq_map: Dict[str, List[str]] = {}
        for link in learning_context.prerequisites:
            prereq_map.setdefault(link.target_concept_id, []).append(link.source_concept_id)

        visited: Set[str] = set()
        ancestors: List[str] = []

        def dfs(curr: str):
            for parent in prereq_map.get(curr, []):
                if parent not in visited:
                    visited.add(parent)
                    dfs(parent)
                    ancestors.append(parent)

        dfs(target_concept_id)
        return ancestors

    def construct_hypotheses(
        self,
        target_concept_id: str,
        learning_context: LearningContext,
        learner_state: LearnerState,
    ) -> List[DiagnosticHypothesis]:
        """
        Constructs mutually exclusive competing hypotheses for a failed target concept:
        H_1 ... H_k: gap in prerequisite ancestors A_1 ... A_k
        H_target: target-specific gap
        Priors are initialized from learner's observed mastery & uncertainty, normalized.
        """
        ancestors = self.get_ancestor_prerequisites(target_concept_id, learning_context)
        candidate_concept_ids = ancestors + [target_concept_id]

        raw_weights = []
        for cid in candidate_concept_ids:
            cstate = learner_state.get_concept_state(cid)
            # Prior weight is high if mastery is low and uncertainty is high, with epsilon baseline
            w = (1.0 - cstate.mastery_probability) * (0.5 + 0.5 * cstate.uncertainty) + 0.1
            raw_weights.append(w)

        total_w = sum(raw_weights)
        hypotheses = []
        for idx, cid in enumerate(candidate_concept_ids):
            p = raw_weights[idx] / total_w
            cview = learning_context.concepts.get(cid)
            cname = cview.canonical_name if cview else cid
            is_target = (cid == target_concept_id)
            desc = f"Target-specific gap in {cname}" if is_target else f"Prerequisite gap in {cname}"

            hypotheses.append(
                DiagnosticHypothesis(
                    hypothesis_id=f"H_{idx + 1}_{cid}",
                    concept_id=cid,
                    prior_probability=round(p, 4),
                    evidence=[desc],
                    posterior_probability=round(p, 4),
                    status="active",
                )
            )

        return hypotheses

    def select_next_question(
        self,
        hypotheses: List[DiagnosticHypothesis],
        candidate_questions: Sequence[QuestionBankItem],
        learning_context: LearningContext,
        learner_state: LearnerState,
        target_concept_id: str,
        asked_question_ids: Optional[Set[str]] = None,
    ) -> Tuple[Optional[QuestionBankItem], Optional[DecisionTrace]]:
        """
        Selects the question that maximizes Information Gain across competing hypotheses.
        Generates and returns an internal DecisionTrace artifact.
        """
        asked = asked_question_ids or set()
        eligible = [q for q in candidate_questions if q.question_id not in asked]
        if not eligible or not hypotheses:
            return None, None

        # Build prerequisite map for Information Gain calculation
        prereq_graph: Dict[str, Set[str]] = {}
        for link in learning_context.prerequisites:
            prereq_graph.setdefault(link.target_concept_id, set()).add(link.source_concept_id)

        scored: List[Tuple[float, QuestionBankItem, Dict[str, Any]]] = []

        for q in eligible:
            try:
                ig, _, details = MathematicalInformationGain.calculate_ig(
                    hypotheses=hypotheses,
                    question=q,
                    prereq_graph=prereq_graph,
                    learner_state=learner_state,
                )
                scored.append((ig, q, details))
            except ValueError:
                continue

        if not scored:
            return None, None

        # Deterministic sorting: primary = information_gain descending, secondary = question_id ascending
        scored.sort(key=lambda item: (-item[0], item[1].question_id))
        best_ig, best_q, best_details = scored[0]

        candidate_actions = [
            {
                "question_id": item[1].question_id,
                "concept_ids": item[1].concept_ids,
                "information_gain": item[0],
            }
            for item in scored
        ]

        decision_trace = DecisionTrace(
            decision_id=f"dec_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc),
            target_concept=target_concept_id,
            candidate_actions=candidate_actions,
            learner_state_snapshot={
                cid: {
                    "mastery": learner_state.get_concept_state(cid).mastery_probability,
                    "uncertainty": learner_state.get_concept_state(cid).uncertainty,
                }
                for cid in set([target_concept_id] + [h.concept_id for h in hypotheses])
            },
            hypotheses=[h.model_dump(mode="json") for h in hypotheses],
            selected_action={
                "question_id": best_q.question_id,
                "concept_ids": best_q.concept_ids,
                "information_gain": best_ig,
            },
            selection_reason=(
                f"Selected question {best_q.question_id} maximizing Shannon Information Gain "
                f"({best_ig:.4f} bits) to discriminate between {len(hypotheses)} competing gap hypotheses."
            ),
            expected_value=best_ig,
            information_gain=best_ig,
            policy_version=self.policy_version,
        )

        return best_q, decision_trace

    def update_beliefs(
        self,
        hypotheses: List[DiagnosticHypothesis],
        question: QuestionBankItem,
        is_correct: bool,
        learning_context: LearningContext,
        guess_prob: float = 0.25,
        slip_prob: float = 0.10,
    ) -> List[DiagnosticHypothesis]:
        """
        Updates posterior probabilities of competing hypotheses via Bayes' theorem.
        """
        prereq_graph: Dict[str, Set[str]] = {}
        for link in learning_context.prerequisites:
            prereq_graph.setdefault(link.target_concept_id, set()).add(link.source_concept_id)

        q_concept = question.concept_ids[0] if question.concept_ids else ""

        # Compute transitive ancestor closure for q_concept
        q_ancestors: Set[str] = set()
        stack = list(prereq_graph.get(q_concept, set()))
        while stack:
            parent = stack.pop()
            if parent not in q_ancestors:
                q_ancestors.add(parent)
                stack.extend(prereq_graph.get(parent, set()))

        # Calculate likelihood P(obs | h_i)
        unnorm_posteriors = []
        for h in hypotheses:
            gap_concept = h.concept_id
            if q_concept == gap_concept or gap_concept in q_ancestors:
                p_c = guess_prob
            else:
                p_c = 1.0 - slip_prob

            likelihood = p_c if is_correct else (1.0 - p_c)
            unnorm_posteriors.append(h.posterior_probability * likelihood)

        total_post = sum(unnorm_posteriors)
        if total_post <= 0:
            total_post = 1.0

        for idx, h in enumerate(hypotheses):
            h.prior_probability = h.posterior_probability
            h.posterior_probability = round(unnorm_posteriors[idx] / total_post, 4)
            ev_str = (
                f"Q({question.question_id}) tested '{q_concept}': "
                f"{'CORRECT' if is_correct else 'INCORRECT'} -> post={h.posterior_probability:.4f}"
            )
            h.evidence.append(ev_str)

            if h.posterior_probability >= self.confidence_threshold:
                h.status = "confirmed"
            elif h.posterior_probability <= 0.05:
                h.status = "eliminated"
            else:
                h.status = "active"

        return hypotheses

    def is_diagnostic_complete(
        self,
        hypotheses: List[DiagnosticHypothesis],
        questions_asked_count: int,
        max_budget: int = 5,
    ) -> Tuple[bool, Optional[DiagnosticHypothesis]]:
        """
        Evaluates stopping criteria:
        1. Top hypothesis posterior >= confidence_threshold
        2. Entropy < entropy_threshold
        3. Question budget reached
        """
        if not hypotheses:
            return True, None

        posteriors = [h.posterior_probability for h in hypotheses]
        current_entropy = compute_entropy(posteriors)

        sorted_h = sorted(hypotheses, key=lambda x: x.posterior_probability, reverse=True)
        top_h = sorted_h[0]

        if top_h.posterior_probability >= self.confidence_threshold:
            return True, top_h

        if current_entropy <= self.entropy_threshold:
            return True, top_h

        if questions_asked_count >= max_budget:
            return True, top_h

        return False, None
