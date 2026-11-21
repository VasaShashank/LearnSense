"""LearnSense Person 3 — Exam-Readiness Estimation Engine.

Evaluates student exam readiness against a structured exam blueprint with weighted topics,
explicitly distinguishing exam preparation from general concept mastery:
1. Multi-factor evidential synthesis: Combines BKT latent mastery P(L), mastery uncertainty U,
   personalized memory retention R(t), and unseen transfer verification into a transparent index.
2. Distinct coverage reporting: Separates evidence coverage (fraction of blueprint concepts assessed)
   from the readiness score itself.
3. Diagnostic risk identification: Identifies unassessed topics, weak concepts, stale retention,
   transfer gaps, and active misconceptions.
4. Scientific and calibration guardrails:
   - Clearly labeled as a provisional heuristic readiness estimate.
   - Sets is_calibrated_probability = False; explicitly disclaims passing probability claims.
   - Does NOT mutate BKT knowledge states or predictive baseline parameters.
"""

from __future__ import annotations

import copy
import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.misconceptions import MisconceptionTracker
from src.retention import PersonalizedRetentionModel
from src.state import LearnerConceptState, LearnerStateService
from src.transfer import MasteryTransferVerifier
from src.uncertainty import MasteryUncertaintyEvaluator


@dataclass
class TopicReadinessSummary:
    """Readiness breakdown for a single topic or domain within an exam blueprint."""
    topic_id: str
    weight: float
    concept_ids: List[str]
    assessed_concept_count: int
    mean_mastery: float
    mean_uncertainty: float
    mean_retention: float
    transfer_verified_count: int
    topic_readiness_score: float
    status: str  # 'unassessed', 'critical_gap', 'developing', 'prepared'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExamReadinessReport:
    """Comprehensive, explainable exam readiness assessment conforming to LearnSense standards."""
    report_id: str
    learner_id: str
    blueprint_id: str
    provisional_readiness_score: float  # [0.0, 1.0]
    readiness_level: str  # 'not_ready', 'emerging', 'progressing', 'ready_with_caution', 'exam_ready'
    is_calibrated_probability: bool  # strictly False
    evidence_coverage: Dict[str, Any]
    topic_breakdown: List[TopicReadinessSummary]
    unassessed_concepts: List[str]
    weak_concepts: List[str]
    stale_retention_concepts: List[str]
    transfer_gap_concepts: List[str]
    key_risk_factors: List[str]
    key_strengths: List[str]
    formula_documentation: str
    limitations_disclaimer: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "learner_id": self.learner_id,
            "blueprint_id": self.blueprint_id,
            "provisional_readiness_score": round(self.provisional_readiness_score, 4),
            "readiness_level": self.readiness_level,
            "is_calibrated_probability": self.is_calibrated_probability,
            "evidence_coverage": copy.deepcopy(self.evidence_coverage),
            "topic_breakdown": [t.to_dict() for t in self.topic_breakdown],
            "unassessed_concepts": list(self.unassessed_concepts),
            "weak_concepts": list(self.weak_concepts),
            "stale_retention_concepts": list(self.stale_retention_concepts),
            "transfer_gap_concepts": list(self.transfer_gap_concepts),
            "key_risk_factors": list(self.key_risk_factors),
            "key_strengths": list(self.key_strengths),
            "formula_documentation": self.formula_documentation,
            "limitations_disclaimer": self.limitations_disclaimer,
            "created_at": self.created_at,
        }


DEFAULT_JEE_BLUEPRINT: Dict[str, Any] = {
    "blueprint_id": "JEE_PILOT_MECHANICS_V1",
    "topics": [
        {
            "topic_id": "Kinematics_and_Vectors",
            "weight": 0.35,
            "concept_ids": ["PHY_VEC", "PHY_KIN", "PHY_MOT", "PHY_PRJ"],
        },
        {
            "topic_id": "Dynamics_and_Laws_of_Motion",
            "weight": 0.40,
            "concept_ids": ["PHY_NLM", "PHY_FRC", "PHY_WKP", "PHY_CIR"],
        },
        {
            "topic_id": "Conservation_and_Collisions",
            "weight": 0.25,
            "concept_ids": ["PHY_MOM", "PHY_COL"],
        },
    ],
}


