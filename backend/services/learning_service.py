"""
Learning Service Facade for Taproot Application Layer.
Orchestrates onboarding self-assessment, diagnostic assessment creation/submission, learning activities, quiz processing, and KT updates.
"""

from typing import Any, Dict, List, Optional

from phase3.errors import (
    ContentValidationError,
    KnowledgeNotFoundError,
    LearnSenseError,
    RetrievalError,
)
from phase3.question_bank.builder import QuestionBankBuilder
from phase3.question_bank.models import QuestionBank, QuestionBankItem, QuestionType, SourceCitation
from phase3.retrieval.evidence_retriever import EvidenceRetriever
from phase4.integration.phase3_adapter import Phase3Adapter
from phase4.models import KnowledgeInitializationSession, SelfAssessmentStatus
from phase5.validation import IdempotencyTracker, LearnerStateValidator, PlanningValidator
from storage.repositories import QuestionBankRepository, SessionRepository

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService


class LearningService:
    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        question_bank_repo: Optional[QuestionBankRepository] = None,
        learner_service: Optional[LearnerService] = None,
        knowledge_service: Optional[KnowledgeService] = None,
    ):
        self.session_repo = session_repo or SessionRepository()
        self.bank_repo = question_bank_repo or QuestionBankRepository()
        self.learner_service = learner_service or LearnerService()
        self.knowledge_service = knowledge_service or KnowledgeService()

        self.adapter = Phase3Adapter()
        self.idempotency_tracker = IdempotencyTracker()
        self.learner_state_validator = LearnerStateValidator(idempotency_tracker=self.idempotency_tracker)
        self.planning_validator = PlanningValidator()

    def get_or_create_question_bank(
        self, subject_id: str, concept_ids: Optional[List[str]] = None
    ) -> QuestionBank:
        """
        Return a question bank whose every question is grounded in the uploaded document.

        Questions are produced by :class:`QuestionBankBuilder` from passages retrieved out
        of the learner's own file, validated for real provenance, deduplicated and
        persisted. Concepts with no retrievable passage are reported rather than given a
        canned question, so a request never silently returns placeholder content.
        """
        ctx = self.knowledge_service.get_learning_context(subject_id)
        target_ids = list(concept_ids or ctx.concepts.keys())

        builder = QuestionBankBuilder()
        retriever = self._retriever_for(subject_id)

        existing = self.bank_repo.load_grounded_bank(subject_id)
        if existing is not None:
            # Keep only questions for concepts this caller cares about.
            scoped = QuestionBank(document_id=subject_id, chapter_id="ch_all")
            for item in existing.get_grounded_questions():
                if set(item.concept_ids) & set(target_ids):
                    scoped.add_question(item)
            existing = scoped if scoped.questions else None

        bank = builder.build_bank_for_chapter(
            ctx,
            chapter_id="ch_all",
            target_count=max(1, len(target_ids)),
            retriever=retriever,
            existing=existing,
        )

        if bank.get_grounded_questions():
            self.bank_repo.save_bank(bank)
        return bank

    def _retriever_for(self, document_id: str):
        """
        Build the retrieval index for a document, or ``None`` when it is unavailable.

        The index needs the Phase 1 structured document. When it cannot be rebuilt the
        bank builder raises a typed error instead of generating ungrounded questions.
        """
        from backend.services.knowledge_build_service import KnowledgeBuildService

        try:
            return KnowledgeBuildService().get_retriever(document_id)
        except LearnSenseError:
            return None

    def submit_self_assessment(
        self,
        learner_id: str,
        subject_id: str,
        selections: Dict[str, SelfAssessmentStatus],
        all_concept_ids: List[str],
    ) -> KnowledgeInitializationSession:
        val_res = self.planning_validator.validate_self_assessment(selections, all_concept_ids)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        session = self.adapter.self_assessment_handler.create_session(
            learner_id=learner_id,
            subject_id=subject_id,
            selections=selections,
            all_subject_concept_ids=all_concept_ids,
        )
        self.session_repo.save_session(session)
        # Ensure learner state exists
        self.learner_service.get_or_create_learner_state(learner_id, all_concept_ids)
        # Pre-populate question bank for all concepts of this subject
        self.get_or_create_question_bank(subject_id, all_concept_ids)
        return session

    def start_diagnostic(self, session_id: str) -> Dict[str, Any]:
        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")

        bank = self.get_or_create_question_bank(session.subject_id, session.know_concept_ids)
        questions = self.adapter.diagnostic_orchestrator.create_diagnostic_quiz(session, bank)

        val_res = self.planning_validator.validate_diagnostic_quiz_creation(session, questions)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        dumped_questions = []
        for q in questions:
            q_dict = q.model_dump(mode="json")
            q_dict.pop("correct_answer", None)
            q_dict["item_id"] = q_dict.get("question_id", "")
            q_dict["prompt"] = q_dict.get("question_text", "")
            dumped_questions.append(q_dict)

        self.session_repo.save_session(session)
        return {
            "session_id": session.session_id,
            "know_concepts": session.know_concept_ids,
            "question_count": len(questions),
            "questions": dumped_questions,
        }

    def submit_diagnostic(self, session_id: str, responses: Dict[str, float]) -> Dict[str, Any]:
        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")

        all_concepts = session.know_concept_ids + session.dont_know_concept_ids + session.unanswered_concept_ids
        learner_state = self.learner_service.get_or_create_learner_state(session.learner_id, all_concepts)
        bank = self.get_or_create_question_bank(session.subject_id, session.know_concept_ids)

        updated_masteries = self.adapter.diagnostic_orchestrator.submit_diagnostic_responses(
            init_session=session,
            learner_state=learner_state,
            question_responses=responses,
            question_bank=bank,
        )

        self.session_repo.save_session(session)
        self.learner_service.save_learner_state(learner_state)

        return {
            "session_id": session.session_id,
            "diagnostic_completed": session.diagnostic_completed,
            "diagnostic_score": session.diagnostic_score,
            "updated_masteries": updated_masteries,
        }

    def process_activity_response(
        self,
        learner_id: str,
        subject_id: str,
        concept_ids: List[str],
        correctness: float,
        all_subject_concept_ids: List[str],
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        learner_state = self.learner_service.get_or_create_learner_state(learner_id, all_subject_concept_ids)
        # Context comes from the uploaded document; concept IDs are never injected here.
        learning_context = self.knowledge_service.get_learning_context(subject_id)

        val_res = self.learner_state_validator.validate_response_submission(
            learner_id=learner_id,
            concept_ids=concept_ids,
            correctness=correctness,
            request_id=request_id,
            valid_subject_concepts=set(all_subject_concept_ids),
        )
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        if val_res.metadata.get("duplicate_submission", False):
            path = self.adapter.path_generator.generate_path(learning_context, learner_state, all_subject_concept_ids)
            next_target = self.adapter.target_selector.select_next_target(path, learner_state, learning_context)
            return {
                "duplicate_submission": True,
                "updated_masteries": {
                    cid: learner_state.concept_states[cid].mastery_probability
                    for cid in concept_ids if cid in learner_state.concept_states
                },
                "path": path.model_dump(mode="json"),
                "next_target": next_target.model_dump(mode="json") if next_target else None,
            }

        updated_masteries, path, next_target = self.adapter.handle_activity_response_and_replan(
            learner_state=learner_state,
            learning_context=learning_context,
            subject_concept_ids=all_subject_concept_ids,
            concept_ids=concept_ids,
            correctness=correctness,
        )

        self.learner_service.save_learner_state(learner_state)
        if request_id:
            self.idempotency_tracker.mark_processed(request_id)

        return {
            "duplicate_submission": False,
            "updated_masteries": updated_masteries,
            "path": path.model_dump(mode="json"),
            "next_target": next_target.model_dump(mode="json") if next_target else None,
        }

    def get_concept_question(self, subject_id: str, concept_id: str) -> Dict[str, Any]:
        """
        Return a grounded multiple-choice question for a concept.

        Sourced from the persisted, provenance-checked bank. When the document has no
        passage that can support a question about the concept, a typed error is raised
        instead of falling back to a canned question.
        """
        bank = self.get_or_create_question_bank(subject_id, [concept_id])
        candidates = bank.get_by_concept(concept_id)
        if not candidates:
            raise ContentValidationError(
                f"The uploaded material does not contain enough information to write a "
                f"question about '{concept_id}'. Add material covering this concept and "
                f"try again.",
                details={"document_id": subject_id, "concept_id": concept_id},
            )

        q = candidates[0]
        return {
            "question_id": q.question_id,
            "concept_id": concept_id,
            "question_text": q.question_text,
            "options": q.options,
            "correct_answer": q.correct_answer,
            "explanation": q.explanation,
            # Real page/block citations, so the learner can check the material.
            "source_citations": [c.model_dump(mode="json") for c in q.source_citations],
        }

    def get_concept_learning_content(self, subject_id: str, concept_id: str) -> Dict[str, Any]:
        """
        Generate a lesson for a concept, grounded in the learner's own material.

        The passages retrieved for the concept are placed in the prompt and the model's
        citations are resolved back to real pages before the lesson is returned. If the
        model cites nothing usable, the request fails loudly: a lesson that invents
        examples and formulas is worse than an error.
        """
        ctx = self.knowledge_service.get_learning_context(subject_id)
        concept = ctx.concepts.get(concept_id)
        if concept is None:
            raise KnowledgeNotFoundError(
                f"'{concept_id}' is not a concept in '{subject_id}'.",
                details={"document_id": subject_id, "concept_id": concept_id},
            )

        retriever = self._retriever_for(subject_id)
        if retriever is None:
            raise RetrievalError(
                f"The passages of '{subject_id}' are unavailable, so a grounded lesson "
                f"cannot be produced.",
                details={"document_id": subject_id, "concept_id": concept_id},
            )

        chunks = retriever.retrieve_for_concept(concept_id, concept.canonical_name)
        evidence_block = EvidenceRetriever.format_evidence_for_prompt(chunks)
        ref_labels = {f"E{i}": chunk for i, chunk in enumerate(chunks, start=1)}

        prompt = (
            "Below are passages taken verbatim from the learner's own material.\n"
            f"{evidence_block}\n\n"
            f"Write a lesson about the concept \"{concept.canonical_name}\" using ONLY "
            "those passages.\n"
            "RULES:\n"
            "1. Every statement must be supported by the passages. Do not add outside "
            "knowledge, and do not invent examples, formulas or figures that are absent.\n"
            "2. The worked example must use a situation that actually appears in the "
            "passages.\n"
            "3. Cite the labels of the passages you used for the overview, the key "
            "principles and the worked example, e.g. [\"E1\"].\n"
            "4. Use ASCII characters for equations and symbols."
        )

        schema = {
            "overview": "string",
            "intuition": "string",
            "key_principles": [
                {"text": "string", "evidence_refs": ["string (e.g. 'E1')"]}
            ],
            "worked_example": {
                "problem": "string",
                "steps": ["string"],
                "solution": "string",
                "evidence_refs": ["string"],
            },
            "common_misconceptions": ["string"],
            "key_takeaway": "string",
            "evidence_refs": ["string (labels used overall)"],
        }

        res = self.adapter.llm_adapter.generate_json(prompt, schema)

        # Resolve the model's citations. An empty, malformed or unresolvable response
        # must not be turned into a lesson.
        raw_refs = res.get("evidence_refs") or []
        citations = _resolve_citations(raw_refs, ref_labels)
        if not citations:
            raise ContentValidationError(
                f"The generated lesson for '{concept.canonical_name}' did not cite any "
                f"passage from the uploaded material, so it cannot be trusted.",
                details={"document_id": subject_id, "concept_id": concept_id},
            )

        principles = []
        for entry in res.get("key_principles") or []:
            if isinstance(entry, dict):
                text = str(entry.get("text") or "").strip()
                refs = _resolve_citations(entry.get("evidence_refs") or [], ref_labels)
            else:
                text = str(entry or "").strip()
                refs = []
            if text:
                principles.append(
                    {
                        "text": text,
                        "source_citations": [c.model_dump(mode="json") for c in refs],
                    }
                )

        example = res.get("worked_example") or {}
        return {
            "concept_id": concept_id,
            "concept_name": concept.canonical_name,
            "subject_id": subject_id,
            "overview": str(res.get("overview") or "").strip(),
            "intuition": str(res.get("intuition") or "").strip(),
            "key_principles": principles,
            "worked_example": {
                "problem": str(example.get("problem") or "").strip(),
                "steps": [str(s).strip() for s in (example.get("steps") or []) if str(s).strip()],
                "solution": str(example.get("solution") or "").strip(),
                "source_citations": [
                    c.model_dump(mode="json")
                    for c in _resolve_citations(example.get("evidence_refs") or [], ref_labels)
                ],
            },
            "common_misconceptions": [
                str(m).strip() for m in (res.get("common_misconceptions") or []) if str(m).strip()
            ],
            "key_takeaway": str(res.get("key_takeaway") or "").strip(),
            "source_citations": [c.model_dump(mode="json") for c in citations],
        }


def _resolve_citations(refs: Any, ref_labels: Dict[str, Any]) -> List[SourceCitation]:
    """Map ``["E1", ...]`` labels onto real :class:`SourceCitation` objects."""
    out: List[SourceCitation] = []
    seen = set()
    for ref in refs or []:
        key = str(ref).strip().upper().lstrip("[]")
        chunk = ref_labels.get(key)
        if chunk is None:
            continue
        citation = SourceCitation(**chunk.citation())
        if citation.block_id in seen:
            continue
        seen.add(citation.block_id)
        out.append(citation)
    return out
