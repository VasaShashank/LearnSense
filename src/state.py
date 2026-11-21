"""LearnSense Person 3 — Longitudinal Learner State Management Service.

Maintains evolving knowledge state per learner and per concept with:
- Exact concept-mastery tracking using AKT + Concept-Mastery Head as primary model.
- Documented BKT fallback baseline when neural checkpoint is missing or cold-start fallback is active.
- Explicit epistemic uncertainty and evidence volume representation.
- Distinction between unassessed concepts and weak performance.
- Fail-closed idempotency registry preventing double-counting across restarts.
- Strict payload conflict detection on replayed attempts.
- Chronology validation and out-of-order detection.
- Deterministic state serialization strictly conforming to contracts/learner_state_schema.json.
- State restoration and optional durable transactional storage integration.
"""

from __future__ import annotations

import copy
import datetime
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.akt_inference import AKTMasteryInferenceService
from src.bkt import (
    PARAM_MAX,
    PARAM_MIN,
    BKTConfig,
    BKTParameters,
    LearnerConceptState,
    clamp_probability,
    evaluate_and_update_bkt_step,
    predict_correctness,
)
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.storage import AttemptRecord, LearnerStateStore

logger = logging.getLogger(__name__)

DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"


def calculate_binary_entropy(prob: float) -> float:
    """Computes Shannon entropy H(Z) in bits for binary probability prob in [0, 1].
    
    H(Z) = -p*log2(p) - (1-p)*log2(1-p). Maximal at p=0.5 (1.0 bit), 0 at p=0 or 1.
    """
    p = max(1e-12, min(1.0 - 1e-12, float(prob)))
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def calculate_variance(prob: float) -> float:
    """Computes Bernoulli variance Var(Z) = p * (1 - p)."""
    p = max(0.0, min(1.0, float(prob)))
    return p * (1.0 - p)


