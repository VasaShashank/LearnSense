"""
Question Bank Builder for Phase 3.
Seeds questions from Phase 2 AssessableItems (SOURCE), calls LLM for course-grounded questions (GENERATED),
and generates variants (VARIANT). Validates and deduplicates before persisting.
"""

from typing import List, Optional
from phase3.adapters.llm_adapter import Phase3LLMAdapter
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.question_bank.models import (
    QuestionBank,
    QuestionBankItem,
    QuestionSourceType,
    QuestionType,
    QuestionValidationStatus,
)
from phase3.question_bank.validator import QuestionBankDeduplicator, QuestionBankValidator


class QuestionBankBuilder:
    def __init__(self, llm_adapter: Optional[Phase3LLMAdapter] = None):
        self.llm_adapter = llm_adapter or Phase3LLMAdapter()

    def build_bank_for_chapter(self, context: LearningContext, chapter_id: str = "ch_1", target_count: int = 25) -> QuestionBank:
        bank = QuestionBank(document_id=context.document_id, chapter_id=chapter_id)
        candidates: List[QuestionBankItem] = []

        # 1. Seed from Phase 2 AssessableItems (SOURCE)
        for item_id, item in context.assessable_items.items():
            unit = context.educational_units.get(item.unit_id)
            excerpt = f"Assessable Exercise for {item.unit_id}"
            if unit and unit.source:
                excerpt = f"Exercise in unit {unit.unit_id}"

            source_q = QuestionBankItem(
                question_id=f"src_{item.item_id}",
                chapter_id=chapter_id,
                topic_ids=[unit.section_id] if unit and unit.section_id else ["default_topic"],
                concept_ids=item.concept_ids or list(context.concepts.keys())[:2],
                skill_ids=[sl.skill_id for sl in item.skill_links],
                question_type=QuestionType.SHORT_ANSWER,
                question_text=f"Solve the problem: {excerpt}",
                correct_answer="See detailed solution in text.",
                explanation="Extracted directly from learning material.",
                source_type=QuestionSourceType.SOURCE,
                source_item_id=item.item_id,
                validation_status=QuestionValidationStatus.VALID,
            )
            candidates.append(source_q)

        # 2. LLM Generation grounded in EKR context (GENERATED)
        num_topics = max(1, len(context.topics))
        per_topic_gen = max(5, target_count // num_topics)

        for topic in context.topics:
            topic_concepts = topic.get("concept_ids", [])
            concept_names = [
                context.concepts[c_id].canonical_name
                for c_id in topic_concepts
                if c_id in context.concepts
            ]
            if not concept_names:
                concept_names = [c.canonical_name for c in list(context.concepts.values())[:2]] or ["General Topic Principles"]

            prompt = (
                f"Generate {per_topic_gen} educational multiple-choice questions for topic '{topic['topic_id']}' "
                f"grounded ONLY in concepts: {', '.join(concept_names)}. Return JSON format."
            )

            template = {
                "questions": [
                    {
                        "question_text": f"Which statement best describes {concept_names[i % len(concept_names)]} (Question {i+1})?",
                        "options": [
                            f"Core principle of {concept_names[i % len(concept_names)]}",
                            "Unrelated concept definition",
                            "Incorrect application",
                            "Opposite theorem statement"
                        ],
                        "correct_answer": f"Core principle of {concept_names[i % len(concept_names)]}",
                        "explanation": f"Grounded in course concepts for {topic['topic_id']}.",
                        "question_type": "mcq",
                        "difficulty": min(0.9, 0.3 + (i * 0.03))
                    }
                    for i in range(per_topic_gen)
                ]
            }

            response = self.llm_adapter.generate_json(prompt, template)
            raw_qs = response.get("questions", [])
            for raw_q in raw_qs:
                diff = float(raw_q.get("difficulty", 0.5))
                diff = max(0.0, min(1.0, diff))
                gen_q = QuestionBankItem(
                    chapter_id=chapter_id,
                    topic_ids=[topic["topic_id"]],
                    concept_ids=topic_concepts or list(context.concepts.keys())[:1],
                    skill_ids=[],
                    question_type=QuestionType(raw_q.get("question_type", "mcq")),
                    question_text=raw_q.get("question_text", "Generated Question"),
                    options=raw_q.get("options", []),
                    correct_answer=raw_q.get("correct_answer", ""),
                    explanation=raw_q.get("explanation", ""),
                    difficulty=diff,
                    source_type=QuestionSourceType.GENERATED,
                    validation_status=QuestionValidationStatus.VALID,
                )
                candidates.append(gen_q)

        # 3. Generate Variants for source and generated questions (VARIANT)
        for candidate in list(candidates):
            if len(candidates) >= target_count * 2:
                break
            var_q = QuestionBankItem(
                chapter_id=chapter_id,
                topic_ids=candidate.topic_ids,
                concept_ids=candidate.concept_ids,
                skill_ids=candidate.skill_ids,
                question_type=candidate.question_type,
                question_text=f"Variation of ({candidate.question_id}): {candidate.question_text}",
                options=candidate.options,
                correct_answer=candidate.correct_answer,
                explanation=f"Variant of question {candidate.question_id}",
                source_type=QuestionSourceType.VARIANT,
                source_item_id=candidate.question_id,
                validation_status=QuestionValidationStatus.VALID,
            )
            candidates.append(var_q)

        # 4. Validate & Deduplicate
        valid_items = []
        for cand in candidates:
            is_valid, _ = QuestionBankValidator.validate_item(cand, context)
            if is_valid:
                cand.validation_status = QuestionValidationStatus.VALID
                valid_items.append(cand)

        unique_items = QuestionBankDeduplicator.deduplicate(valid_items)

        for item in unique_items:
            bank.add_question(item)

        return bank
