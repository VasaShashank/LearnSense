"""
Unit tests for Phase 4 Knowledge Initialization and Diagnostic including 'I don't know' options.
"""

from phase3.learner.kt import KnowledgeTracer
from phase3.question_bank.models import QuestionBank, QuestionBankItem
from phase4.knowledge_initialization.concept_self_assessment import ConceptSelfAssessmentHandler
from phase4.knowledge_initialization.diagnostic_orchestrator import DiagnosticOrchestrator
from phase4.knowledge_initialization.knowledge_sufficiency import KnowledgeSufficiencyChecker
from phase4.models import SelfAssessmentStatus, KnowledgeSufficiencyStatus


def test_concept_self_assessment_partitioning():
    handler = ConceptSelfAssessmentHandler()
    all_concepts = ["c1", "c2", "c3", "c4"]
    selections = {
        "c1": SelfAssessmentStatus.KNOW,
        "c2": SelfAssessmentStatus.DONT_KNOW,
    }
    session = handler.create_session("learner_1", "subj_1", selections, all_concepts)

    assert session.know_concept_ids == ["c1"]
    assert session.dont_know_concept_ids == ["c2"]
    assert set(session.unanswered_concept_ids) == {"c3", "c4"}
    assert session.sufficiency_status == KnowledgeSufficiencyStatus.UNINITIALIZED


def test_diagnostic_orchestrator_know_concepts_only():
    bank = QuestionBank(
        document_id="doc1",
        chapter_id="ch1",
        questions={
            "q1": QuestionBankItem(
                question_id="q1",
                concept_ids=["c1"],
                question_text="q1 text",
                options=["A", "B", "C", "D"],
                correct_answer="A",
            ),
            "q2": QuestionBankItem(
                question_id="q2",
                concept_ids=["c2"],
                question_text="q2 text",
                options=["A", "B", "C", "D"],
                correct_answer="B",
            ),
        }
    )
    handler = ConceptSelfAssessmentHandler()
    all_concepts = ["c1", "c2"]
    selections = {"c1": SelfAssessmentStatus.KNOW, "c2": SelfAssessmentStatus.DONT_KNOW}
    session = handler.create_session("learner_1", "subj_1", selections, all_concepts)

    orchestrator = DiagnosticOrchestrator()
    questions = orchestrator.create_diagnostic_quiz(session, bank)

    # Diagnostic MUST only include q1 assessing KNOW concept c1
    assert len(questions) == 1
    assert questions[0].question_id == "q1"
    # Verify 'I don't know' option was appended to options
    assert "I don't know" in questions[0].options


def test_diagnostic_zero_know_concepts_bypasses_diagnostic():
    bank = QuestionBank(
        document_id="doc1",
        chapter_id="ch1",
        questions={
            "q1": QuestionBankItem(question_id="q1", concept_ids=["c1"], question_text="q1 text", correct_answer="A"),
        }
    )
    handler = ConceptSelfAssessmentHandler()
    all_concepts = ["c1", "c2"]
    selections = {"c1": SelfAssessmentStatus.DONT_KNOW, "c2": SelfAssessmentStatus.DONT_KNOW}
    session = handler.create_session("learner_1", "subj_1", selections, all_concepts)

    orchestrator = DiagnosticOrchestrator()
    questions = orchestrator.create_diagnostic_quiz(session, bank)

    assert questions == []
    assert session.diagnostic_completed is True


def test_diagnostic_response_updates_kt():
    tracer = KnowledgeTracer()
    learner_state = tracer.initialize_learner("learner_1", ["c1", "c2"])

    bank = QuestionBank(
        document_id="doc1",
        chapter_id="ch1",
        questions={
            "q1": QuestionBankItem(question_id="q1", concept_ids=["c1"], question_text="q1 text", correct_answer="A"),
        }
    )
    handler = ConceptSelfAssessmentHandler()
    session = handler.create_session("learner_1", "subj_1", {"c1": SelfAssessmentStatus.KNOW}, ["c1", "c2"])

    orchestrator = DiagnosticOrchestrator(tracer=tracer)
    updates = orchestrator.submit_diagnostic_responses(session, learner_state, {"q1": 1.0}, bank)

    assert "c1" in updates
    assert updates["c1"] > 0.3  # Initial mastery was 0.3, post-correct update should be higher
    assert session.diagnostic_completed is True
    assert session.sufficiency_status == KnowledgeSufficiencyStatus.INITIALIZED


def test_diagnostic_dont_know_response_evaluated_as_zero_correctness():
    tracer = KnowledgeTracer()
    learner_state = tracer.initialize_learner("learner_1", ["c1"])

    bank = QuestionBank(
        document_id="doc1",
        chapter_id="ch1",
        questions={
            "q1": QuestionBankItem(question_id="q1", concept_ids=["c1"], question_text="q1 text", correct_answer="A"),
        }
    )
    handler = ConceptSelfAssessmentHandler()
    session = handler.create_session("learner_1", "subj_1", {"c1": SelfAssessmentStatus.KNOW}, ["c1"])

    orchestrator = DiagnosticOrchestrator(tracer=tracer)
    # Responding with 0.0 correctness for 'I don't know' option
    updates = orchestrator.submit_diagnostic_responses(session, learner_state, {"q1": 0.0}, bank)

    assert "c1" in updates
    assert updates["c1"] < 0.3  # Incorrect / don't know response decreases mastery estimate
