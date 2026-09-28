"""
Dynamic Topic Mini-Quiz Generator for Phase 3.
Generates 5-8 questions targeted specifically at the learner's current Knowledge Tracing state.
"""

from typing import List, Optional
from phase3.adapters.llm_adapter import Phase3LLMAdapter
from phase3.errors import LLMOutputError
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.models import LearnerState
from phase3.quiz.models import DynamicMiniQuiz, QuizQuestion
from phase3.question_bank.models import QuestionType


class DynamicMiniQuizGenerator:
    """Generates 5-8 question KT-aware dynamic mini quizzes for a topic."""

    def __init__(self, llm_adapter: Optional[Phase3LLMAdapter] = None):
        self.llm_adapter = llm_adapter or Phase3LLMAdapter()

    def generate_quiz(
        self,
        learner_id: str,
        topic_id: str,
        context: LearningContext,
        learner_state: LearnerState,
        target_count: int = 6,
    ) -> DynamicMiniQuiz:
        # 1. Identify concepts in topic and sort by lowest mastery (KT-aware targeting)
        topic_dict = next((t for t in context.topics if t["topic_id"] == topic_id), None)
        topic_concept_ids = topic_dict.get("concept_ids", []) if topic_dict else list(context.concepts.keys())

        # Focus heavily on low-mastery concepts
        concept_masteries = [
            (c_id, learner_state.get_concept_state(c_id).mastery_probability)
            for c_id in topic_concept_ids
        ]
        concept_masteries.sort(key=lambda x: x[1])  # Ascending order (lowest mastery first)

        target_concept_ids = (
            [c[0] for c in concept_masteries[:3]] if concept_masteries else list(context.concepts.keys())[:1]
        )
        concept_names = [
            context.concepts[c_id].canonical_name
            for c_id in target_concept_ids
            if c_id in context.concepts
        ]

        # 2. Call LLM with KT-aware context prompt
        prompt = (
            f"Generate {target_count} authentic educational diagnostic questions for topic '{topic_id}' "
            f"specifically testing these low-mastery concepts: {', '.join(concept_names)}.\n"
            f"RULES:\n"
            f"1. For each question, directly test a concrete property or operation of one of the concepts.\n"
            f"2. For MCQ questions, provide 4 distinct, plausible options directly discussing the concept. "
            f"Exactly ONE must be correct.\n"
            f"3. NEVER use generic placeholder phrases like 'Correct Option' or 'Distractor'. "
            f"All options must be domain-grounded."
        )

        template = {
            "questions": [
                {
                    "question_text": "string (concrete question testing specific concept)",
                    "options": [
                        "string (option A)",
                        "string (option B)",
                        "string (option C)",
                        "string (option D)",
                    ],
                    "correct_answer": "string (exact match of correct option)",
                    "explanation": "string (detailed explanation)",
                    "question_type": "mcq",
                    "difficulty": 0.5,
                }
            ]
        }

        response = self.llm_adapter.generate_json(prompt, template)
        raw_questions = response.get("questions", [])
        if not isinstance(raw_questions, list):
            raise LLMOutputError(
                "Expected the model to return a 'questions' array.",
                details={"got_type": type(raw_questions).__name__},
            )

        quiz_questions: List[QuizQuestion] = []
        for i, raw_q in enumerate(raw_questions[:target_count]):
            if not isinstance(raw_q, dict):
                continue
            c_ids = [target_concept_ids[i % len(target_concept_ids)]] if target_concept_ids else []
            try:
                q_type = QuestionType(str(raw_q.get("question_type", "mcq")).strip().lower())
            except ValueError:
                q_type = QuestionType.MCQ

            question_text = str(raw_q.get("question_text") or "").strip()
            if not question_text:
                continue

            options = _coerce_options(raw_q.get("options")) if q_type == QuestionType.MCQ else None
            if q_type == QuestionType.MCQ:
                if not options or len(options) < 2:
                    raise LLMOutputError(
                        "Model returned an MCQ without usable options.",
                        details={"question_index": i, "options": raw_q.get("options")},
                    )
                if len(set(options)) != len(options):
                    raise LLMOutputError(
                        "Model returned duplicate MCQ options, which makes the item unanswerable.",
                        details={"question_index": i, "options": options},
                    )

            correct_answer = str(raw_q.get("correct_answer") or "").strip()
            if not correct_answer:
                raise LLMOutputError(
                    "Model returned a question without a correct_answer.",
                    details={"question_index": i},
                )
            if options and correct_answer not in options:
                # Accept a case/whitespace variant of a listed option, otherwise fail loudly
                # rather than shipping an item whose answer key matches nothing.
                match = next((o for o in options if o.strip().lower() == correct_answer.lower()), None)
                if match is None:
                    raise LLMOutputError(
                        "correct_answer does not match any of the provided options.",
                        details={
                            "question_index": i,
                            "correct_answer": correct_answer,
                            "options": options,
                        },
                    )
                correct_answer = match

            quiz_questions.append(
                QuizQuestion(
                    question_type=q_type,
                    question_text=question_text,
                    options=options,
                    correct_answer=correct_answer,
                    explanation=str(raw_q.get("explanation") or "").strip(),
                    concept_ids=c_ids,
                    skill_ids=[],
                    difficulty=_coerce_difficulty(raw_q.get("difficulty")),
                    provenance="KT_GENERATED",
                )
            )

        if not quiz_questions:
            raise LLMOutputError(
                "The model produced no usable questions for this topic.",
                details={"returned": len(raw_questions), "topic_id": topic_id},
            )

        return DynamicMiniQuiz(
            learner_id=learner_id,
            topic_id=topic_id,
            questions=quiz_questions,
            target_question_count=len(quiz_questions),
        )


def _coerce_options(raw: object) -> Optional[List[str]]:
    """
    Normalise LLM options into a list of distinct, non-empty strings.

    Models frequently return ``[["a","b"],["c","d"]]`` or ``["a", null, ""]``; flattening
    here keeps a partially malformed response usable instead of crashing on Pydantic.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return None

    out: List[str] = []
    for item in raw:
        if isinstance(item, (list, tuple)):
            out.extend(str(x).strip() for x in item if str(x).strip())
        elif item is not None and str(item).strip():
            out.append(str(item).strip())
    return out


def _coerce_difficulty(raw: object) -> float:
    """Clamp any LLM-provided difficulty into the model's valid range."""
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, value))
