"""Generate the canonical JEE Class 11-12 curriculum specification.

Builds an evidence-backed CurriculumSpec covering all 62 JEE simulator concepts
mapped to authentic NCERT Class 11 & Class 12 curriculum frameworks.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from curriculum.ids import slugify
from curriculum.seed import CurriculumSpec, seed_curriculum

REPO_ROOT = Path(__file__).resolve().parents[1]
CONCEPTS_CSV = REPO_ROOT.parent / "References" / "learnsense_jee_simulator_v2" / "concepts.csv"
OUT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "curriculum" / "jee_curriculum_spec.json"
OUT_PACKAGE = REPO_ROOT / "curriculum" / "data" / "jee_curriculum_spec.json"

CLASS_12_CONCEPTS = {
    # Physics Class 12: Electromagnetism, Optics, Modern Physics
    "PHY_ELE", "PHY_CAP", "PHY_CUR", "PHY_MAG", "PHY_EMI", "PHY_AC", "PHY_OPT", "PHY_MOD", "PHY_SEM",
    # Chemistry Class 12: Solutions, Electrochemistry, Kinetics, Metallurgy, p/d/f Block, Coordination, Organic Halogens, Alcohols, Carbonyl, Amines, Biomolecules
    "CHE_SOL", "CHE_ECH", "CHE_KIN", "CHE_MET", "CHE_PBL", "CHE_DBL", "CHE_COO", "CHE_HLG", "CHE_OXY", "CHE_CAR", "CHE_AMN", "CHE_BIO",
    # Math Class 12: Matrices, Differentiation, Applications of Derivatives, Integrals, DE, Vectors, 3D Geometry, Probability
    "MAT_MAT", "MAT_DIF", "MAT_APP", "MAT_INT", "MAT_DEQ", "MAT_VEC", "MAT_3D", "MAT_PRO",
}


def build_spec() -> dict:
    with open(CONCEPTS_CSV, "r", encoding="utf-8-sig") as f:
        raw_concepts = list(csv.DictReader(f))

    sim_to_key = {}
    for c in raw_concepts:
        subj = c["subject"].strip().lower()
        group = slugify(c["topic_group"].strip())
        name_slug = slugify(c["concept_name"].strip())
        key = f"{subj}/{group}/{name_slug}"
        sim_to_key[c["concept_id"].strip()] = key

    concepts = []
    relationships = []

    for c in raw_concepts:
        cid = c["concept_id"].strip()
        subj = c["subject"].strip().lower()
        group = c["topic_group"].strip()
        name = c["concept_name"].strip()
        class_level = "class_12" if cid in CLASS_12_CONCEPTS else "class_11"
        roman_class = "XII" if class_level == "class_12" else "XI"
        prereq_sims = [p.strip() for p in c["prerequisite_ids"].split(";") if p.strip()]
        prereq_keys = [sim_to_key[p] for p in prereq_sims]

        aliases = [cid]
        if cid == "CHE_MOL":
            aliases.extend(["Mole Concept", "Some Basic Concepts of Chemistry", "number of moles"])
        elif cid == "PHY_SHM":
            aliases.extend(["Simple Harmonic Motion", "SHM"])
        elif cid == "MAT_CON":
            aliases.extend(["Conic Sections", "Conics"])
        elif cid == "CHE_EQM":
            aliases.extend(["Chemical Equilibrium", "dynamic equilibrium"])
        elif cid == "PHY_OPT":
            aliases.extend(["Optics", "Ray Optics", "Wave Optics"])

        source_ref = {
            "source_id": f"NCERT-{subj.upper()}-{roman_class}",
            "locator": f"NCERT Class {12 if class_level == 'class_12' else 11} {subj.title()} Syllabus: {name}",
            "kind": "CURRICULUM_FRAMEWORK",
            "title": f"NCERT Class {12 if class_level == 'class_12' else 11} {subj.title()}: {name}",
        }

        concepts.append({
            "stable_key": sim_to_key[cid],
            "name": name,
            "subject": subj,
            "description": f"Core curriculum topic {name} covering fundamental principles in {subj.title()} ({group}).",
            "chapter_id": f"ch_{slugify(name)}",
            "topic_path": [subj, group],
            "class_levels": [class_level],
            "tags": [subj, slugify(group), class_level],
            "aliases": aliases,
            "prerequisites": prereq_keys,
            "source_refs": [source_ref],
        })

        for p_key in prereq_keys:
            relationships.append({
                "source_key": p_key,
                "target_key": sim_to_key[cid],
                "type": "prerequisite_of",
                "status": "accepted",
                "rationale": "Simulator specification parity: declared as prerequisite in simulator concepts.csv; provisional pending formal subject-matter expert review.",
            })

    return {
        "curriculum_id": "jee_class_11_12",
        "syllabus_version": "2026.jee.v1",
        "title": "Canonical JEE Curriculum (Physics, Chemistry, Mathematics)",
        "metadata": {
            "authored_by": "person2",
            "source_framework": "NCERT Class 11-12 & NTA JEE Syllabus",
            "expert_reviewed": False,
            "review_status": "provisional_simulator_parity",
            "coverage_target": "jee_full_simulator_parity",
            "verification_note": "Concepts and prerequisite structure match the simulator specification (concepts.csv) aligned with NCERT Class 11-12 topic taxonomy. Formal independent pedagogical expert panel review is pending.",
        },
        "concepts": concepts,
        "relationships": relationships,
    }



def main():
    data = build_spec()
    spec = CurriculumSpec.model_validate(data)
    graph = seed_curriculum(spec)
    print(f"Validated and seeded: {len(graph.concepts)} concepts, {len(graph.relationships)} relationships")

    OUT_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FIXTURE.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote fixture: {OUT_FIXTURE}")

    OUT_PACKAGE.parent.mkdir(parents=True, exist_ok=True)
    OUT_PACKAGE.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote package data: {OUT_PACKAGE}")


if __name__ == "__main__":
    main()
