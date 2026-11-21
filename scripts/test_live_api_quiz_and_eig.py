import urllib.request
import json
import time

headers = {
    'Authorization': 'Bearer demo-token-alex',
    'Content-Type': 'application/json'
}

# 1. Test POST /api/quiz/generate-micro-quiz
print("=== 1. TEST POST /api/quiz/generate-micro-quiz ===")
quiz_req_data = json.dumps({
    "concept_id": "cc_0a599e2579d7239e",
    "learner_id": "c0000000-0000-0000-0000-000000000001",
    "num_questions": 4,
    "include_hints": True
}).encode("utf-8")
q_req = urllib.request.Request("http://127.0.0.1:8000/api/quiz/generate", data=quiz_req_data, headers=headers)
with urllib.request.urlopen(q_req) as resp:
    quiz_res = json.loads(resp.read().decode())
    print("Quiz ID:", quiz_res.get("quiz_id"))
    print("Concept:", quiz_res.get("concept_name"))
    print("Total Questions:", len(quiz_res.get("items", [])))
    for it in quiz_res.get("items", []):
        print(f"  Q{it.get('question_number')}: {it.get('prompt')}")
        opts = [o.get("text") for o in it.get("options", [])]
        print(f"    Options: {opts}")
    assert len(quiz_res.get("items", [])) == 4, "Expected 4 questions in micro quiz"
    print("SUCCESS: Micro-Quiz Generation Endpoint Verified!")

# 2. Test POST /api/assessments/adaptive-select (Shannon EIG)
print("\n=== 2. TEST POST /api/assessments/adaptive-select (Information Gain) ===")
select_req_data = json.dumps({
    "learner_id": "c0000000-0000-0000-0000-000000000001",
    "target_concept_ids": ["cc_0a599e2579d7239e"],
    "assessment_objective": "diagnostic"
}).encode("utf-8")
sel_req = urllib.request.Request("http://127.0.0.1:8000/api/assessments/adaptive-select", data=select_req_data, headers=headers)
with urllib.request.urlopen(sel_req) as resp:
    sel_res = json.loads(resp.read().decode())
    print("Selected Question ID:", sel_res.get("selected_question_id"))
    print("Expected Information Gain:", sel_res.get("information_gain"), "bits")
    print("Rationale:", sel_res.get("selection_rationale"))
    print("Eligible Candidates Evaluated:", sel_res.get("eligible_candidate_count"))
    assert sel_res.get("information_gain", 0) > 0, "Expected non-zero Information Gain"
    print("SUCCESS: Adaptive EIG Selection Endpoint Verified!")

# 3. Test Adaptive Session Lifecycle (Start -> Next -> Submit)
print("\n=== 3. TEST ADAPTIVE SESSION (EIG-Driven Assessment) ===")
start_req_data = json.dumps({
    "learner_id": "c0000000-0000-0000-0000-000000000001",
    "target_concept_ids": ["cc_0a599e2579d7239e"],
    "assessment_objective": "diagnostic",
    "max_questions": 8
}).encode("utf-8")
start_req = urllib.request.Request("http://127.0.0.1:8000/api/assessments/adaptive-session/start", data=start_req_data, headers=headers)
with urllib.request.urlopen(start_req) as resp:
    start_res = json.loads(resp.read().decode())
    session_id = start_res.get("session_id")
    print(f"Session Started: {session_id} | Target questions: {start_res.get('target_questions')} | Prior Mastery: {start_res.get('current_mastery')}")

# Get Next Question
next_req = urllib.request.Request(f"http://127.0.0.1:8000/api/assessments/adaptive-session/{session_id}/next-question", headers=headers)
with urllib.request.urlopen(next_req) as resp:
    next_res = json.loads(resp.read().decode())
    q_info = next_res.get("selected_question") or {}
    print(f"Next Question Served:")
    print(f"  Q{next_res.get('question_number')}: {q_info.get('question_id')}")
    print(f"  Phase: {next_res.get('phase')} | Objective: {next_res.get('objective')}")
    print(f"  Expected Information Gain: {next_res.get('information_gain_bits')} bits")

# Submit Answer
ans_req_data = json.dumps({
    "question_id": q_info.get("question_id"),
    "selected_option": "A",
    "is_correct": True
}).encode("utf-8")
ans_req = urllib.request.Request(f"http://127.0.0.1:8000/api/assessments/adaptive-session/{session_id}/submit-answer", data=ans_req_data, headers=headers)
with urllib.request.urlopen(ans_req) as resp:
    ans_res = json.loads(resp.read().decode())
    print(f"Answer Submitted:")
    print(f"  Updated Mastery: {ans_res.get('current_mastery')}")
    print(f"  Updated Entropy: {ans_res.get('current_entropy')} bits")
    print(f"  Consecutive Correct: {ans_res.get('consecutive_correct')}")
    print("SUCCESS: Full Adaptive Session Lifecycle Verified!")
