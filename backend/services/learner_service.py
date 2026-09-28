"""
Learner Service Facade for Taproot Application Layer.
Manages persistent learner state, Bayesian Knowledge Tracing (BKT) updates, gap analysis, and personalized learning paths.
"""

from typing import Dict, List, Optional, Any
from phase3.storage.learner_repository import LearnerStateRepository
from phase3.learner.models import LearnerState
from phase4.integration.phase3_adapter import Phase3Adapter
from backend.services.knowledge_service import KnowledgeService


class LearnerService:
    def __init__(
        self,
        repo: Optional[LearnerStateRepository] = None,
        knowledge_service: Optional[KnowledgeService] = None,
    ):
        self.repo = repo or LearnerStateRepository()
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.adapter = Phase3Adapter()

    def get_or_create_learner_state(self, learner_id: str, concept_ids: List[str]) -> LearnerState:
        """
        Retrieves persistent learner state or initializes a new one.
        """
        state = self.repo.load_state(learner_id)
        if not state:
            state = self.adapter.tracer.initialize_learner(learner_id, concept_ids)
            self.repo.save_state(state)
        else:
            # Ensure any missing new concepts are registered
            missing = [cid for cid in concept_ids if cid not in state.concept_states]
            if missing:
                for cid in missing:
                    state.concept_states[cid] = self.adapter.tracer.initialize_concept_state(cid)
                self.repo.save_state(state)
        return state

    def save_learner_state(self, state: LearnerState) -> None:
        self.repo.save_state(state)

    def get_learner_progress(self, learner_id: str, subject_id: str) -> Dict[str, Any]:
        """
        Computes progress breakdown: Exploration, Demonstrated Mastery, Confidence, and Path Position.
        """
        graph = self.knowledge_service.get_subject_graph(subject_id)
        all_concepts = [c["concept_id"] for c in graph["concepts"]]
        state = self.get_or_create_learner_state(learner_id, all_concepts)

        mastered_count = 0
        developing_count = 0
        explored_count = 0
        total_mastery_sum = 0.0

        for cid in all_concepts:
            cs = state.concept_states.get(cid)
            if cs:
                m = cs.mastery_probability
                total_mastery_sum += m
                if cs.attempt_count > 0:
                    explored_count += 1
                if m >= 0.75:
                    mastered_count += 1
                elif m >= 0.4:
                    developing_count += 1

        total_concepts = len(all_concepts) or 1
        avg_mastery = total_mastery_sum / total_concepts
        exploration_rate = explored_count / total_concepts

        return {
            "learner_id": learner_id,
            "subject_id": subject_id,
            "total_concepts": total_concepts,
            "explored_concepts": explored_count,
            "mastered_concepts": mastered_count,
            "developing_concepts": developing_count,
            "unexplored_concepts": total_concepts - explored_count,
            "average_mastery": round(avg_mastery, 3),
            "exploration_rate": round(exploration_rate, 3),
            "overall_confidence": "HIGH" if exploration_rate > 0.6 else "MEDIUM" if exploration_rate > 0.2 else "LOW",
        }

    def get_gaps_and_path(self, learner_id: str, subject_id: str) -> Dict[str, Any]:
        """
        Derives Phase 4 knowledge gaps, prioritized order, cycle-safe learning path, and active next target.
        """
        graph = self.knowledge_service.get_subject_graph(subject_id)
        concept_ids = [c["concept_id"] for c in graph["concepts"]]

        learner_state = self.get_or_create_learner_state(learner_id, concept_ids)
        # No concept seeding: the context is loaded from the uploaded document, and
        # concept_ids here come from that same document's graph.
        learning_context = self.knowledge_service.get_learning_context(subject_id)

        gaps = self.adapter.gap_detector.detect_gaps(learning_context, learner_state, concept_ids)
        prioritized_gaps = self.adapter.gap_prioritizer.prioritize_gaps(gaps)
        path = self.adapter.path_generator.generate_path(learning_context, learner_state, concept_ids)
        next_target = self.adapter.target_selector.select_next_target(path, learner_state, learning_context)

        dumped_path = path.model_dump(mode="json")
        for node in dumped_path.get("nodes", []):
            cid = node.get("concept_id")
            c_info = next((c for c in graph["concepts"] if c["concept_id"] == cid), None)
            c_name = node.get("concept_name") or (c_info["name"] if c_info else cid.replace("_", " ").title())
            node["name"] = c_name
            node["concept_name"] = c_name
            node["mastery"] = node.get("estimated_mastery", 0.15)
            node["prerequisites"] = c_info.get("prerequisites", []) if c_info else []

        dumped_target = next_target.model_dump(mode="json") if next_target else None
        if dumped_target:
            t_cid = dumped_target.get("concept_id")
            c_info = next((c for c in graph["concepts"] if c["concept_id"] == t_cid), None)
            t_name = dumped_target.get("concept_name") or (c_info["name"] if c_info else t_cid.replace("_", " ").title())
            dumped_target["name"] = t_name
            dumped_target["concept_name"] = t_name
            dumped_target["estimated_minutes"] = 15

        return {
            "gaps": [g.model_dump(mode="json") for g in prioritized_gaps],
            "learning_path": dumped_path,
            "next_target": dumped_target,
        }
