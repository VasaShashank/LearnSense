"""
Dynamic Topic Mini-Quiz Generator for Phase 3.
Generates 5-8 questions targeted specifically at the learner's current Knowledge Tracing state.
"""

from typing import List, Optional
from phase3.adapters.llm_adapter import Phase3LLMAdapter
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

        target_concept_ids = [c[0] for c in concept_masteries[:3]] if concept_masteries else list(context.concepts.keys())[:1]
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
            f"2. For MCQ questions, provide 4 distinct, plausible options directly discussing the concept. Exactly ONE must be correct.\n"
            f"3. NEVER use generic placeholder phrases like 'Correct Option' or 'Distractor'. All options must be domain-grounded."
        )

        template = {
            "questions": [
                {
                    "question_text": "string (concrete question testing specific concept)",
                    "options": [
                        "string (option A)",
                        "string (option B)",
                        "string (option C)",
                        "string (option D)"
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

        quiz_questions: List[QuizQuestion] = []
        for i, raw_q in enumerate(raw_questions[:target_count]):
            c_ids = [target_concept_ids[i % len(target_concept_ids)]] if target_concept_ids else []
            q_type_str = raw_q.get("question_type", "mcq")
            try:
                q_type = QuestionType(q_type_str)
            except ValueError:
                q_type = QuestionType.MCQ

            q = QuizQuestion(
                question_type=q_type,
                question_text=raw_q.get("question_text", f"Question {i+1}"),
                options=raw_q.get("options") if q_type == QuestionType.MCQ else None,
                correct_answer=raw_q.get("correct_answer", "Correct Option"),
                explanation=raw_q.get("explanation", ""),
                concept_ids=c_ids,
                skill_ids=[],
                difficulty=raw_q.get("difficulty", 0.5),
                provenance="KT_GENERATED",
            )
            quiz_questions.append(q)

        return DynamicMiniQuiz(
            learner_id=learner_id,
            topic_id=topic_id,
            questions=quiz_questions,
            target_question_count=len(quiz_questions),
        )
