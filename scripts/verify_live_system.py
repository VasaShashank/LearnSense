import urllib.request
import json
import time

headers = {'Authorization': 'Bearer demo-token-alex'}

# 1. Test question retrieval for cc_0a599e2579d7239e
q_req = urllib.request.Request('http://127.0.0.1:8000/api/subjects/jee_physics/concepts/cc_0a599e2579d7239e/question?offset=0', headers=headers)
with urllib.request.urlopen(q_req) as resp:
    q_data = json.loads(resp.read().decode())
    print('=== 1. QUESTION TEST ===')
    print('Question ID:', q_data.get('question_id'))
    print('Question Text:', q_data.get('question_text'))
    print('Options:', q_data.get('options'))
    assert 'JQ51' not in q_data.get('question_text', ''), 'Error: JQ found in question!'
    assert 'cc_0a' not in q_data.get('question_text', ''), 'Error: raw cc_ hash found in question!'
    print('SUCCESS: Clean authentic question verified!')

# 2. Test Marketplace Peers
m_req = urllib.request.Request('http://127.0.0.1:8000/api/marketplace/peers?subject_id=jee_physics', headers=headers)
with urllib.request.urlopen(m_req) as resp:
    m_data = json.loads(resp.read().decode())
    print('=== 2. MARKETPLACE TEST ===')
    print('Total peers found:', len(m_data))
    for p in m_data:
        print(f"Peer: {p.get('name')} | Specialty: {p.get('specialty')} | Match: {int(p.get('match_score', 0)*100)}% | Strengths: {p.get('strengths')}")
    assert len(m_data) > 0, 'No peers returned!'
    print('SUCCESS: Real peer marketplace verified!')

# 3. Test Activity Response and BKT update
act_data = json.dumps({
    'learner_id': 'c0000000-0000-0000-0000-000000000001',
    'subject_id': 'jee_physics',
    'concept_ids': ['cc_0a599e2579d7239e'],
    'question_id': q_data.get('question_id'),
    'selected_option': q_data.get('options')[0],
    'request_id': f'req_live_{int(time.time()*1000)}'
}).encode('utf-8')
act_req = urllib.request.Request('http://127.0.0.1:8000/api/learners/activity-response', data=act_data, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer demo-token-alex'})
with urllib.request.urlopen(act_req) as resp:
    act_res = json.loads(resp.read().decode())
    print('=== 3. BKT ACTIVITY TEST ===')
    print('Correctness:', act_res.get('correctness'))
    print('Concept Masteries updated:', act_res.get('updated_masteries'))
    assert act_res.get('updated_masteries'), 'No updated masteries returned!'
    print('SUCCESS: Real-time BKT mastery update verified!')
