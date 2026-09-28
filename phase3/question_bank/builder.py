"""
Question Bank Builder for Phase 3.

Every question LearnSense serves is derived from the learner's own uploaded material:

* SOURCE questions reuse the real text of a Phase 2 ``AssessableItem``'s source spans.
* GENERATED questions are produced by the LLM from passages retrieved out of the
  document by :class:`~phase3.retrieval.evidence_retriever.EvidenceRetriever`. The
  passages are labelled ``[E1]``, ``[E2]`` ... in the prompt and the model must cite
  the labels it used; every citation is resolved back to a real block/page before the
  question is accepted.

Deliberately absent: placeholder topics, "Generated Question" prompts, "See detailed
solution in text" answers and synthetic "variant" duplicates. If the material cannot
ground a question, :class:`~phase3.errors.QuestionBankError` is raised instead.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from phase3.adapters.llm_adapter import Phase3LLMAdapter
from phase3.errors import QuestionBankError, RetrievalError
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.question_bank.models import (
    QuestionBank,
    QuestionBankItem,
    QuestionSourceType,
    QuestionType,
    QuestionValidationStatus,
    SourceCitation,
)
from phase3.question_bank.validator import QuestionBankDeduplicator, QuestionBankValidator
from phase3.retrieval.evidence_retriever import EvidenceRetriever, SourceChunk

logger = logging.getLogger(__name__)

# How many passages of the learner's own text to show the model per request.
_PASSAGES_PER_REQUEST = 8
# Chapters of a real document rarely need more than this many generation rounds.
_MAX_GENERATION_ROUNDS = 6


class QuestionBankBuilder:
    """
    Builds (and reuses) a grounded question bank for one chapter.

    Parameters
    ----------
    llm_adapter:
        Adapter used for generation. Only ever called when the persisted bank is
        missing questions, so a reused bank costs zero provider requests.
    """

    def __init__(self, llm_adapter: Optional[Phase3LLMAdapter] = None) -> None:
        self.llm_adapter = llm_adapter or Phase3LLMAdapter()
        self._llm_calls = 0

    @property
    def llm_calls(self) -> int:
        """Number of provider requests made. Zero when a valid bank was reused."""
        return self._llm_calls

    # -- public API ---------------------------------------------------------

    def build_bank_for_chapter(
        self,
        context: LearningContext,
        chapter_id: str = "ch_1",
        target_count: int = 25,
        retriever: Optional[EvidenceRetriever] = None,
        existing: Optional[QuestionBank] = None,
    ) -> QuestionBank:
        """
        Return a question bank for ``chapter_id``, generating only what is missing.

        ``existing`` (usually the persisted bank) is kept as-is; questions are only
        generated for concepts that have fewer than ``min_per_concept`` grounded items.
        """
        bank = existing or QuestionBank(document_id=context.document_id, chapter_id=chapter_id)
        bank.document_id = context.document_id
        bank.chapter_id = chapter_id

        # 1. Reuse every already-valid, grounded question.
        for item in bank.get_grounded_questions():
            bank.add_question(item)

        # 2. Seed questions straight from real exercises in the material.
        self._seed_from_assessable_items(context, bank, chapter_id, retriever)

        if len(bank.get_grounded_questions()) >= target_count:
            logger.info(
                "Reusing %d persisted grounded questions for %s/%s (no LLM call).",
                len(bank.get_grounded_questions()),
                context.document_id,
                chapter_id,
            )
            return bank

        # 3. Generate only for concepts that are still short of questions.
        if retriever is None:
            raise QuestionBankError(
                "Cannot build a question bank for this chapter: the uploaded material's "
                "source passages are unavailable, so questions could not be grounded. "
                "Re-upload the document or load the persisted knowledge representation.",
                details={"document_id": context.document_id, "chapter_id": chapter_id},
            )

        covered = self._concept_coverage(bank)
        shortfalls = self._concepts_needing_questions(context, covered, target_count)
        if not shortfalls:
            return bank

        self._generate_for_concepts(context, bank, chapter_id, target_count, retriever, shortfalls)

        grounded = len(bank.get_grounded_questions())
        if not grounded:
            raise QuestionBankError(
                "No question could be grounded in the uploaded material. The document may "
                "be too short, scanned without readable text, or unrelated to the concepts "
                "that were extracted from it.",
                details={"document_id": context.document_id, "chapter_id": chapter_id},
            )

        logger.info(
            "Built %d grounded questions for %s/%s using %d LLM call(s).",
            grounded,
            context.document_id,
            chapter_id,
            self._llm_calls,
        )
        return bank

    # -- step 1: real source questions -------------------------------------

    def _seed_from_assessable_items(
        self,
        context: LearningContext,
        bank: QuestionBank,
        chapter_id: str,
        retriever: Optional[EvidenceRetriever],
    ) -> None:
        """
        Turn each Phase 2 exercise into a question using the exercise's own text.

        An ``AssessableItem`` stores no prompt text of its own - it points at the unit
        whose ``source`` spans hold the real block IDs. Those blocks are resolved to
        text here, so the question text is the learner's material rather than a
        description of it.
        """
        existing_ids = set(bank.questions.keys())
        chunks_by_block: Dict[str, SourceChunk] = {}
        if retriever is not None:
            chunks_by_block = dict(retriever._chunks_by_block)  # noqa: SLF001

        for item_id, item in context.assessable_items.items():
            if f"src_{item_id}" in existing_ids:
                continue

            unit = context.educational_units.get(item.unit_id)
            concept_ids = [c for c in (item.concept_ids or []) if c in context.concepts]
            if not concept_ids:
                concept_ids = self._concepts_for_unit(context, unit)
            if not concept_ids:
                # Without a concept there is nothing to assess and no vocabulary to
                # retrieve with; skip rather than inventing an association.
                continue

            prompt_text, citations = self._real_text_for_item(
                context, item, unit, chunks_by_block
            )
            if not prompt_text:
                # The exercise's blocks have no retrievable text (e.g. a figure-only
                # exercise). Skip it instead of writing "See detailed solution in text".
                continue

            item_obj = QuestionBankItem(
                question_id=f"src_{item_id}",
                chapter_id=chapter_id,
                topic_ids=self._topic_ids_for_unit(context, unit, concept_ids),
                concept_ids=concept_ids,
                skill_ids=[link.skill_id for link in item.skill_links if link.skill_id in context.skills],
                question_type=QuestionType.SHORT_ANSWER,
                question_text=prompt_text,
                correct_answer=citations[0].quote if citations else prompt_text,
                explanation=(
                    f"Ask the learner to work through the passage below "
                    f"(page {citations[0].page})."
                    if citations
                    else ""
                ),
                allow_dont_know_option=False,
                source_type=QuestionSourceType.SOURCE,
                source_item_id=item_id,
                evidence_refs=[c.block_id for c in citations],
                source_citations=citations,
                validation_status=QuestionValidationStatus.VALID,
            )
            bank.add_question(item_obj)

    def _real_text_for_item(
        self,
        context: LearningContext,
        item,
        unit,
        chunks_by_block: Dict[str, SourceChunk],
    ) -> tuple[str, List[SourceCitation]]:
        """Resolve an assessable item to the real text of the blocks it points at."""
        block_ids: List[str] = []
        for ref in getattr(unit, "source", []) or []:
            if ref.block_id and ref.block_id not in block_ids:
                block_ids.append(ref.block_id)
        for evidence_id in item.evidence_ids or []:
            evidence = context.evidence.get(evidence_id)
            if evidence and evidence.block_id not in block_ids:
                block_ids.append(evidence.block_id)

        citations: List[SourceCitation] = []
        texts: List[str] = []
        for block_id in block_ids:
            chunk = chunks_by_block.get(block_id)
            if chunk is not None:
                citation = SourceCitation(**chunk.citation())
                texts.append(chunk.text)
            else:
                # Fall back to the EKR evidence excerpt for this block.
                excerpt = next(
                    (
                        ev.excerpt
                        for ev in context.evidence.values()
                        if ev.block_id == block_id and ev.excerpt
                    ),
                    "",
                )
                if not excerpt:
                    continue
                concept = next(
                    (c for c in context.concepts.values() if block_id in c.block_ids), None
                )
                citation = SourceCitation(
                    document_id=context.document_id,
                    page=(concept.page_indices[0] + 1) if concept and concept.page_indices else 1,
                    block_id=block_id,
                    section=concept.section_titles[0] if concept and concept.section_titles else None,
                    evidence_ids=[ev.evidence_id for ev in context.evidence.values() if ev.block_id == block_id],
                    quote=excerpt,
                )
                texts.append(excerpt)
            citations.append(citation)

        if not texts:
            return "", []

        prompt = " ".join(texts).strip()
        if len(prompt) > 1200:
            prompt = prompt[:1199].rstrip() + "…"
        return prompt, citations

    # -- step 2: generation from retrieved passages ------------------------

    def _generate_for_concepts(
        self,
        context: LearningContext,
        bank: QuestionBank,
        chapter_id: str,
        target_count: int,
        retriever: EvidenceRetriever,
        shortfalls: List[str],
    ) -> None:
        rounds = 0
        # Fingerprints already in the bank, so a model that repeats itself across
        # rounds cannot fill the bank with copies of the same question.
        seen = {QuestionBankDeduplicator.compute_fingerprint(q.question_text) for q in bank.questions.values()}

        for concept_id in shortfalls:
            if rounds >= _MAX_GENERATION_ROUNDS:
                break
            concept = context.concepts.get(concept_id)
            if concept is None:
                continue

            try:
                chunks = retriever.retrieve_for_concept(
                    concept_id,
                    concept_name=concept.canonical_name,
                    top_k=_PASSAGES_PER_REQUEST,
                )
            except RetrievalError as exc:
                # A concept with no retrievable passage is reported, never papered over.
                logger.warning(
                    "Skipping question generation for concept %s: %s", concept_id, exc.message
                )
                continue

            generated = self._generate_for_concept(context, concept_id, chunks, chapter_id)
            rounds += 1
            for item in generated:
                fingerprint = QuestionBankDeduplicator.compute_fingerprint(item.question_text)
                if fingerprint in seen:
                    logger.info(
                        "Dropped duplicate question for concept %s: %r",
                        concept_id,
                        item.question_text[:60],
                    )
                    continue
                seen.add(fingerprint)
                bank.add_question(item)

    def _generate_for_concept(
        self,
        context: LearningContext,
        concept_id: str,
        chunks: Sequence[SourceChunk],
        chapter_id: str,
    ) -> List[QuestionBankItem]:
        concept = context.concepts[concept_id]
        evidence_block = EvidenceRetriever.format_evidence_for_prompt(chunks)
        ref_labels = {f"E{i}": chunk for i, chunk in enumerate(chunks, start=1)}

        prompt = (
            f"Below are passages taken from the learner's own material.\n"
            f"{evidence_block}\n\n"
            f"Write 4 multiple-choice questions about the concept "
            f"\"{concept.canonical_name}\" that are answerable using ONLY the passages above.\n"
            f"RULES:\n"
            f"1. Every question must be answerable from the passages. Do not use outside "
            f"knowledge and do not invent facts, examples or formulas that are absent.\n"
            f"2. Give exactly 4 options. Exactly one is correct. The other 3 must be "
            f"plausible mistakes a learner studying THIS material might make.\n"
            f"3. Use the terminology and notation that appear in the passages.\n"
            f"4. Cite the labels of the passages each question relies on, e.g. [\"E1\"].\n"
            f"5. The explanation must quote or paraphrase the cited passage, not add new claims.\n"
            f"6. Difficulty is 0.0-1.0 (0.5 = typical)."
        )

        template = {
            "questions": [
                {
                    "question_text": "string",
                    "options": ["string", "string", "string", "string"],
                    "correct_answer": "string (must exactly equal one of the options)",
                    "explanation": "string",
                    "evidence_refs": ["string (e.g. 'E1')"],
                    "concept_id": "string",
                    "difficulty": 0.5,
                }
            ]
        }

        response = self.llm_adapter.generate_json(prompt, template)
        self._llm_calls += 1

        accepted: List[QuestionBankItem] = []
        for raw in response.get("questions", []) or []:
            item = self._item_from_response(
                context, concept_id, raw, ref_labels, chapter_id
            )
            if item is None:
                continue
            is_valid, reasons = QuestionBankValidator.validate_item(item, context)
            if is_valid:
                item.validation_status = QuestionValidationStatus.VALID
                accepted.append(item)
            else:
                logger.info(
                    "Discarded ungrounded question %r for concept %s: %s",
                    item.question_text[:60],
                    concept_id,
                    "; ".join(reasons),
                )
        return accepted

    def _item_from_response(
        self,
        context: LearningContext,
        concept_id: str,
        raw: dict,
        ref_labels: Dict[str, SourceChunk],
        chapter_id: str,
    ) -> Optional[QuestionBankItem]:
        """
        Convert one LLM response into an item, resolving its evidence refs.

        Returns ``None`` when the model omitted the question text entirely, so the
        caller never stores a placeholder question.
        """
        question_text = str(raw.get("question_text") or "").strip()
        if not question_text:
            return None

        options = [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()]
        correct_answer = str(raw.get("correct_answer") or "").strip()
        explanation = str(raw.get("explanation") or "").strip()

        # Resolve the cited evidence labels to real locations.
        citations: List[SourceCitation] = []
        refs: List[str] = []
        for ref in raw.get("evidence_refs", []) or []:
            key = str(ref).strip().upper().lstrip("[]")
            chunk = ref_labels.get(key)
            if chunk is None:
                continue
            refs.append(key)
            citation = SourceCitation(**chunk.citation())
            if citation.block_id not in {c.block_id for c in citations}:
                citations.append(citation)

        # A model that cites nothing cannot be trusted to have used the passages.
        if not citations:
            logger.info(
                "Discarded question with no resolvable evidence citation: %r", question_text[:60]
            )
            return None

        # Only keep concepts that actually exist in this document.
        claimed = str(raw.get("concept_id") or "").strip() or concept_id
        resolved_concept = claimed if claimed in context.concepts else concept_id

        try:
            difficulty = max(0.0, min(1.0, float(raw.get("difficulty", 0.5))))
        except (TypeError, ValueError):
            difficulty = 0.5

        question_type = QuestionType.MCQ
        if len(options) < 2:
            question_type = QuestionType.SHORT_ANSWER

        return QuestionBankItem(
            chapter_id=chapter_id,
            topic_ids=self._topic_ids_for_concept(context, resolved_concept),
            concept_ids=[resolved_concept],
            question_type=question_type,
            question_text=question_text,
            options=options or None,
            correct_answer=correct_answer,
            explanation=explanation,
            difficulty=difficulty,
            allow_dont_know_option=True,
            source_type=QuestionSourceType.GENERATED,
            evidence_refs=refs,
            source_citations=citations,
            validation_status=QuestionValidationStatus.PENDING,
        )

    # -- helpers ------------------------------------------------------------

    def _concept_coverage(self, bank: QuestionBank) -> Dict[str, int]:
        coverage: Dict[str, int] = {}
        for item in bank.get_grounded_questions():
            for concept_id in item.concept_ids:
                coverage[concept_id] = coverage.get(concept_id, 0) + 1
        return coverage

    def _concepts_needing_questions(
        self,
        context: LearningContext,
        coverage: Dict[str, int],
        target_count: int,
    ) -> List[str]:
        if not context.concepts:
            return []
        per_concept = max(1, min(4, target_count // max(1, len(context.concepts))))
        return [
            concept_id
            for concept_id in context.concepts
            if coverage.get(concept_id, 0) < per_concept
        ]

    def _topic_ids_for_concept(self, context: LearningContext, concept_id: str) -> List[str]:
        """Topic that really contains this concept. Empty when the document has no topics."""
        for topic in context.topics or []:
            if concept_id in (topic.get("concept_ids") or []):
                return [topic["topic_id"]]
        return []

    def _topic_ids_for_unit(
        self, context: LearningContext, unit, concept_ids: Sequence[str]
    ) -> List[str]:
        topic_ids: List[str] = []
        for topic in context.topics or []:
            if set(topic.get("concept_ids") or []) & set(concept_ids):
                topic_ids.append(topic["topic_id"])
        if topic_ids:
            return topic_ids
        section_id = getattr(unit, "section_id", None)
        if section_id:
            return [section_id]
        return []

    def _concepts_for_unit(self, context: LearningContext, unit) -> List[str]:
        concept_ids: List[str] = []
        for link in getattr(unit, "concept_links", []) or []:
            if link.concept_id in context.concepts and link.concept_id not in concept_ids:
                concept_ids.append(link.concept_id)
        return concept_ids
