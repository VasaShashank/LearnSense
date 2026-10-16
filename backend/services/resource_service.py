"""
Resource Intelligence Service Facade for TAPROOT / LearnSense.
Manages educational video resources, notation-aware matching, and recommendations (§9).
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase3.resources.models import (
    ResourceRecord,
    ResourceMatchResult,
    TranscriptSegment,
    FormulaVariant,
    NotationVariant,
)
from phase3.resources.recommender import ResourceRecommender
from phase3.resources.notation_matcher import NotationMatcher
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: Any, base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(base_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


class ResourceService:
    """
    Manages external educational resources and serves notation-matched video recommendations.
    """

    def __init__(
        self,
        storage_dir: str = "storage/resources",
        knowledge_service: Optional[KnowledgeService] = None,
        learner_service: Optional[LearnerService] = None,
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.learner_service = learner_service or LearnerService()

        # Connect live LLM adapter for zero-shot semantic notation alignment across any discipline
        llm_adapter = None
        try:
            from phase3.adapters.llm_adapter import get_llm_adapter
            adapter = get_llm_adapter()
            if not getattr(adapter, "is_mock", False) and adapter.health().get("has_credentials"):
                llm_adapter = adapter
        except Exception as _llm_init_exc:  # noqa: BLE001
            logger.warning("LLM adapter unavailable for ResourceService; falling back to non-LLM notation matching: %s", _llm_init_exc)

        self.matcher = NotationMatcher(llm_adapter=llm_adapter)
        self.recommender = ResourceRecommender(notation_matcher=self.matcher)
        self._ensure_seed_resources()

    def get_resource(self, resource_id: str) -> Optional[ResourceRecord]:
        path = self.storage_dir / f"{resource_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return ResourceRecord.model_validate(data)
        except Exception as exc:
            logger.error("Failed to load resource %s: %s", resource_id, exc)
            return None

    def save_resource(self, resource: ResourceRecord) -> Path:
        path = self.storage_dir / f"{resource.resource_id}.json"
        data = resource.model_dump(mode="json")
        return _atomic_write_json(path, data, self.storage_dir)

    def list_all_resources(self) -> List[ResourceRecord]:
        results: List[ResourceRecord] = []
        for file in sorted(self.storage_dir.glob("*.json")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append(ResourceRecord.model_validate(data))
            except Exception as exc:
                logger.warning("Skipping unreadable resource %s: %s", file, exc)
        return results

    def get_recommendations_for_concept(
        self,
        subject_id: str,
        concept_id: str,
        learner_id: Optional[str] = None,
        top_k: int = 5,
    ) -> List[ResourceMatchResult]:
        """
        Retrieves notation-matched video recommendations for a specific concept in a course.
        """
        # Load course context
        ctx = self.knowledge_service.get_learning_context(subject_id)
        concept = ctx.concepts.get(concept_id)
        concept_name = concept.canonical_name if concept else concept_id

        # Extract formulas mentioned or associated with this concept in the course
        source_formulas: List[str] = []
        for form_id, formula in ctx.formulas.items():
            if formula.concept_id == concept_id or concept_id in formula.related_concept_ids:
                source_formulas.append(formula.latex or formula.raw_text)

        # Extract prerequisite concept ids
        prereq_ids = [p.source_concept_id for p in ctx.prerequisites if p.target_concept_id == concept_id]

        # Extract learner mastery if learner_id provided
        learner_mastery = 0.30
        if learner_id:
            all_cids = list(ctx.concepts.keys())
            st = self.learner_service.get_or_create_learner_state(learner_id, all_cids)
            c_state = st.concept_states.get(concept_id)
            if c_state:
                learner_mastery = c_state.mastery_probability

        # Extract document-derived context glossary from concept aliases and definitions
        context_glossary: Dict[str, str] = {}
        for c in ctx.concepts.values():
            for alias in c.aliases:
                context_glossary[alias] = c.canonical_name
            context_glossary[c.concept_id] = c.canonical_name

        # Domain is generalized: uses the real document/course title
        domain = ctx.document_title or subject_id

        candidates = self.list_all_resources()
        return self.recommender.recommend_resources(
            target_concept_id=concept_id,
            target_concept_name=concept_name,
            source_formulas=source_formulas,
            candidate_resources=candidates,
            learner_mastery=learner_mastery,
            prerequisite_concept_ids=prereq_ids,
            subject_domain=domain,
            context_glossary=context_glossary,
            top_k=top_k,
        )

    def _ensure_seed_resources(self) -> None:
        """Seed foundational verified educational video resources."""
        if any(self.storage_dir.glob("*.json")):
            return

        seeds = [
            ResourceRecord(
                resource_id="res_3b1b_calculus_essence",
                url="https://www.youtube.com/watch?v=WUvTyaaNkzM",
                provider="youtube",
                title="The Essence of Calculus - Chapter 1",
                channel="3Blue1Brown",
                duration_seconds=1025,
                language="en",
                difficulty=0.45,
                confidence=1.0,
                concepts_covered=["c_derivatives", "derivatives", "limits", "c_limits", "slope"],
                prerequisite_concepts=["functions", "algebra"],
                notation_variants=[
                    NotationVariant(symbol="df/dx", meaning="derivative", canonical_symbol="derivative"),
                    NotationVariant(symbol="dx", meaning="infinitesimal_change", canonical_symbol="dx"),
                ],
                formulas=[
                    FormulaVariant(
                        raw_formula="df/dx = lim_{dx->0} (f(x+dx) - f(x))/dx",
                        normalized_formula="df/dx = lim(dx->0) (f(x+dx)-f(x))/dx",
                        canonical_formula_id="derivative_definition",
                    )
                ],
                transcript=[
                    TranscriptSegment(
                        start_seconds=0.0,
                        end_seconds=145.0,
                        text="Calculus is fundamentally about geometry and tiny changes. Let's see what derivatives really represent visually.",
                        concept_ids=["c_derivatives", "derivatives"],
                    ),
                    TranscriptSegment(
                        start_seconds=146.0,
                        end_seconds=380.0,
                        text="When we take the ratio of a tiny nudge in output df over a tiny nudge in input dx, we get the derivative df/dx.",
                        concept_ids=["c_derivatives", "derivatives"],
                        formulas_mentioned=["df/dx"],
                    ),
                    TranscriptSegment(
                        start_seconds=381.0,
                        end_seconds=600.0,
                        text="This brings us to limits: what does the ratio approach as dx gets arbitrarily close to zero?",
                        concept_ids=["c_limits", "limits"],
                    ),
                ],
            ),
            ResourceRecord(
                resource_id="res_khan_kinematics_v_at",
                url="https://www.youtube.com/watch?v=4yC_r_a8f9w",
                provider="youtube",
                title="Deriving Kinematic Equations: Velocity and Acceleration",
                channel="Khan Academy",
                duration_seconds=540,
                language="en",
                difficulty=0.40,
                confidence=1.0,
                concepts_covered=["kinematics", "acceleration", "velocity", "c_kinematics"],
                prerequisite_concepts=["algebra", "time"],
                notation_variants=[
                    NotationVariant(symbol="v_0", meaning="initial_velocity", canonical_symbol="initial_velocity"),
                    NotationVariant(symbol="\\Delta t", meaning="time", canonical_symbol="time"),
                ],
                formulas=[
                    FormulaVariant(
                        raw_formula="v = v_0 + a*\\Delta t",
                        normalized_formula="v = v_0 + a*t",
                        canonical_formula_id="kinematics_velocity_time",
                        variable_mappings={"v_0": "u", "\\Delta t": "t"},
                    )
                ],
                transcript=[
                    TranscriptSegment(
                        start_seconds=0.0,
                        end_seconds=120.0,
                        text="Welcome to kinematic motion with constant acceleration. We start with the definition of acceleration as change in velocity.",
                        concept_ids=["acceleration"],
                    ),
                    TranscriptSegment(
                        start_seconds=121.0,
                        end_seconds=310.0,
                        text="If our starting velocity is v naught (v_0) and acceleration is constant a, the final velocity v after time interval delta t is v = v_0 + a*delta t.",
                        concept_ids=["velocity", "acceleration"],
                        formulas_mentioned=["v = v_0 + a*\\Delta t"],
                    ),
                ],
            ),
            ResourceRecord(
                resource_id="res_organic_chem_chain_rule",
                url="https://www.youtube.com/watch?v=6k7re_j4m8c",
                provider="youtube",
                title="The Chain Rule For Derivatives Made Easy",
                channel="The Organic Chemistry Tutor",
                duration_seconds=780,
                language="en",
                difficulty=0.50,
                confidence=1.0,
                concepts_covered=["chain_rule", "c_chain_rule", "c_derivatives"],
                prerequisite_concepts=["c_derivatives"],
                formulas=[
                    FormulaVariant(
                        raw_formula="d/dx [f(g(x))] = f'(g(x)) * g'(x)",
                        normalized_formula="f'(g(x))*g'(x)",
                        canonical_formula_id="chain_rule",
                    )
                ],
                transcript=[
                    TranscriptSegment(
                        start_seconds=0.0,
                        end_seconds=95.0,
                        text="In this video we will master the chain rule for differentiating composite functions step by step.",
                        concept_ids=["c_chain_rule", "chain_rule"],
                    ),
                    TranscriptSegment(
                        start_seconds=96.0,
                        end_seconds=340.0,
                        text="The derivative of an outside function evaluated at the inside function, times the derivative of the inside: f prime of g of x times g prime of x.",
                        concept_ids=["c_chain_rule"],
                        formulas_mentioned=["d/dx [f(g(x))] = f'(g(x)) * g'(x)"],
                    ),
                ],
            ),
        ]

        for s in seeds:
            self.save_resource(s)
