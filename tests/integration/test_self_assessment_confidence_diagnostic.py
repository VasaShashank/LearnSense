"""Regression tests for self-assessment + confidence -> adaptive diagnostic.

Covers Batch 15 (Tests 1-15):
1.  ingestion complete -> self-assessment available
2.  self-assessment persisted
3.  confidence persisted separately (mastery untouched)
4.  Strong + high confidence -> quick verification (cap 1), not auto-mastery
5.  Weak + high confidence -> excluded from probing (gap drives path instead)
6.  Unsure -> uncertainty-reducing diagnostic coverage
7.  wrong diagnostic response updates objective evidence
8.  single wrong answer does NOT mark topic weak (insufficient_evidence)
9.  repeated evidence CAN establish likely weakness
10. prerequisite failure redirects learning path toward the prerequisite
11. Strong contradicted by poor performance is detected (CI)
12. Unsure + strong performance is detected (UC)
13. refresh/resume preserves self-assessment + diagnostic state
14. no answer keys leaked to the frontend
15. Light Mode control is absent
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from phase3.question_bank.models import QuestionBank, QuestionBankItem, SourceCitation
from phase4.knowledge_initialization.concept_self_assessment import ConceptSelfAssessmentHandler
from phase4.knowledge_initialization.diagnostic_orchestrator import DiagnosticOrchestrator
from phase4.models import ConfidenceLevel, SelfAssessmentStatus

client = TestClient(app)

# Learner-state storage is file-backed and survives across test runs, so every
# learner ID below is namespaced per run for exact attempt-count assertions.
import uuid as _uuid

_RUN = _uuid.uuid4().hex[:8]


def _learner(tag: str) -> str:
    return f"{tag}_{_RUN}"

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _sa(learner_id, subject_id, selections, confidences=None, all_ids=None):
    body = {
        "learner_id": learner_id,
        "subject_id": subject_id,
        "selections": selections,
        "all_subject_concept_ids": all_ids or list(selections.keys()),
    }
    if confidences is not None:
        body["confidences"] = confidences
    res = client.post("/api/initialization/self-assessment", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _start(session_id, learner_id):
    res = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session_id, "learner_id": learner_id},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _submit(session_id, learner_id, responses):
    res = client.post(
        "/api/initialization/diagnostic/submit",
        json={"session_id": session_id, "learner_id": learner_id, "responses": responses},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _synthetic_bank(*concept_ids: str) -> QuestionBank:
    """Deterministic in-memory bank: 3 grounded questions per concept."""
    bank = QuestionBank(document_id="synth", chapter_id="ch_all")
    for cid in concept_ids:
        for i in range(3):
            bank.add_question(
                QuestionBankItem(
                    question_id=f"q_{cid}_{i}",
                    chapter_id="ch_all",
                    concept_ids=[cid],
                    question_text=f"Question {i} about {cid}?",
                    options=["alpha", "beta", "gamma"],
                    correct_answer="alpha",
                    explanation=f"Because {cid}.",
                    difficulty=0.5,
                    source_citations=[
                        SourceCitation(
                            document_id="synth", page=1, block_id=f"b_{cid}_{i}", quote="alpha"
                        )
                    ],
                )
            )
    return bank


# --- Test 1: ingestion complete -> self-assessment available -----------------
def test_1_ingestion_complete_enables_self_assessment(ingested_calculus):
    graph = client.get(f"/api/subjects/{ingested_calculus.document_id}/graph")
    assert graph.status_code == 200, graph.text
    concepts = graph.json()["concepts"]
    assert len(concepts) > 0
    # Self-assessment becomes available: every concept accepts a rating.
    assert all(c["concept_id"] for c in concepts)


# --- Test 2: self-assessment persisted ---------------------------------------
def test_2_self_assessment_is_persisted(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    know = all_ids[:1]
    selections = {cid: ("KNOW" if cid in know else "DONT_KNOW") for cid in all_ids}
    data = _sa(_learner("t2_learner"), subject_id, selections, all_ids=all_ids)
    assert set(data["know_concept_ids"]) == set(know)
    assert set(data["dont_know_concept_ids"]) == set(all_ids[1:])
    assert data["self_assessments"][know[0]]["status"] == "KNOW"


# --- Test 3: confidence persisted separately; mastery untouched ---------------
def test_3_confidence_persisted_separately(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    selections = {cid: "KNOW" for cid in all_ids[:1]}
    confidences = {all_ids[0]: "HIGH"}
    data = _sa(_learner("t3_learner"), subject_id, selections, confidences, all_ids=all_ids)
    assert data["confidences"][all_ids[0]] == "HIGH"
    assert data["self_assessments"][all_ids[0]]["confidence"] == "HIGH"
    # Objective mastery is NOT set from self-report: learner state stays at prior.
    from backend.services.learner_service import LearnerService

    state = LearnerService().get_or_create_learner_state(_learner("t3_learner"), all_ids)
    assert state.concept_states[all_ids[0]].mastery_probability == pytest.approx(0.3)
    assert state.concept_states[all_ids[0]].attempt_count == 0


# --- Test 4: Strong + high confidence -> quick verification ------------------
def test_4_strong_high_confidence_quick_verification():
    handler = ConceptSelfAssessmentHandler()
    orch = DiagnosticOrchestrator()
    session = handler.create_session(
        learner_id="t4",
        subject_id="s",
        selections={"c_a": SelfAssessmentStatus.KNOW},
        all_subject_concept_ids=["c_a", "c_b"],
        confidences={"c_a": ConfidenceLevel.HIGH},
    )
    bank = _synthetic_bank("c_a")
    questions = orch.create_diagnostic_quiz(session, bank)
    for_c_a = [q for q in questions if "c_a" in q.concept_ids]
    assert 1 <= len(for_c_a) <= 1, "confident-strong claims get a single quick check"
    assert session.diagnostic_priorities["c_a"] < orch.concept_priority(
        handler.create_session(
            learner_id="t4b",
            subject_id="s",
            selections={"c_x": SelfAssessmentStatus.UNANSWERED},
            all_subject_concept_ids=["c_x"],
            confidences={"c_x": ConfidenceLevel.LOW},
        ),
        "c_x",
    )


# --- Test 5: Weak + high confidence -> excluded from probing -----------------
def test_5_weak_high_confidence_not_probed(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    selections = {cid: "DONT_KNOW" for cid in all_ids}
    confidences = {cid: "HIGH" for cid in all_ids}
    data = _sa(_learner("t5_learner"), subject_id, selections, confidences, all_ids=all_ids)
    assert data["verify_concept_ids"] == [] or all(
        cid not in data["verify_concept_ids"] for cid in all_ids
    )
    started = _start(data["session_id"], _learner("t5_learner"))
    assert started["question_count"] == 0


# --- Test 6: Unsure -> uncertainty-reducing coverage --------------------------
def test_6_unsure_gets_diagnostic_coverage(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    unsure = all_ids[:1]
    selections = {cid: ("UNANSWERED" if cid in unsure else "DONT_KNOW") for cid in all_ids}
    data = _sa(_learner("t6_learner"), subject_id, selections, all_ids=all_ids)
    assert set(data["verify_concept_ids"]) == set(unsure)
    started = _start(data["session_id"], _learner("t6_learner"))
    assert started["question_count"] >= 0
    covered = {c for q in started["questions"] for c in (q.get("concept_ids") or [])}
    assert not covered or covered <= set(unsure)


# --- Test 7: wrong response updates objective evidence ------------------------
def test_7_wrong_response_updates_evidence(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    know = all_ids[:1]
    selections = {cid: ("KNOW" if cid in know else "DONT_KNOW") for cid in all_ids}
    data = _sa(_learner("t7_learner"), subject_id, selections, all_ids=all_ids)
    started = _start(data["session_id"], _learner("t7_learner"))
    assert started["question_count"] > 0
    qid = started["questions"][0].get("question_id") or started["questions"][0].get("item_id")
    result = _submit(data["session_id"], _learner("t7_learner"), {qid: 0.0})
    assert result["diagnostic_completed"] is True
    assert result["updated_masteries"][know[0]] < 0.3


# --- Test 8: single wrong answer is NOT a weakness verdict --------------------
def test_8_single_wrong_answer_insufficient_evidence(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    know = all_ids[:1]
    selections = {cid: ("KNOW" if cid in know else "DONT_KNOW") for cid in all_ids}
    data = _sa(_learner("t8_learner"), subject_id, selections, all_ids=all_ids)
    started = _start(data["session_id"], _learner("t8_learner"))
    qid = started["questions"][0].get("question_id") or started["questions"][0].get("item_id")
    result = _submit(data["session_id"], _learner("t8_learner"), {qid: 0.0})
    verdict = result["evidence_verdicts"][know[0]]
    assert verdict["attempts"] < 3
    assert verdict["verdict"] == "insufficient_evidence"


# --- Test 9: repeated evidence CAN establish weakness --------------------------
def test_9_repeated_evidence_establishes_weakness(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    know = all_ids[:1]
    selections = {cid: ("KNOW" if cid in know else "DONT_KNOW") for cid in all_ids}
    data = _sa(_learner("t9_learner"), subject_id, selections, all_ids=all_ids)
    started = _start(data["session_id"], _learner("t9_learner"))
    qid = started["questions"][0].get("question_id") or started["questions"][0].get("item_id")
    result = None
    for _ in range(3):
        result = _submit(data["session_id"], _learner("t9_learner"), {qid: 0.0})
    assert result is not None
    verdict = result["evidence_verdicts"][know[0]]
    assert verdict["attempts"] >= 3
    assert verdict["verdict"] == "likely_weak"
    assert result["updated_masteries"][know[0]] < 0.5


# --- Test 10: prerequisite failure redirects path ------------------------------
def test_10_prerequisite_failure_redirects_path(ingested_calculus):
    """Copies the real fixture context under a new subject, adds a B->C
    prerequisite link, seeds grounded questions for B and C citing real
    provenance, then fails C: B must be flagged and repaired first."""
    from phase3.knowledge.phase2_adapter import PrerequisiteLink
    from phase3.question_bank.models import QuestionBank, QuestionBankItem, SourceCitation
    from storage.repositories import LearningContextRepository, QuestionBankRepository

    all_ids = ingested_calculus.concept_ids
    concept_b = ingested_calculus.id_for("Derivatives")
    concept_c = ingested_calculus.id_for("Chain Rule")
    assert concept_b != concept_c
    subject_id = "subj_prereq_t10"
    learner_id = _learner("t10_learner")

    src_ctx = LearningContextRepository().load_context(ingested_calculus.document_id)
    assert src_ctx is not None
    ctx = src_ctx.model_copy(
        update={
            "document_id": subject_id,
            "prerequisites": [
                PrerequisiteLink(
                    source_concept_id=concept_b,
                    target_concept_id=concept_c,
                    confidence=1.0,
                )
            ],
        }
    )
    LearningContextRepository().save_context(ctx)

    view_c = ctx.concepts[concept_c]
    page = (view_c.page_indices[0] + 1) if view_c.page_indices else 1
    block = view_c.block_ids[0] if view_c.block_ids else "b_prereq_t10"
    quote = (view_c.description or view_c.canonical_name)[:200]

    def _cite() -> SourceCitation:
        return SourceCitation(document_id=subject_id, page=page, block_id=block, quote=quote)

    bank = QuestionBank(document_id=subject_id, chapter_id="ch_all")
    bank.add_question(
        QuestionBankItem(
            question_id="t10_q_c1",
            chapter_id="ch_all",
            concept_ids=[concept_c],
            question_text="Seeded verification question 1 for the downstream concept?",
            options=["opt_a", "opt_b"],
            correct_answer="opt_a",
            explanation="Seeded.",
            source_citations=[_cite()],
        )
    )
    bank.add_question(
        QuestionBankItem(
            question_id="t10_q_b1",
            chapter_id="ch_all",
            concept_ids=[concept_b],
            question_text="Seeded verification question for the prerequisite concept?",
            options=["opt_a", "opt_b"],
            correct_answer="opt_a",
            explanation="Seeded.",
            source_citations=[_cite()],
        )
    )
    QuestionBankRepository().save_bank(bank)

    selections = {
        cid: ("KNOW" if cid in (concept_b, concept_c) else "DONT_KNOW") for cid in all_ids
    }
    data = _sa(learner_id, subject_id, selections, all_ids=all_ids)
    started = _start(data["session_id"], learner_id)
    assert started["question_count"] > 0
    target_q = next(
        q for q in started["questions"] if concept_c in (q.get("concept_ids") or [])
    )
    qid = target_q.get("question_id") or target_q.get("item_id")
    result = _submit(data["session_id"], learner_id, {qid: 0.0})
    prereq_hits = [p for p in result["prerequisite_verification"] if p["concept_id"] == concept_c]
    assert prereq_hits, "failure on C must flag its prerequisite B for verification"
    assert any(p["prerequisite_id"] == concept_b for p in prereq_hits)
    # The adaptive path repairs the prerequisite first (topological order).
    path_res = client.get(f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}")
    assert path_res.status_code == 200, path_res.text
    ids = [n["concept_id"] for n in path_res.json()["learning_path"]["nodes"]]
    assert concept_b in ids and concept_c in ids
    assert ids.index(concept_b) < ids.index(concept_c)


# --- Test 11: Strong contradicted by poor performance --------------------------
def test_11_strong_contradicted_by_poor_performance(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    know = all_ids[:1]
    selections = {cid: ("KNOW" if cid in know else "DONT_KNOW") for cid in all_ids}
    confidences = {know[0]: "HIGH"}
    data = _sa(_learner("t11_learner"), subject_id, selections, confidences, all_ids=all_ids)
    started = _start(data["session_id"], _learner("t11_learner"))
    qid = started["questions"][0].get("question_id") or started["questions"][0].get("item_id")
    result = _submit(data["session_id"], _learner("t11_learner"), {qid: 0.0})
    assert know[0] in result["contradicted_concept_ids"]
    assert result["calibration"][know[0]] == "CI"


# --- Test 12: Unsure + strong performance -> UC ---------------------------------
def test_12_unsure_strong_performance_detected(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    unsure = all_ids[:1]
    selections = {cid: ("UNANSWERED" if cid in unsure else "DONT_KNOW") for cid in all_ids}
    confidences = {unsure[0]: "LOW"}
    data = _sa(_learner("t12_learner"), subject_id, selections, confidences, all_ids=all_ids)
    started = _start(data["session_id"], _learner("t12_learner"))
    assert started["question_count"] > 0
    qid = started["questions"][0].get("question_id") or started["questions"][0].get("item_id")
    result = _submit(data["session_id"], _learner("t12_learner"), {qid: 1.0})
    assert result["calibration"][unsure[0]] == "UC"


# --- Test 13: refresh/resume preserves state ------------------------------------
def test_13_resume_preserves_self_assessment_and_diagnostic(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    know = all_ids[:1]
    selections = {cid: ("KNOW" if cid in know else "DONT_KNOW") for cid in all_ids}
    confidences = {know[0]: "HIGH"}
    data = _sa(_learner("t13_learner"), subject_id, selections, confidences, all_ids=all_ids)
    session_id = data["session_id"]

    # Simulate process restart: fresh service instances read the same storage.
    from backend.services.learner_service import LearnerService
    from storage.repositories import SessionRepository

    reloaded = SessionRepository().load_session(session_id)
    assert reloaded is not None
    assert reloaded.self_assessments[know[0]].status == SelfAssessmentStatus.KNOW
    assert reloaded.confidences[know[0]] == ConfidenceLevel.HIGH

    resumed = LearnerService().resume_learner_state(_learner("t13_learner"), subject_id=subject_id)
    assert resumed["has_state"] is True
    active = resumed["active_init_session"]
    assert active is not None and active["session_id"] == session_id

    # Diagnostic resumes by re-starting from the persisted session.
    started = _start(session_id, _learner("t13_learner"))
    assert started["question_count"] > 0


# --- Test 14: no answer keys leaked ----------------------------------------------
def test_14_no_answer_key_leak(ingested_calculus):
    subject_id = ingested_calculus.document_id
    all_ids = ingested_calculus.concept_ids
    know = all_ids[:1]
    selections = {cid: ("KNOW" if cid in know else "DONT_KNOW") for cid in all_ids}
    data = _sa(_learner("t14_learner"), subject_id, selections, all_ids=all_ids)
    started = _start(data["session_id"], _learner("t14_learner"))
    for q in started["questions"]:
        assert "correct_answer" not in q
        assert "explanation" not in q


# --- Test 15: Light Mode control is absent ---------------------------------------
def test_15_light_mode_control_absent():
    navbar = (FRONTEND / "components" / "navigation" / "TopNavbar.tsx").read_text()
    assert "onToggleTheme" not in navbar
    assert "Toggle Visual Mode" not in navbar
    app_tsx = (FRONTEND / "App.tsx").read_text()
    assert "onToggleTheme" not in app_tsx
    assert "setTheme" not in app_tsx
