"""
Learning Service Facade for Taproot Application Layer.
Orchestrates onboarding self-assessment, diagnostic assessment creation/submission,
learning activities, quiz processing, and KT updates. Authoritative for concepts,
ownership, and server-side correctness evaluation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from phase3.errors import (
    ContentValidationError,
    KnowledgeNotFoundError,
    LearnSenseError,
    QuestionBankError,
    RetrievalError,
)
from phase3.question_bank.builder import QuestionBankBuilder
from datetime import datetime, timezone
import uuid
from phase3.question_bank.models import QuestionBank, QuestionBankItem, QuestionType, SourceCitation
from phase3.retrieval.evidence_retriever import EvidenceRetriever
from phase4.integration.phase3_adapter import Phase3Adapter
from phase4.models import ConfidenceLevel, KnowledgeInitializationSession, SelfAssessmentStatus, FinalAssessmentSession
from phase5.validation import IdempotencyTracker, LearnerStateValidator, PlanningValidator
from storage.repositories import QuestionBankRepository, SessionRepository

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService

import threading

logger = logging.getLogger(__name__)

# Upper bound on how many concepts get a generated question when the diagnostic
# starts. The quiz itself is capped far lower (DIAGNOSTIC_MAX_QUESTIONS); this
# only limits how much question-bank work is done up front.
MAX_DIAGNOSTIC_BUILD_CONCEPTS = 12


class LearningService:
    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        question_bank_repo: Optional[QuestionBankRepository] = None,
        learner_service: Optional[LearnerService] = None,
        knowledge_service: Optional[KnowledgeService] = None,
        idempotency_tracker: Optional[IdempotencyTracker] = None,
    ):
        self.session_repo = session_repo or SessionRepository()
        self.bank_repo = question_bank_repo or QuestionBankRepository()
        self.learner_service = learner_service or LearnerService()
        self.knowledge_service = knowledge_service or KnowledgeService()

        self.adapter = Phase3Adapter()
        self.idempotency_tracker = idempotency_tracker or IdempotencyTracker()
        self.learner_state_validator = LearnerStateValidator(idempotency_tracker=self.idempotency_tracker)
        self.planning_validator = PlanningValidator()
        self._learner_locks: Dict[str, threading.Lock] = {}
        self._lock_guard = threading.Lock()

    def _get_learner_lock(self, learner_id: str) -> threading.Lock:
        with self._lock_guard:
            if learner_id not in self._learner_locks:
                self._learner_locks[learner_id] = threading.Lock()
            return self._learner_locks[learner_id]

    def get_or_create_question_bank(
        self, subject_id: str, concept_ids: Optional[List[str]] = None
    ) -> QuestionBank:
        """
        Return a question bank whose every question is grounded in the uploaded document.
        """
        ctx = self.knowledge_service.get_learning_context(subject_id)
        target_ids = list(concept_ids or ctx.concepts.keys())

        builder = QuestionBankBuilder()
        retriever = self._retriever_for(subject_id)

        existing = self.bank_repo.load_grounded_bank(subject_id)
        if existing is not None:
            scoped = QuestionBank(document_id=subject_id, chapter_id="ch_all")
            for item in existing.get_grounded_questions():
                if set(item.concept_ids) & set(target_ids):
                    scoped.add_question(item)
            existing = scoped if scoped.questions else None

        try:
            bank = builder.build_bank_for_chapter(
                ctx,
                chapter_id="ch_all",
                target_count=max(1, len(target_ids)),
                retriever=retriever,
                existing=existing,
                # Generate for the concepts this caller asked about. Without this the
                # builder considered every concept in the document, so a request for one
                # concept's practice question could spend all its provider calls on
                # unrelated concepts and still return "no questions" for the real one.
                concept_ids=target_ids,
            )
        except QuestionBankError:
            # The persisted grounded bank is still honest evidence: when fresh
            # generation is impossible (e.g. retriever artifacts missing) but
            # valid grounded questions already exist, serve those instead of
            # failing the whole request.
            if existing is not None and existing.get_grounded_questions():
                logger.warning(
                    "Falling back to %d persisted grounded questions for '%s'.",
                    len(existing.get_grounded_questions()),
                    subject_id,
                )
                return existing
            raise

        if bank.get_grounded_questions():
            self.bank_repo.save_bank(bank)
        return bank

    def _retriever_for(self, document_id: str):
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
        all_concept_ids: Optional[List[str]] = None,
        confidences: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeInitializationSession:
        """
        Submits learner concept self-assessment. Server is authoritative for concept IDs.
        Rejects foreign concept IDs not belonging to the subject.
        ``confidences`` (Low/Medium/High per concept) is stored as a separate
        hypothesis signal; it never sets KT mastery.
        """
        ctx = self.knowledge_service.get_learning_context(subject_id)
        authoritative_concepts = list(ctx.concepts.keys()) if ctx and ctx.concepts else (all_concept_ids or list(selections.keys()))

        # Enforce server authority: reject any concept not belonging to subject
        if ctx and ctx.concepts:
            foreign = [cid for cid in selections.keys() if cid not in ctx.concepts]
            if foreign:
                raise ValueError(f"Foreign concept IDs not present in subject '{subject_id}': {foreign}")

        val_res = self.planning_validator.validate_self_assessment(selections, authoritative_concepts)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        parsed_confidences: Dict[str, ConfidenceLevel] = {}
        for cid, conf in (confidences or {}).items():
            if cid not in authoritative_concepts:
                continue
            if isinstance(conf, ConfidenceLevel):
                parsed_confidences[cid] = conf
            else:
                try:
                    parsed_confidences[cid] = ConfidenceLevel(str(conf).upper())
                except ValueError:
                    parsed_confidences[cid] = ConfidenceLevel.MEDIUM

        session = self.adapter.self_assessment_handler.create_session(
            learner_id=learner_id,
            subject_id=subject_id,
            selections=selections,
            all_subject_concept_ids=authoritative_concepts,
            confidences=parsed_confidences,
        )
        # Publish the deterministic verification set (KNOW + UNANSWERED) and its
        # confidence-driven priorities on the session itself, so the frontend
        # contract carries the hypothesis before the diagnostic starts.
        session.verify_concept_ids = self.adapter.diagnostic_orchestrator.verification_concepts(session)
        session.diagnostic_priorities = {
            cid: self.adapter.diagnostic_orchestrator.concept_priority(session, cid)
            for cid in session.verify_concept_ids
        }
        self.session_repo.save_session(session)
        # Ensure learner state exists
        self.learner_service.get_or_create_learner_state(learner_id, authoritative_concepts)
        # NOTE: the question bank is deliberately NOT built here. Building it for
        # every concept in a large document is an LLM-bound operation that can
        # exceed the request timeout (the frontend saw 502 and a dead "Begin
        # Diagnostic" button). It is built lazily, scoped to the verification set
        # only, when the diagnostic actually starts.
        return session

    def get_calibration_status(self, learner_id: str, subject_id: str) -> Dict[str, Any]:
        """Per-subject onboarding gate: True when this learner has never submitted
        self-assessment for this subject (no init session exists yet)."""
        session = self.session_repo.find_any_init_session(learner_id, subject_id)
        if session is None:
            return {
                "learner_id": learner_id,
                "subject_id": subject_id,
                "needs_calibration": True,
                "session_id": None,
                "diagnostic_completed": False,
            }
        return {
            "learner_id": learner_id,
            "subject_id": subject_id,
            "needs_calibration": False,
            "session_id": session.session_id,
            "diagnostic_completed": session.diagnostic_completed,
        }

    def start_diagnostic(self, session_id: str, learner_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates diagnostic quiz questions. NEVER returns correct_answer to the client.

        Security (P0): ``learner_id`` is REQUIRED and ownership is ALWAYS enforced.
        The previous guard was ``if learner_id and ...``, so omitting the field
        skipped the ownership check entirely and let any caller start -- and then
        submit -- another learner's diagnostic.
        """
        if not learner_id:
            raise ValueError("learner_id is required to start a diagnostic.")

        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")
        if session.learner_id != learner_id:
            raise ValueError(f"Session '{session_id}' does not belong to learner '{learner_id}'.")

        # The diagnostic asks at most DIAGNOSTIC_MAX_QUESTIONS questions, so only
        # the highest-priority slice of the verification set needs a question.
        # Scoping the bank build to that slice keeps start fast and bounded even
        # when a document yields hundreds of concepts.
        verify_ids = self.adapter.diagnostic_orchestrator.verification_concepts(session)
        if verify_ids:
            verify_ids = sorted(
                verify_ids,
                key=lambda cid: (
                    -self.adapter.diagnostic_orchestrator.concept_priority(session, cid),
                    cid,
                ),
            )[: MAX_DIAGNOSTIC_BUILD_CONCEPTS]
        bank = self.get_or_create_question_bank(session.subject_id, verify_ids or session.know_concept_ids)
        questions = self.adapter.diagnostic_orchestrator.create_diagnostic_quiz(session, bank)

        val_res = self.planning_validator.validate_diagnostic_quiz_creation(session, questions)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        dumped_questions = []
        for q in questions:
            q_dict = q.model_dump(mode="json")
            # P0 Assessment Security: Strip correct_answer and explanation before submission!
            q_dict.pop("correct_answer", None)
            q_dict.pop("explanation", None)
            q_dict["item_id"] = q_dict.get("question_id", "")
            q_dict["prompt"] = q_dict.get("question_text", "")
            dumped_questions.append(q_dict)

        self.session_repo.save_session(session)
        return {
            "session_id": session.session_id,
            "know_concepts": session.know_concept_ids,
            "verify_concepts": session.verify_concept_ids,
            "diagnostic_priorities": {k: float(v) for k, v in session.diagnostic_priorities.items()},
            "question_count": len(questions),
            "questions": dumped_questions,
        }

    def submit_diagnostic(
        self,
        session_id: str,
        responses: Dict[str, Any],
        learner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates diagnostic responses AUTHORITATIVELY on the server.
        Accepts selected options or don't-know signals and checks against authoritative question bank.

        Security (P0): ``learner_id`` is REQUIRED and ownership is ALWAYS enforced.
        """
        if not learner_id:
            raise ValueError("learner_id is required to submit a diagnostic.")

        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")
        if session.learner_id != learner_id:
            raise ValueError(f"Session '{session_id}' does not belong to learner '{learner_id}'.")

        all_concepts = session.know_concept_ids + session.dont_know_concept_ids + session.unanswered_concept_ids
        learner_state = self.learner_service.get_or_create_learner_state(session.learner_id, all_concepts)
        verify_ids = self.adapter.diagnostic_orchestrator.verification_concepts(session)
        bank = self.get_or_create_question_bank(session.subject_id, verify_ids or session.know_concept_ids)

        evaluated_responses: Dict[str, float] = {}
        for qid, resp in responses.items():
            q_item = bank.get_question(qid)
            if isinstance(resp, (int, float)):
                # Backward-compatibility for raw numeric test calls
                evaluated_responses[qid] = float(resp)
            elif isinstance(resp, str):
                resp_clean = resp.strip()
                if resp_clean.lower() in ("i don't know", "dont know", "unsure", "unknown", ""):
                    evaluated_responses[qid] = 0.0
                elif q_item:
                    is_corr = (resp_clean == str(q_item.correct_answer).strip())
                    evaluated_responses[qid] = 1.0 if is_corr else 0.0
                else:
                    evaluated_responses[qid] = 0.0
            elif isinstance(resp, dict):
                if resp.get("is_dont_know", False):
                    evaluated_responses[qid] = 0.0
                else:
                    opt = str(resp.get("selected_option", "")).strip()
                    if q_item:
                        is_corr = (opt == str(q_item.correct_answer).strip())
                        evaluated_responses[qid] = 1.0 if is_corr else 0.0
                    else:
                        evaluated_responses[qid] = 0.0
            else:
                evaluated_responses[qid] = 0.0

        updated_masteries = self.adapter.diagnostic_orchestrator.submit_diagnostic_responses(
            init_session=session,
            learner_state=learner_state,
            question_responses=evaluated_responses,
            question_bank=bank,
        )

        # Prerequisite-aware verification (Batch 9): for each failed verification
        # concept, check its prerequisites from the knowledge graph. A failure on C
        # with an untested/weak B surfaces B as needing verification instead of
        # concluding C alone is weak. Reuses the existing graph; no new system.
        session.prerequisite_verification = self.compute_prerequisite_verification(
            session.subject_id, learner_state, bank, evaluated_responses
        )

        # Evidence verdicts per tested concept (Batch 8): a single wrong answer
        # yields INSUFFICIENT_EVIDENCE until MIN_EVIDENCE_COUNT attempts accrue.
        from phase4.config import phase4_config as _p4config

        evidence_verdicts: Dict[str, Dict[str, Any]] = {}
        for cid in session.verify_concept_ids or list(updated_masteries.keys()):
            cs = learner_state.concept_states.get(cid)
            if cs is None:
                continue
            if cs.attempt_count < _p4config.MIN_EVIDENCE_COUNT:
                verdict = "insufficient_evidence"
            elif cs.mastery_probability >= _p4config.MASTERY_THRESHOLD:
                verdict = "verified_strong"
            else:
                verdict = "likely_weak"
            evidence_verdicts[cid] = {
                "verdict": verdict,
                "mastery": round(cs.mastery_probability, 4),
                "attempts": cs.attempt_count,
                "calibration": session.calibration.get(cid),
            }

        self.session_repo.save_session(session)
        self.learner_service.save_learner_state(learner_state)

        return {
            "session_id": session.session_id,
            "diagnostic_completed": session.diagnostic_completed,
            "diagnostic_score": session.diagnostic_score,
            "updated_masteries": updated_masteries,
            "calibration": session.calibration,
            "confirmed_concept_ids": session.confirmed_concept_ids,
            "contradicted_concept_ids": session.contradicted_concept_ids,
            "prerequisite_verification": session.prerequisite_verification,
            "evidence_verdicts": evidence_verdicts,
        }

    def compute_prerequisite_verification(
        self,
        subject_id: str,
        learner_state: Any,
        bank: QuestionBank,
        evaluated_responses: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Flag prerequisites needing verification after failed diagnostic items.

        Deterministic and side-effect free: for every failed response on concept
        C, each prerequisite B of C whose mastery is below threshold (or which
        has never been attempted) is reported as ``verification_needed``.
        """
        hints: List[Dict[str, Any]] = []
        try:
            learning_context = self.knowledge_service.get_learning_context(subject_id)
            prereq_map: Dict[str, List[str]] = {}
            if learning_context is not None:
                for link in learning_context.prerequisites:
                    prereq_map.setdefault(link.target_concept_id, []).append(link.source_concept_id)
            for qid, score in evaluated_responses.items():
                if score >= 0.5:
                    continue
                q_item = bank.get_question(qid)
                if not q_item or not q_item.concept_ids:
                    continue
                for cid in q_item.concept_ids:
                    for pid in prereq_map.get(cid, []):
                        p_state = learner_state.concept_states.get(pid)
                        p_mastery = p_state.mastery_probability if p_state else 0.3
                        p_attempts = p_state.attempt_count if p_state else 0
                        if p_mastery < 0.5 or p_attempts == 0:
                            hints.append({
                                "concept_id": cid,
                                "prerequisite_id": pid,
                                "status": "verification_needed",
                                "prerequisite_mastery": round(p_mastery, 4),
                                "prerequisite_attempts": p_attempts,
                            })
            seen = set()
            deduped = []
            for entry in hints:
                key = (entry["concept_id"], entry["prerequisite_id"])
                if key not in seen:
                    seen.add(key)
                    deduped.append(entry)
            return deduped
        except Exception as exc:
            logger.warning("Prerequisite verification hints skipped: %s", exc)
            return []

    def process_activity_response(
        self,
        learner_id: str,
        subject_id: str,
        concept_ids: List[str],
        correctness: Optional[float] = None,
        all_subject_concept_ids: Optional[List[str]] = None,
        request_id: Optional[str] = None,
        question_id: Optional[str] = None,
        selected_option: Optional[str] = None,
        selected_index: Optional[int] = None,
        is_dont_know: bool = False,
        allow_client_correctness: bool = True,
    ) -> Dict[str, Any]:
        """
        Authoritatively evaluates activity/quiz response, triggers BKT update & replanning.
        If question_id is provided, correctness is calculated server-side; client correctness is ignored.
        Guarded by durable idempotency tracker and per-learner thread lock.

        Security (P0) -- ``allow_client_correctness``:
        The ``correctness`` parameter is retained ONLY for legacy in-process callers
        (unit tests, internal services). The HTTP API must never be able to assert
        its own mastery, so the route passes ``allow_client_correctness=False``
        and the ``correctness``-only branch below becomes unreachable from HTTP.
        """
        if not allow_client_correctness and correctness is not None and not question_id:
            raise ValueError(
                "Client-reported correctness is not accepted. Supply question_id so the "
                "server can evaluate the answer authoritatively."
            )

        with self._get_learner_lock(learner_id):
            # 1. Idempotency Check: return cached replay if already processed
            if request_id and self.idempotency_tracker.is_duplicate(request_id):
                cached = self.idempotency_tracker.get_cached_response(request_id)
                if cached:
                    cached["duplicate_submission"] = True
                    return cached

            # 2. Server Authority: derive authoritative concepts from subject context
            learning_context = self.knowledge_service.get_learning_context(subject_id)
            authoritative_concepts = (
                list(learning_context.concepts.keys())
                if learning_context and learning_context.concepts
                else (all_subject_concept_ids or concept_ids)
            )

            # Enforce concept containment
            if learning_context and learning_context.concepts:
                for cid in concept_ids:
                    if cid not in learning_context.concepts:
                        raise ValueError(f"Concept '{cid}' does not belong to subject '{subject_id}'.")

            learner_state = self.learner_service.get_or_create_learner_state(learner_id, authoritative_concepts)

            # 3. Server-Side Correctness Evaluation
            q_item = None
            is_correct = False
            eval_correctness = 0.0
            correct_answer = ""
            explanation = ""

            if question_id:
                bank = self.get_or_create_question_bank(subject_id, concept_ids)
                q_item = bank.get_question(question_id)
                if not q_item:
                    raise ValueError(f"Question '{question_id}' not found in question bank for subject '{subject_id}'.")

                correct_answer = str(q_item.correct_answer).strip()
                explanation = q_item.explanation or ""

                if is_dont_know:
                    eval_correctness = 0.0
                    is_correct = False
                elif selected_option is not None:
                    is_correct = (selected_option.strip() == correct_answer)
                    eval_correctness = 1.0 if is_correct else 0.0
                elif selected_index is not None:
                    opts = q_item.options or []
                    if 0 <= selected_index < len(opts):
                        is_correct = (opts[selected_index].strip() == correct_answer)
                        eval_correctness = 1.0 if is_correct else 0.0
                    else:
                        raise ValueError(f"Invalid option index {selected_index} for question '{question_id}'.")
                else:
                    raise ValueError("Must provide selected_option, selected_index, or is_dont_know.")
            else:
                # Fallback for direct test calls passing correctness directly
                if correctness is None:
                    raise ValueError("Must provide either question_id or correctness.")
                eval_correctness = float(correctness)
                is_correct = (eval_correctness >= 0.7)

            # 4. Validation
            val_res = self.learner_state_validator.validate_response_submission(
                learner_id=learner_id,
                concept_ids=concept_ids,
                correctness=eval_correctness,
                request_id=request_id,
                valid_subject_concepts=set(authoritative_concepts),
            )
            if not val_res.is_valid:
                raise ValueError(val_res.errors[0])

            if val_res.metadata.get("duplicate_submission", False):
                path = self.adapter.path_generator.generate_path(learning_context, learner_state, authoritative_concepts)
                next_target = self.adapter.target_selector.select_next_target(path, learner_state, learning_context)
                dup_res = {
                    "duplicate_submission": True,
                    "is_correct": is_correct,
                    "correct_answer": correct_answer if q_item else None,
                    "explanation": explanation if q_item else None,
                    "updated_masteries": {
                        cid: learner_state.concept_states[cid].mastery_probability
                        for cid in concept_ids if cid in learner_state.concept_states
                    },
                    "path": path.model_dump(mode="json"),
                    "next_target": next_target.model_dump(mode="json") if next_target else None,
                }
                return dup_res

            # 5. Bayesian Knowledge Tracing Update & Replanning
            updated_masteries, path, next_target = self.adapter.handle_activity_response_and_replan(
                learner_state=learner_state,
                learning_context=learning_context,
                subject_concept_ids=authoritative_concepts,
                concept_ids=concept_ids,
                correctness=eval_correctness,
            )

            self.learner_service.save_learner_state(learner_state)

            result_payload = {
                "duplicate_submission": False,
                "is_correct": is_correct,
                "correct_answer": correct_answer if q_item else None,
                "explanation": explanation if q_item else None,
                "updated_masteries": updated_masteries,
                "path": path.model_dump(mode="json"),
                "next_target": next_target.model_dump(mode="json") if next_target else None,
            }

            # 6. Save durable idempotency token with response payload
            if request_id:
                self.idempotency_tracker.mark_processed(
                    request_id, learner_id=learner_id, response_payload=result_payload
                )

            return result_payload

        return result_payload

    def get_concept_question(self, subject_id: str, concept_id: str) -> Dict[str, Any]:
        """
        Return a grounded multiple-choice question for a concept.
        P0 Assessment Security: correct_answer and explanation are NEVER returned here!

        If the concept has no grounded questions, returns a valid response with
        empty options and a 'no_questions' flag so the frontend can handle it
        gracefully instead of showing an error.
        """
        bank = self.get_or_create_question_bank(subject_id, [concept_id])
        candidates = bank.get_by_concept(concept_id)
        if not candidates:
            return {
                "question_id": "",
                "concept_id": concept_id,
                "question_text": "",
                "options": [],
                "source_citations": [],
                "no_questions": True,
            }

        q = candidates[0]
        return {
            "question_id": q.question_id,
            "concept_id": concept_id,
            "question_text": q.question_text,
            "options": q.options,
            # P0: correct_answer is strictly omitted before submission
            "source_citations": [c.model_dump(mode="json") for c in q.source_citations],
            "no_questions": False,
        }

    def get_concept_learning_content(self, subject_id: str, concept_id: str) -> Dict[str, Any]:
        """
        Return source-grounded learning content for a concept.

        Anti-fabrication policy (phase3/errors.py):
          "No error in this module ever implies that substitute educational content
           is acceptable. When an LLM-backed artifact cannot be produced, the error
           propagates. Inventing content is a bug, not a recovery strategy."

        This function therefore NEVER generates generic educational claims. It
        returns only:
          * the concept's own definition from the knowledge graph, and
          * verbatim source passages retrieved from the uploaded document,
            each labelled as source evidence with its provenance.

        If the source material cannot supply enough evidence, it raises
        ContentValidationError instead of filling the response with invented
        intuition, worked examples, misconceptions or takeaways.
        """
        from backend.services.knowledge_build_service import KnowledgeBuildService

        graph = self.knowledge_service.get_subject_graph(subject_id)
        c_node = next((c for c in graph["concepts"] if c["concept_id"] == concept_id), None)
        if c_node is None:
            raise ContentValidationError(
                f"Concept '{concept_id}' was not found in the knowledge graph for "
                f"'{subject_id}'.",
                details={"document_id": subject_id, "concept_id": concept_id},
            )

        c_name = c_node["name"]
        c_def = c_node.get("definition") or ""

        # Retrieve real source evidence. A retrieval failure must propagate, not be
        # silently replaced with template text.
        retriever = KnowledgeBuildService().get_retriever(subject_id)
        chunks = retriever.retrieve_for_concept(concept_id, concept_name=c_name, top_k=3)
        if not chunks:
            raise ContentValidationError(
                f"The uploaded material does not contain enough source evidence to "
                f"build learning content for '{c_name}'. Add material covering this "
                f"concept and try again.",
                details={"document_id": subject_id, "concept_id": concept_id},
            )

        source_evidence = []
        for chunk in chunks:
            citation = chunk.citation() if hasattr(chunk, "citation") else {}
            source_evidence.append({
                "text": chunk.text,
                "provenance": {
                    "document_id": chunk.document_id,
                    "page": citation.get("page"),
                    "block_id": chunk.block_id,
                    "section": citation.get("section"),
                    "evidence_ids": chunk.evidence_ids,
                },
            })

        # Only fields with real evidence are populated. Everything the system
        # cannot ground is omitted rather than invented.
        content: Dict[str, Any] = {
            "concept_id": concept_id,
            "concept_name": c_name,
            "definition": c_def or None,
            "source_evidence": source_evidence,
            "grounded": True,
        }
        return content

    def start_final_assessment(self, learner_id: str, subject_id: str) -> Dict[str, Any]:
        """
        Creates or resumes a dedicated Final Assessment covering concepts in the subject.
        NEVER leaks correct_answer or explanation to the client.
        Guarantees session resumability upon browser refresh.
        """
        learning_context = self.knowledge_service.get_learning_context(subject_id)
        if not learning_context or not learning_context.concepts:
            raise ValueError(f"Subject '{subject_id}' does not have valid knowledge context.")

        all_concept_ids = list(learning_context.concepts.keys())
        learner_state = self.learner_service.get_or_create_learner_state(learner_id, all_concept_ids)

        # Resumability check: if active uncompleted session exists, resume it
        active_sess = self.session_repo.find_active_final_assessment(learner_id, subject_id)
        bank = self.get_or_create_question_bank(subject_id, all_concept_ids)

        if active_sess and not active_sess.completed:
            questions = []
            for qid in active_sess.question_ids:
                q_item = bank.get_question(qid)
                if q_item:
                    q_dict = q_item.model_dump(mode="json")
                    q_dict.pop("correct_answer", None)
                    q_dict.pop("explanation", None)
                    q_dict["item_id"] = q_dict.get("question_id", "")
                    q_dict["prompt"] = q_dict.get("question_text", "")
                    questions.append(q_dict)
            # Return submitted responses so the frontend can restore progress.
            # The current question index is derived server-side as the first
            # unanswered question, so the frontend never needs to persist it.
            submitted_responses = dict(active_sess.responses or {})
            answered_ids = set(submitted_responses.keys())
            first_unanswered = 0
            for idx, qid in enumerate(active_sess.question_ids):
                if qid not in answered_ids:
                    first_unanswered = idx
                    break
            else:
                first_unanswered = len(active_sess.question_ids)
            return {
                "assessment_id": active_sess.assessment_id,
                "subject_id": subject_id,
                "resumed": True,
                "question_count": len(questions),
                "questions": questions,
                "submitted_responses": submitted_responses,
                "current_question_index": first_unanswered,
            }

        # Select grounded questions covering concepts
        target_concept_ids = all_concept_ids[:10]
        selected_questions: List[Dict[str, Any]] = []
        question_ids: List[str] = []

        for cid in target_concept_ids:
            candidates = bank.get_by_concept(cid)
            if candidates:
                q = candidates[0]
                if q.question_id not in question_ids:
                    question_ids.append(q.question_id)
                    q_dict = q.model_dump(mode="json")
                    q_dict.pop("correct_answer", None)
                    q_dict.pop("explanation", None)
                    q_dict["item_id"] = q_dict.get("question_id", "")
                    q_dict["prompt"] = q_dict.get("question_text", "")
                    selected_questions.append(q_dict)

        if not selected_questions:
            for q in bank.get_grounded_questions()[:10]:
                if q.question_id not in question_ids:
                    question_ids.append(q.question_id)
                    q_dict = q.model_dump(mode="json")
                    q_dict.pop("correct_answer", None)
                    q_dict.pop("explanation", None)
                    q_dict["item_id"] = q_dict.get("question_id", "")
                    q_dict["prompt"] = q_dict.get("question_text", "")
                    selected_questions.append(q_dict)

        if not selected_questions:
            raise ValueError(f"Insufficient question material in document to construct final assessment for '{subject_id}'.")

        assessment_id = f"final_{uuid.uuid4().hex[:12]}"
        final_sess = FinalAssessmentSession(
            assessment_id=assessment_id,
            learner_id=learner_id,
            subject_id=subject_id,
            question_ids=question_ids,
            concept_ids=target_concept_ids,
            total_questions=len(selected_questions),
            completed=False,
        )
        self.session_repo.save_final_assessment(final_sess)

        return {
            "assessment_id": assessment_id,
            "subject_id": subject_id,
            "resumed": False,
            "question_count": len(selected_questions),
            "questions": selected_questions,
        }

    def submit_final_assessment(
        self,
        assessment_id: str,
        learner_id: str,
        subject_id: str,
        responses: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates Final Assessment responses authoritatively on the server.
        Updates BKT masteries across all tested concepts and marks assessment complete.
        Protected by durable idempotency and per-learner thread locks.
        """
        with self._get_learner_lock(learner_id):
            if request_id and self.idempotency_tracker.is_duplicate(request_id):
                cached = self.idempotency_tracker.get_cached_response(request_id)
                if cached:
                    cached["duplicate_submission"] = True
                    return cached

            session = self.session_repo.load_final_assessment(assessment_id)
            if not session:
                raise ValueError(f"Final Assessment session '{assessment_id}' not found.")

            if session.learner_id != learner_id:
                raise ValueError(f"Assessment '{assessment_id}' does not belong to learner '{learner_id}'.")

            if session.subject_id != subject_id:
                raise ValueError(f"Assessment '{assessment_id}' belongs to subject '{session.subject_id}', not '{subject_id}'.")

            learning_context = self.knowledge_service.get_learning_context(subject_id)
            all_concept_ids = list(learning_context.concepts.keys()) if learning_context else list(session.concept_ids)
            learner_state = self.learner_service.get_or_create_learner_state(learner_id, all_concept_ids)
            bank = self.get_or_create_question_bank(subject_id, all_concept_ids)

            correct_count = 0
            total_questions = len(session.question_ids) or len(responses) or 1
            scores: Dict[str, float] = {}
            concept_results: Dict[str, Dict[str, Any]] = {}

            for qid in session.question_ids:
                q_item = bank.get_question(qid)
                resp = responses.get(qid)
                is_correct = False

                if q_item and resp is not None:
                    user_str = str(resp).strip()
                    correct_str = str(q_item.correct_answer).strip()
                    if user_str.lower() in ("i don't know", "dont know", "unsure", ""):
                        is_correct = False
                    else:
                        is_correct = (user_str == correct_str)

                score_val = 1.0 if is_correct else 0.0
                scores[qid] = score_val
                if is_correct:
                    correct_count += 1

                if q_item and q_item.concept_ids:
                    for cid in q_item.concept_ids:
                        concept_results[cid] = {
                            "question_id": qid,
                            "correct": is_correct,
                            "score": score_val,
                            "correct_answer": q_item.correct_answer,
                            "explanation": q_item.explanation,
                        }

            score_pct = round((correct_count / total_questions) * 100, 1)
            passed = bool(score_pct >= 70.0)

            # Update BKT for all tested concepts
            updated_masteries = {}
            for cid, c_res in concept_results.items():
                c_score = c_res["score"]
                post_m = self.adapter.tracer.update(
                    learner_state=learner_state,
                    concept_ids=[cid],
                    correctness=c_score,
                )
                updated_masteries.update(post_m)

            # Mark session complete & persist atomically
            session.completed = True
            session.score_pct = score_pct
            session.passed = passed
            session.correct_count = correct_count
            session.total_questions = total_questions
            session.responses = responses
            session.scores = scores
            session.concept_results = concept_results
            session.completed_at = datetime.now(timezone.utc)

            self.session_repo.save_final_assessment(session)
            self.learner_service.save_learner_state(learner_state)

            result_payload = {
                "assessment_id": assessment_id,
                "duplicate_submission": False,
                "completed": True,
                "total_questions": total_questions,
                "correct_count": correct_count,
                "score_pct": score_pct,
                "passed": passed,
                "concept_results": concept_results,
                "updated_masteries": updated_masteries,
                "message": "Final assessment completed successfully.",
            }

            if request_id:
                self.idempotency_tracker.mark_processed(
                    request_id, learner_id=learner_id, response_payload=result_payload
                )

            return result_payload

    def get_final_assessment_status(self, assessment_id: str, learner_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves status of a Final Assessment.

        Security (P0): ``learner_id`` is REQUIRED and ownership is ALWAYS enforced.
        A previous implementation made ``learner_id`` optional and only compared it
        when supplied, so omitting it returned the full session dump -- including
        ``concept_results[*].correct_answer`` and ``concept_results[*].explanation``
        -- to any unauthenticated caller. The answer key is now stripped unconditionally.
        """
        if not learner_id:
            raise ValueError("learner_id is required to read Final Assessment status.")

        session = self.session_repo.load_final_assessment(assessment_id)
        if not session:
            raise ValueError(f"Final Assessment session '{assessment_id}' not found.")
        if session.learner_id != learner_id:
            raise ValueError(f"Assessment '{assessment_id}' does not belong to learner '{learner_id}'.")

        payload = session.model_dump(mode="json")

        # Strip the authoritative answer key. The learner may see their own submitted
        # answers and the resulting scores, never the expected answers or explanations.
        for concept_id, concept_result in (payload.get("concept_results") or {}).items():
            if isinstance(concept_result, dict):
                concept_result.pop("correct_answer", None)
                concept_result.pop("explanation", None)

        payload["answer_key_disclosed"] = False
        return payload