class ExamReadinessEstimator:
    """Evaluates multi-factor, evidence-backed exam readiness against exam blueprints."""

    def __init__(
        self,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        retention_model: Optional[PersonalizedRetentionModel] = None,
        transfer_verifier: Optional[MasteryTransferVerifier] = None,
        misconception_tracker: Optional[MisconceptionTracker] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.retention_model = retention_model
        self.transfer_verifier = transfer_verifier
        self.misconception_tracker = misconception_tracker

    def estimate_readiness(
        self,
        learner_id: str,
        state_service: LearnerStateService,
        blueprint: Optional[Dict[str, Any]] = None,
        as_of_time: Optional[str] = None,
    ) -> ExamReadinessReport:
        """Calculates a transparent exam readiness assessment against an exam blueprint."""
        lid = str(learner_id).strip()
        now_iso = as_of_time or datetime.datetime.now(datetime.timezone.utc).isoformat()
        report_id = f"READ_{uuid.uuid4().hex[:12]}"

        bp = blueprint or DEFAULT_JEE_BLUEPRINT
        blueprint_id = str(bp.get("blueprint_id", "CUSTOM_EXAM_BLUEPRINT"))
        raw_topics = bp.get("topics", [])

        # Normalize topic blueprint format
        normalized_topics: List[Dict[str, Any]] = []
        if isinstance(raw_topics, list) and raw_topics:
            for item in raw_topics:
                if isinstance(item, dict):
                    t_id = str(item.get("topic_id", "unnamed_topic"))
                    w = float(item.get("weight", 1.0))
                    c_ids = [str(c).strip() for c in item.get("concept_ids", []) if str(c).strip()]
                    normalized_topics.append({"topic_id": t_id, "weight": w, "concept_ids": c_ids})
        elif isinstance(bp.get("weights"), dict):
            # Flat concept weights format: {"PHY_KIN": 0.5, "PHY_NLM": 0.5}
            for cid, w in bp["weights"].items():
                normalized_topics.append({
                    "topic_id": cid,
                    "weight": float(w),
                    "concept_ids": [cid],
                })

        if not normalized_topics:
            raise ValueError("Invalid exam blueprint: blueprint must define non-empty topics with concept mappings.")

        # Normalize weights so sum equals 1.0
        total_w = sum(t["weight"] for t in normalized_topics)
        if total_w <= 0.0:
            raise ValueError("Invalid exam blueprint: total topic weight must be strictly positive.")
        for t in normalized_topics:
            t["weight"] = t["weight"] / total_w

        all_blueprint_cids: Set[str] = set()
        for t in normalized_topics:
            all_blueprint_cids.update(t["concept_ids"])

        all_states = state_service.get_all_learner_states(lid)
        mastery_vector = state_service.get_learner_mastery_vector(lid)

        total_blueprint_concepts = len(all_blueprint_cids)
        assessed_cids = {cid for cid in all_blueprint_cids if cid in all_states and all_states[cid].evidence_count > 0}
        assessed_ratio = (len(assessed_cids) / total_blueprint_concepts) if total_blueprint_concepts > 0 else 0.0

        topic_summaries: List[TopicReadinessSummary] = []
        unassessed_list: List[str] = []
        weak_list: List[str] = []
        stale_list: List[str] = []
        transfer_gap_list: List[str] = []
        risk_factors: List[str] = []
        strengths: List[str] = []

        weighted_readiness_accum = 0.0

        for t in normalized_topics:
            t_id = t["topic_id"]
            t_weight = t["weight"]
            c_ids = t["concept_ids"]

            if not c_ids:
                topic_summaries.append(
                    TopicReadinessSummary(
                        topic_id=t_id,
                        weight=round(t_weight, 4),
                        concept_ids=[],
                        assessed_concept_count=0,
                        mean_mastery=0.0,
                        mean_uncertainty=1.0,
                        mean_retention=0.0,
                        transfer_verified_count=0,
                        topic_readiness_score=0.0,
                        status="unassessed",
                    )
                )
                continue

            t_assessed_count = 0
            m_accum = 0.0
            u_accum = 0.0
            r_accum = 0.0
            tv_count = 0
            readiness_accum = 0.0

            for cid in c_ids:
                st = all_states.get(cid)
                is_assessed = (st is not None and st.evidence_count > 0)

                if not is_assessed:
                    unassessed_list.append(cid)
                    u_val = 1.0
                    m_val = 0.0
                    r_val = 0.0
                    t_val = 0.0
                    eff_readiness = 0.0
                else:
                    t_assessed_count += 1
                    m_val = st.mastery_probability
                    m_accum += m_val

                    # Mastery uncertainty
                    u_eval = MasteryUncertaintyEvaluator.evaluate_state(st, as_of_time=now_iso)
                    u_val = u_eval.uncertainty_index
                    u_accum += u_val

                    # Memory retention
                    if self.retention_model:
                        ret_est = self.retention_model.estimate_retention(lid, cid, as_of_time=now_iso)
                        r_val = float(ret_est.get("retention_probability", 0.5))
                    else:
                        r_val = 0.8  # Default baseline if model unconfigured
                    r_accum += r_val

                    if r_val < 0.60:
                        stale_list.append(cid)

                    # Transfer verification
                    t_factor = 0.70
                    if self.transfer_verifier:
                        tr_eval = self.transfer_verifier.evaluate_transfer(lid, cid)
                        st_val = tr_eval.status.value if hasattr(tr_eval.status, "value") else str(tr_eval.status)
                        if st_val in {"verified_transfer", "transfer_verified"}:
                            t_factor = 1.0
                            tv_count += 1
                        elif tr_eval.unseen_attempts_count > 0 and tr_eval.transfer_accuracy >= 0.50:
                            t_factor = 0.85
                        elif tr_eval.unseen_attempts_count > 0:
                            t_factor = 0.50

                    if m_val >= 0.75 and t_factor < 0.85:
                        transfer_gap_list.append(cid)

                    if m_val < 0.50:
                        weak_list.append(cid)

                    # Effective concept readiness:
                    # E_i = M_i * (0.40 + 0.30 * (1 - U_i) + 0.15 * R_i + 0.15 * T_factor)
                    cert_val = max(0.0, 1.0 - u_val)
                    readiness_multiplier = 0.40 + (0.30 * cert_val) + (0.15 * r_val) + (0.15 * t_factor)
                    eff_readiness = m_val * readiness_multiplier

                readiness_accum += eff_readiness

            c_len = len(c_ids)
            topic_readiness = round(readiness_accum / c_len, 4)
            weighted_readiness_accum += t_weight * topic_readiness

            mean_m = round(m_accum / c_len, 4)
            mean_u = round(u_accum / c_len, 4)
            mean_r = round(r_accum / c_len, 4)

            # Topic status
            if t_assessed_count == 0:
                t_status = "unassessed"
            elif mean_m < 0.45 or (t_assessed_count / c_len) < 0.5:
                t_status = "critical_gap"
            elif topic_readiness < 0.70:
                t_status = "developing"
            else:
                t_status = "prepared"

            topic_summaries.append(
                TopicReadinessSummary(
                    topic_id=t_id,
                    weight=round(t_weight, 4),
                    concept_ids=list(c_ids),
                    assessed_concept_count=t_assessed_count,
                    mean_mastery=mean_m,
                    mean_uncertainty=mean_u,
                    mean_retention=mean_r,
                    transfer_verified_count=tv_count,
                    topic_readiness_score=topic_readiness,
                    status=t_status,
                )
            )

        final_score = round(weighted_readiness_accum, 4)

        # Synthesize qualitative readiness level
        if assessed_ratio < 0.30 or final_score < 0.35:
            readiness_lvl = "not_ready"
        elif final_score < 0.55:
            readiness_lvl = "emerging"
        elif final_score < 0.70:
            readiness_lvl = "progressing"
        elif final_score < 0.85:
            readiness_lvl = "ready_with_caution"
        else:
            readiness_lvl = "exam_ready"

        # Diagnostic Risk & Strength factors
        if assessed_ratio < 0.50:
            risk_factors.append(f"Low exam coverage: {round(assessed_ratio * 100, 1)}% of blueprint concepts have been assessed.")
        if unassessed_list:
            risk_factors.append(f"Unassessed concepts in blueprint ({len(unassessed_list)}): {', '.join(unassessed_list[:4])}.")
        if weak_list:
            risk_factors.append(f"Weak mastery detected on {len(weak_list)} concepts: {', '.join(weak_list[:4])}.")
        if stale_list:
            risk_factors.append(f"Memory retention decayed on {len(stale_list)} concepts; spaced review required.")
        if transfer_gap_list:
            risk_factors.append(f"High familiar mastery but unseen transfer unverified on {len(transfer_gap_list)} concepts.")

        for ts in topic_summaries:
            if ts.status == "prepared":
                strengths.append(f"Solid preparation on '{ts.topic_id}' (Score: {ts.topic_readiness_score:.2f}).")
            elif ts.status == "critical_gap":
                risk_factors.append(f"Critical knowledge gap on high-weight topic '{ts.topic_id}'.")

        if not strengths and final_score >= 0.50:
            strengths.append("Foundational concepts developing across pilot curriculum.")

        formula_doc = (
            "Provisional Heuristic Readiness Formula: "
            "For each concept i in blueprint: E_i = P(L_i) * [0.40 + 0.30*(1 - U_i) + 0.15*R(Δt) + 0.15*T_i]. "
            "Blueprint Score = sum(weight_j * mean(E_i in topic_j))."
        )
        limitations_disc = (
            "This index is a transparent heuristic synthesis of BKT latent mastery, evidential certainty, "
            "memory retention, and unseen transfer performance. It is NOT an empirical passing probability "
            "and has not been calibrated on human student standardized exam outcomes."
        )

        coverage_dict = {
            "total_blueprint_concepts": total_blueprint_concepts,
            "assessed_blueprint_concepts": len(assessed_cids),
            "assessed_ratio": round(assessed_ratio, 4),
            "coverage_sufficient": assessed_ratio >= 0.60,
        }

        return ExamReadinessReport(
            report_id=report_id,
            learner_id=lid,
            blueprint_id=blueprint_id,
            provisional_readiness_score=final_score,
            readiness_level=readiness_lvl,
            is_calibrated_probability=False,
            evidence_coverage=coverage_dict,
            topic_breakdown=topic_summaries,
            unassessed_concepts=unassessed_list,
            weak_concepts=weak_list,
            stale_retention_concepts=stale_list,
            transfer_gap_concepts=transfer_gap_list,
            key_risk_factors=risk_factors,
            key_strengths=strengths,
            formula_documentation=formula_doc,
            limitations_disclaimer=limitations_disc,
            created_at=now_iso,
        )