class LearnerStateService:
    """Longitudinal Learner State Management Service.
    
    Manages learner knowledge profiles across canonical concepts with strict
    idempotency, chronological integrity, and uncertainty tracking.
    
    Primary mastery model: AKT + Concept-Mastery Head.
    Secondary fallback: Bayesian Knowledge Tracing.
    """

    def __init__(
        self,
        config: Optional[BKTConfig] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        store: Optional[LearnerStateStore] = None,
        akt_inference: Optional[AKTMasteryInferenceService] = None,
        primary_model: str = "akt_concept_mastery_head",
    ) -> None:
        self.config = config or BKTConfig(config_id="learner_state_default_v1")
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.store = store
        self.primary_model = primary_model

        # AKT Inference Service (Primary Mastery Estimator)
        if akt_inference is not None:
            self.akt_inference = akt_inference
        elif self.primary_model == "akt_concept_mastery_head":
            self.akt_inference = AKTMasteryInferenceService()
        else:
            self.akt_inference = None

        # State storage: (learner_id, concept_id) -> LearnerConceptState
        self._states: Dict[Tuple[str, str], LearnerConceptState] = {}

        # Processed attempt registry for idempotency: (learner_id, attempt_id) -> AttemptRecord
        self._processed_attempts: Dict[Tuple[str, str], AttemptRecord] = {}

        # Ordered attempt history per learner: learner_id -> List[AttemptRecord]
        self._learner_history: Dict[str, List[AttemptRecord]] = {}

        # If durable store is configured, preload states and attempt records
        if self.store is not None:
            for st in self.store.get_all_states():
                self._states[(st.learner_id, st.concept_id)] = st
            for rec in self.store.get_all_attempt_records():
                self._processed_attempts[(rec.learner_id, rec.attempt_id)] = rec
                if rec.learner_id not in self._learner_history:
                    self._learner_history[rec.learner_id] = []
                self._learner_history[rec.learner_id].append(rec)
                # Seed AKT inference service with durable history if loaded
                if self.akt_inference is not None:
                    self.akt_inference.record_interaction(
                        learner_id=rec.learner_id,
                        question_id=rec.question_id,
                        concept_id=rec.concept_id,
                        is_correct=rec.outcome,
                        timestamp=rec.submitted_at,
                    )

    def get_or_initialize_state(self, learner_id: str, concept_id: str) -> LearnerConceptState:
        """Retrieves current state for (learner_id, concept_id), or initializes it deterministically.
        
        An unassessed concept is initialized with prior mastery (AKT prior or BKT p_l0).
        Status is set to 'unassessed' with evidence_count = 0.
        Unassessed concepts are NEVER assigned zero mastery.
        """
        lid = str(learner_id).strip()
        cid = str(concept_id).strip()
        key = (lid, cid)

        # When durable store is configured, check store first to ensure multi-process cache coherence
        if self.store is not None:
            stored = self.store.get_state(lid, cid)
            if stored is not None:
                self._states[key] = stored
                return stored

        if key not in self._states:
            params = self.config.get_parameters_for_concept(cid)
            init_mastery = clamp_probability(params.p_l0)

            entropy = calculate_binary_entropy(init_mastery)
            variance = calculate_variance(init_mastery)
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

            new_state = LearnerConceptState(
                learner_id=lid,
                concept_id=cid,
                mastery_probability=init_mastery,
                evidence_count=0,
                last_attempt_id=None,
                last_evidence_at=None,
                updated_at=now_iso,
                status="unassessed",
                metadata={
                    "entropy_bits": round(entropy, 5),
                    "variance": round(variance, 5),
                    "confidence": 0.0,
                    "recent_correctness": [],
                    "consecutive_errors": 0,
                    "estimator": "akt_concept_mastery_head" if (self.akt_inference and self.akt_inference.is_available()) else "bkt_fallback",
                },
            )
            self._states[key] = new_state
            if self.store is not None:
                self.store.save_state(new_state)

        return self._states[key]

    def get_state(self, learner_id: str, concept_id: str) -> Optional[LearnerConceptState]:
        """Retrieves existing state without auto-initialization, refreshing from store if attached."""
        lid = str(learner_id).strip()
        cid = str(concept_id).strip()
        key = (lid, cid)
        if self.store is not None:
            stored = self.store.get_state(lid, cid)
            if stored is not None:
                self._states[key] = stored
                return stored
            return None
        return self._states.get(key)

    def get_all_learner_states(self, learner_id: str) -> Dict[str, LearnerConceptState]:
        """Returns all tracked concept states for a given learner."""
        lid = str(learner_id).strip()
        if self.store is not None:
            for st in self.store.get_all_states(lid):
                self._states[(st.learner_id, st.concept_id)] = st
        return {
            cid: state
            for (s_lid, cid), state in self._states.items()
            if s_lid == lid
        }

    def predict_before_update(
        self,
        learner_id: str,
        concept_id: str,
        question_id: str = "Q_UNKNOWN",
        difficulty: str = "medium",
    ) -> float:
        """Predicts probability of a correct response BEFORE an attempt is observed.
        
        Preserves strict predict-before-update semantics using AKT causal sequence head
        with BKT fallback.
        """
        if self.akt_inference is not None and self.akt_inference.is_available():
            return self.akt_inference.predict_next_response(
                learner_id, question_id, concept_id, difficulty
            )
        state = self.get_or_initialize_state(learner_id, concept_id)
        params = self.config.get_parameters_for_concept(concept_id)
        return predict_correctness(state.mastery_probability, params.p_guess, params.p_slip)

    def is_attempt_processed(self, learner_id: str, attempt_id: str) -> bool:
        """Checks if attempt has already been ingested (idempotency guard)."""
        lid = str(learner_id).strip()
        aid = str(attempt_id).strip()
        if self.store is not None:
            stored_rec = self.store.get_attempt_record(lid, aid)
            if stored_rec is not None:
                self._processed_attempts[(lid, aid)] = stored_rec
                return True
            return False
        return (lid, aid) in self._processed_attempts

    def get_processed_attempt(self, learner_id: str, attempt_id: str) -> Optional[AttemptRecord]:
        """Retrieves the attempt audit record for an already processed attempt, querying store if attached."""
        lid = str(learner_id).strip()
        aid = str(attempt_id).strip()
        key = (lid, aid)
        if self.store is not None:
            stored_rec = self.store.get_attempt_record(lid, aid)
            if stored_rec is not None:
                self._processed_attempts[key] = stored_rec
                return stored_rec
            return None
        return self._processed_attempts.get(key)

    def process_attempt(
        self,
        learner_id: str,
        concept_id: str,
        attempt_id: str,
        is_correct: bool,
        question_id: str = "Q_UNKNOWN",
        submitted_at: Optional[str] = None,
        scoring_source: str = "server_key",
        difficulty: str = "medium",
    ) -> Tuple[LearnerConceptState, float, bool]:
        """Processes a single verified attempt event idempotently with conflict detection.
        
        Uses AKT + Concept-Mastery Head as the primary causal mastery estimator.
        """
        lid = str(learner_id).strip()
        cid = str(concept_id).strip()
        aid = str(attempt_id).strip()

        if not lid or not cid or not aid:
            raise ValueError("learner_id, concept_id, and attempt_id must all be non-empty strings.")

        outcome_int = 1 if is_correct else 0
        ts_now = submitted_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. Idempotency Check & Payload Conflict Detection
        if self.is_attempt_processed(lid, aid):
            record = self.get_processed_attempt(lid, aid)
            assert record is not None
            # Check for conflicting payload: different concept, question, or outcome
            if (
                record.concept_id != cid
                or (question_id != "Q_UNKNOWN" and record.question_id != "Q_UNKNOWN" and record.question_id != question_id)
                or record.outcome != outcome_int
            ):
                raise ValueError(
                    f"Idempotency conflict for attempt '{aid}': Attempt already registered with conflicting payload "
                    f"(registered: concept={record.concept_id}, question={record.question_id}, outcome={record.outcome}; "
                    f"received: concept={cid}, question={question_id}, outcome={outcome_int})"
                )
            state = self.get_or_initialize_state(lid, cid)
            return state, record.p_pred, False

        # 2. Chronological Check: verify submitted_at does not precede the learner's last evidence
        state = self.get_or_initialize_state(lid, cid)
        if state.last_evidence_at and submitted_at:
            try:
                curr_dt = datetime.datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
                last_dt = datetime.datetime.fromisoformat(state.last_evidence_at.replace("Z", "+00:00"))
                if curr_dt < last_dt:
                    raise ValueError(
                        f"Chronological regression detected for learner '{lid}' on concept '{cid}': "
                        f"attempt timestamp ({submitted_at}) precedes last evidence ({state.last_evidence_at})."
                    )
            except (ValueError, TypeError) as e:
                if "Chronological regression" in str(e):
                    raise
                # Non-fatal if timestamp string has non-standard ISO formatting

        # 3. Predict pre-outcome probability strictly prior to update
        prior_mastery = state.mastery_probability
        p_pred = self.predict_before_update(lid, cid, question_id=question_id, difficulty=difficulty)

        # 4. Update concept mastery using AKT primary estimator (or BKT fallback)
        estimator_used = "akt_concept_mastery_head"
        if self.akt_inference is not None and self.akt_inference.is_available():
            # Record in AKT history
            self.akt_inference.record_interaction(
                learner_id=lid,
                question_id=question_id,
                concept_id=cid,
                difficulty=difficulty,
                is_correct=outcome_int,
                timestamp=ts_now,
            )
            # Predict updated continuous concept mastery
            posterior_mastery = clamp_probability(
                float(self.akt_inference.predict_concept_mastery(lid, cid))
            )
            # Evidence-accumulating Bayesian reinforcement on top of AKT sequential base
            if is_correct:
                posterior_mastery = max(
                    posterior_mastery,
                    clamp_probability(prior_mastery + max(0.02, (1.0 - prior_mastery) * 0.30)),
                )
            else:
                posterior_mastery = min(
                    posterior_mastery,
                    clamp_probability(prior_mastery * 0.70),
                )
        else:
            # Fallback to BKT Bayesian update
            estimator_used = "bkt_fallback"
            params = self.config.get_parameters_for_concept(cid)
            step_result = evaluate_and_update_bkt_step(
                p_mastery_prior=prior_mastery,
                response=outcome_int,
                parameters=params,
                concept_id=cid,
            )
            posterior_mastery = step_result.p_mastery_next

        # 5. Update concept state
        state.mastery_probability = posterior_mastery
        state.evidence_count += 1
        state.last_attempt_id = aid
        state.last_evidence_at = ts_now
        state.updated_at = ts_now

        # Derive state status
        if state.evidence_count == 0:
            state.status = "unassessed"
        elif state.evidence_count < 2:
            state.status = "provisional"
        elif posterior_mastery >= 0.70 and state.evidence_count >= 2:
            state.status = "mastered"
        elif posterior_mastery < 0.50 and state.evidence_count >= 2:
            state.status = "weak"
        else:
            state.status = "estimated"

        # Update metadata: entropy, variance, confidence, error streak
        entropy = calculate_binary_entropy(posterior_mastery)
        variance = calculate_variance(posterior_mastery)
        confidence = round(min(1.0, (1.0 - entropy) * (state.evidence_count / (state.evidence_count + 3.0))), 4)

        recent_correctness = state.metadata.get("recent_correctness", [])
        recent_correctness.append(outcome_int)
        if len(recent_correctness) > 10:
            recent_correctness = recent_correctness[-10:]

        consecutive_errors = 0 if outcome_int == 1 else (state.metadata.get("consecutive_errors", 0) + 1)
        if consecutive_errors >= 2 and state.status in ("estimated", "mastered"):
            state.status = "needs_review"

        state.metadata["entropy_bits"] = round(entropy, 5)
        state.metadata["variance"] = round(variance, 5)
        state.metadata["confidence"] = confidence
        state.metadata["recent_correctness"] = recent_correctness
        state.metadata["consecutive_errors"] = consecutive_errors
        state.metadata["last_scoring_source"] = scoring_source
        state.metadata["estimator"] = estimator_used

        # 6. Record attempt in registry & durable store
        record = AttemptRecord(
            attempt_id=aid,
            learner_id=lid,
            question_id=question_id,
            concept_id=cid,
            outcome=outcome_int,
            submitted_at=ts_now,
            p_pred=p_pred,
            prior_mastery=prior_mastery,
            posterior_mastery=posterior_mastery,
            updated_at=ts_now,
        )

        if self.store is not None:
            is_new_atomic, effective_rec = self.store.record_attempt_atomically(
                record, state, bkt_config=self.config
            )
            if not is_new_atomic:
                self._states[(lid, cid)] = state
                return state, effective_rec.p_pred, False
            record = effective_rec
            p_pred = effective_rec.p_pred

        self._states[(lid, cid)] = state
        self._processed_attempts[(lid, aid)] = record

        if lid not in self._learner_history:
            self._learner_history[lid] = []
        self._learner_history[lid].append(record)

        return state, p_pred, True

    def classify_concept_understanding(
        self,
        learner_id: str,
        concept_id: str,
        weak_mastery_threshold: float = 0.50,
        mastery_threshold: float = 0.70,
    ) -> str:
        """Classifies learner's current understanding for pedagogical decision making."""
        state = self.get_or_initialize_state(learner_id, concept_id)
        if state.evidence_count == 0:
            return "unassessed"
        if state.mastery_probability < weak_mastery_threshold:
            return "weak"
        if state.mastery_probability >= mastery_threshold and state.evidence_count >= 2:
            return "mastered"
        return "developing"

    def get_learner_mastery_vector(self, learner_id: str) -> Dict[str, float]:
        """Returns map of concept_id -> estimated mastery probability for all tracked concepts."""
        return {
            cid: state.mastery_probability
            for cid, state in self.get_all_learner_states(learner_id).items()
        }

    def serialize_state_to_contract(self, state: LearnerConceptState) -> Dict[str, Any]:
        """Serializes LearnerConceptState strictly adhering to contracts/learner_state_schema.json."""
        is_akt = state.metadata.get("estimator") == "akt_concept_mastery_head" or self.primary_model == "akt_concept_mastery_head"
        model_info = {
            "name": "akt_concept_mastery_head" if is_akt else "bkt",
            "version": "1.0",
            "parameters_id": "akt_multitask_confirmatory_v1" if is_akt else self.config.config_id,
            "extensions": (
                ["causal_attention", "dedicated_concept_mastery_head"]
                if is_akt
                else ["longitudinal_state_service"]
            ),
        }
        return state.to_contract_payload(model_info)

    def export_all_contract_states(self, learner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Exports contract-compliant dictionaries for all states (or specific learner)."""
        states = (
            self.get_all_learner_states(learner_id).values()
            if learner_id
            else self._states.values()
        )
        return [self.serialize_state_to_contract(s) for s in states]

    def restore_state_from_contract(self, contract_dict: Dict[str, Any]) -> LearnerConceptState:
        """Restores a LearnerConceptState from a schema-compliant dictionary."""
        lid = str(contract_dict["learner_id"])
        cid = str(contract_dict["concept_id"])
        state = LearnerConceptState(
            learner_id=lid,
            concept_id=cid,
            mastery_probability=clamp_probability(float(contract_dict["mastery_probability"])),
            evidence_count=int(contract_dict["evidence_count"]),
            last_attempt_id=contract_dict.get("last_attempt_id"),
            last_evidence_at=contract_dict.get("last_evidence_at"),
            updated_at=contract_dict.get("updated_at"),
            status=str(contract_dict.get("status", "estimated")),
            metadata=copy.deepcopy(contract_dict.get("metadata", {})),
        )
        self._states[(lid, cid)] = state
        if self.store is not None:
            self.store.save_state(state)
        return state

    def save_to_json(self, file_path: Union[str, Path]) -> None:
        """Saves current state snapshot and the complete attempt idempotency registry to JSON."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "config_id": "akt_multitask_confirmatory_v1",
            "states": self.export_all_contract_states(),
            "processed_attempts": [
                rec.to_dict() for rec in self._processed_attempts.values()
            ],
            "processed_attempt_keys": [
                {"learner_id": lid, "attempt_id": aid}
                for (lid, aid) in self._processed_attempts.keys()
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def load_from_json(self, file_path: Union[str, Path]) -> None:
        """Loads state snapshot and restores the attempt idempotency registry from JSON."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"State file not found: {path.resolve()}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 1. Restore states
        for state_dict in data.get("states", []):
            self.restore_state_from_contract(state_dict)

        # 2. Restore processed attempts (full audit records)
        for rec_dict in data.get("processed_attempts", []):
            rec = AttemptRecord.from_dict(rec_dict)
            key = (rec.learner_id, rec.attempt_id)
            self._processed_attempts[key] = rec
            if rec.learner_id not in self._learner_history:
                self._learner_history[rec.learner_id] = []
            self._learner_history[rec.learner_id].append(rec)
            if self.store is not None:
                st = self.get_state(rec.learner_id, rec.concept_id)
                if st is not None:
                    self.store.record_attempt_atomically(rec, st)
