import urllib.request
import json
import time

teacher_headers = {
    'Authorization': 'Bearer demo-token-vance',
    'Content-Type': 'application/json'
}
admin_headers = {
    'Authorization': 'Bearer demo-token-sterling',
    'Content-Type': 'application/json'
}

# 1. Test GET /classes
print("=== 1. TESTING GET /classes ===")
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/classes", headers=teacher_headers)
    with urllib.request.urlopen(req) as resp:
        classes = json.loads(resp.read().decode())
        print(f"Total classes found: {len(classes)}")
        if classes:
            print("Class 0:", classes[0].get("class_id"), "|", classes[0].get("class_name") or classes[0].get("title"))
            first_cls_id = classes[0]["class_id"]
        else:
            first_cls_id = None
except Exception as e:
    print("GET /classes error:", e)
    first_cls_id = None

# If no class exists, create one for testing
if not first_cls_id:
    print("Registering demo test class...")
    reg_data = json.dumps({
        "subject_id": "jee_physics",
        "class_name": "JEE Advanced Physics Cohort Alpha",
        "enrolled_learner_ids": [
            "c0000000-0000-0000-0000-000000000001",
            "c0000000-0000-0000-0000-000000000003"
        ]
    }).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:8000/api/classes", data=reg_data, headers=teacher_headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        first_cls_id = res.get("class_id")
        print("Created test class:", first_cls_id)

# 2. Test GET /classes/{class_id}/knowledge-state
print(f"\n=== 2. TESTING GET /classes/{first_cls_id}/knowledge-state ===")
try:
    req = urllib.request.Request(f"http://127.0.0.1:8000/api/classes/{first_cls_id}/knowledge-state", headers=teacher_headers)
    with urllib.request.urlopen(req) as resp:
        ks = json.loads(resp.read().decode())
        print("Knowledge State loaded successfully!")
        print("Subject title:", ks.get("subject_title"))
        print("Total enrolled:", ks.get("total_enrolled"))
        print("Active learners:", ks.get("active_learners"))
        print("Overall cohort readiness:", ks.get("overall_class_readiness"))
        print("Concepts tracked:", len(ks.get("concept_distributions", {})))
except Exception as e:
    print("Knowledge state error:", e)

# 3. Test GET /classes/{class_id}/student-learning-insights
print(f"\n=== 3. TESTING GET /classes/{first_cls_id}/student-learning-insights ===")
try:
    req = urllib.request.Request(f"http://127.0.0.1:8000/api/classes/{first_cls_id}/student-learning-insights", headers=teacher_headers)
    with urllib.request.urlopen(req) as resp:
        insights = json.loads(resp.read().decode())
        print(f"Total concept insights generated: {len(insights)}")
        if insights:
            i0 = insights[0]
            print("Sample Insight:", i0.get("concept_name"), "| Difficulty:", i0.get("difficulty_tier"), "| Avg Accuracy:", i0.get("avg_first_try_accuracy"))
            print("Teaching Recommendations:", i0.get("teaching_recommendations"))
except Exception as e:
    print("Learning insights error:", e)

# 4. Test GET /classes/{class_id}/student-mastery
print(f"\n=== 4. TESTING GET /classes/{first_cls_id}/student-mastery ===")
try:
    req = urllib.request.Request(f"http://127.0.0.1:8000/api/classes/{first_cls_id}/student-mastery", headers=teacher_headers)
    with urllib.request.urlopen(req) as resp:
        masteries = json.loads(resp.read().decode())
        print(f"Students with individual mastery vectors: {len(masteries)}")
        if masteries:
            m0 = masteries[0]
            print("Sample Student:", m0.get("name"), f"({m0.get('learner_id')})", "| Mean Mastery:", m0.get("average_mastery"), "| Tier:", m0.get("assigned_tier"))
            print("Weakest Concept:", m0.get("weakest_concept"))
except Exception as e:
    print("Student mastery error:", e)

# 5. Test POST /classes/{class_id}/teaching-optimizer/plan
print(f"\n=== 5. TESTING TEACHING OPTIMIZER: /classes/{first_cls_id}/teaching-optimizer/plan ===")
try:
    plan_data = json.dumps({
        "duration_minutes": 45
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:8000/api/classes/{first_cls_id}/teaching-optimizer/plan", data=plan_data, headers=teacher_headers)
    with urllib.request.urlopen(req) as resp:
        plan = json.loads(resp.read().decode())
        print("Teaching Plan Generated successfully!")
        print("Plan ID:", plan.get("intervention_id"))
        print("Target Concept:", plan.get("target_concept_name") or plan.get("target_concept_id"))
        print("Duration:", plan.get("total_class_duration_minutes"), "min")
        actions = plan.get("actions", [])
        print("Instructional Actions:", len(actions))
        for a in actions:
            print(f"  - [{a.get('action_type')}] {a.get('target_concept_name')} ({a.get('allocated_time_minutes')} min)")
        interv_id = plan.get("intervention_id")
except Exception as e:
    print("Teaching optimizer error:", e)
    interv_id = None

# 6. Test POST /classes/{class_id}/interventions/{intervention_id}/approve
if interv_id:
    print(f"\n=== 6. TESTING PLAN APPROVAL: /classes/{first_cls_id}/interventions/{interv_id}/approve ===")
    try:
        appr_data = json.dumps({
            "notes": "Approved for delivery in Friday Physics double block."
        }).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:8000/api/classes/{first_cls_id}/interventions/{interv_id}/approve", data=appr_data, headers=teacher_headers)
        with urllib.request.urlopen(req) as resp:
            appr = json.loads(resp.read().decode())
            print("Plan Approved Status:", appr.get("status"))
    except Exception as e:
        print("Plan approval error:", e)

# 7. Test Institutional Organizations and Classes
print("\n=== 7. TESTING INSTITUTION PORTAL: /institutions/organizations & /institutions/classes ===")
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/institutions/organizations", headers=admin_headers)
    with urllib.request.urlopen(req) as resp:
        orgs = json.loads(resp.read().decode())
        print(f"Total organizations found: {len(orgs)}")
        for org in orgs[:2]:
            print(f"  Org: {org.get('name')} ({org.get('org_id')})")
        org_id = orgs[0]["org_id"] if orgs else None
except Exception as e:
    print("Organizations error:", e)
    org_id = None

if org_id:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:8000/api/institutions/classes?org_id={org_id}", headers=admin_headers)
        with urllib.request.urlopen(req) as resp:
            inst_classes = json.loads(resp.read().decode())
            print(f"Institution classes in {org_id}: {len(inst_classes)}")
            if inst_classes:
                sample_cid = inst_classes[0]["class_id"]
                # Test roster
                r_req = urllib.request.Request(f"http://127.0.0.1:8000/api/institutions/classes/{sample_cid}/roster", headers=admin_headers)
                with urllib.request.urlopen(r_req) as r_resp:
                    roster = json.loads(r_resp.read().decode())
                    enrolled_list = roster.get('roster', [])
                    print(f"Roster for {sample_cid}: {len(enrolled_list)} students enrolled: {enrolled_list}")
    except Exception as e:
        print("Institution classes error:", e)
