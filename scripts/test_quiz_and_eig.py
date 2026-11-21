import os
import sys
sys.path.insert(0, os.path.abspath('.'))

import json
from src.service import LearnSensePersonalizationService

service = LearnSensePersonalizationService()

# 1. Test Micro-Quiz Generation
print("=== 1. TESTING MICRO-QUIZ GENERATION ===")
quiz = service.generate_micro_quiz(
    learner_id="c0000000-0000-0000-0000-000000000001",
    concept_id="cc_0a599e2579d7239e",
    num_questions=4
)
print("Quiz ID:", quiz.get("quiz_id"))
print("Concept:", quiz.get("concept_name"), f"({quiz.get('concept_id')})")
print("Item count:", len(quiz.get("items", [])))
for item in quiz.get("items", []):
    print(f"  Q{item.get('question_number')}: {item.get('prompt')}")
    for opt in item.get("options", []):
        print(f"    [{opt.get('option_id')}] {opt.get('text')} (Correct: {opt.get('is_correct')})")

# 2. Test Expected Information Gain Question Selection
print("\n=== 2. TESTING EXPECTED INFORMATION GAIN (EIG) SELECTION ===")
eig_result = service.select_adaptive_question(
    learner_id="c0000000-0000-0000-0000-000000000001",
    concept_id="cc_0a599e2579d7239e",
    objective="diagnostic"
)
sel_q = eig_result.get("selected_question") or {}
print("Selected Question ID:", sel_q.get("question_id"))
print("Selected Question Difficulty:", sel_q.get("difficulty"))
print("Expected Information Gain:", eig_result.get("information_gain"), "bits")
print("Selection Rationale:", eig_result.get("selection_rationale"))
print("Eligible Candidates Evaluated:", eig_result.get("eligible_candidate_count"))

# 3. Test Full Adaptive Assessment Session with 8 Questions
print("\n=== 3. TESTING ADAPTIVE SESSION ORCHESTRATION ===")
sess = service.start_adaptive_session(
    learner_id="c0000000-0000-0000-0000-000000000001",
    concept_id="cc_0a599e2579d7239e",
    target_questions=8
)
sess_id = sess["session_id"]
print("Started Session ID:", sess_id, "| Prior Mastery:", sess.get("current_mastery"))

# Step through questions to verify info gain at each step
for step in range(3):
    next_q = service.get_next_adaptive_session_question(sess_id)
    if next_q.get("is_completed"):
        print("Session completed early.")
        break
    q_data = next_q.get("selected_question") or {}
    print(f"Step {step+1}:")
    print(f"  Question: {q_data.get('question_id')} | Difficulty: {q_data.get('difficulty')}")
    print(f"  Phase: {next_q.get('phase')} | Objective: {next_q.get('objective')}")
    print(f"  Information Gain: {next_q.get('information_gain_bits')} bits")
    print(f"  Current Mastery: {next_q.get('current_mastery')}")
    # Submit answer
    sub_res = service.submit_adaptive_session_answer(
        session_id=sess_id,
        question_id=q_data.get("question_id"),
        is_correct=(step % 2 == 0),
    )
    print(f"  Posterior Mastery after response: {sub_res.get('current_mastery')} | Posterior Entropy: {sub_res.get('current_entropy')} bits")
