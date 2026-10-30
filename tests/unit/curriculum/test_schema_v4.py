"""
Unit tests for Schema v4 (SCHEMA.md v4.0.0) CSV serialization, topological depth, and validation.
"""

import pytest

from curriculum.graph import (
    PrerequisiteCycleError,
    derive_topological_depth,
)
from curriculum.models import (
    CanonicalConcept,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    ReviewStatus,
    Subject,
)
from curriculum.schema_v4 import (
    SCHEMA_V4_HEADERS,
    SchemaV4ValidationError,
    export_to_schema_v4_csv,
    import_from_schema_v4_csv,
)
from curriculum.seed import load_spec, seed_curriculum
from phase2.models import RelationshipStatusEnum, RelationshipTypeEnum


@pytest.fixture
def mini_dag_graph():
    r"""
    Creates a diamond DAG:
        A (root, depth 0)
       / \
      B   C (depth 1)
       \ /
        D (depth 2)
    """
    graph = CurriculumGraph(curriculum_id="mini_dag", syllabus_version="2026.jee.v1")

    for cid, name in [("c_a", "Concept A"), ("c_b", "Concept B"), ("c_c", "Concept C"), ("c_d", "Concept D")]:
        graph.add_concept(
            CanonicalConcept(
                concept_id=cid,
                name=name,
                subject=Subject.PHYSICS,
                chapter_id="ch_test",
                status=ConceptLifecycleStatus.ACTIVE,
                review_status=ReviewStatus.ACCEPTED,
                curriculum_id="mini_dag",
                curriculum_version="2026.jee.v1",
                stable_key=f"physics/test/{cid}",
            )
        )

    edges = [("c_a", "c_b"), ("c_a", "c_c"), ("c_b", "c_d"), ("c_c", "c_d")]
    for src, tgt in edges:
        graph.concepts[tgt].add_prerequisite(src)
        graph.add_relationship(
            ConceptRelationship.create(
                source=src,
                relationship_type=RelationshipTypeEnum.PREREQUISITE_OF,
                target=tgt,
                curriculum_id="mini_dag",
                status=RelationshipStatusEnum.ACCEPTED,
            )
        )

    return graph


def test_derive_topological_depth_diamond(mini_dag_graph):
    depths = derive_topological_depth(mini_dag_graph)
    assert depths["c_a"] == 0
    assert depths["c_b"] == 1
    assert depths["c_c"] == 1
    assert depths["c_d"] == 2


def test_derive_topological_depth_cycle_rejection():
    graph = CurriculumGraph(curriculum_id="cyclic", syllabus_version="2026.jee.v1")
    for cid in ["c_1", "c_2"]:
        graph.add_concept(
            CanonicalConcept(
                concept_id=cid,
                name=f"Concept {cid}",
                subject=Subject.MATHEMATICS,
                status=ConceptLifecycleStatus.ACTIVE,
                review_status=ReviewStatus.ACCEPTED,
                curriculum_id="cyclic",
                curriculum_version="2026.jee.v1",
                stable_key=f"math/test/{cid}",
            )
        )

    # 1 -> 2 and 2 -> 1
    graph.concepts["c_2"].add_prerequisite("c_1")
    graph.concepts["c_1"].add_prerequisite("c_2")
    graph.add_relationship(
        ConceptRelationship.create(
            source="c_1",
            relationship_type=RelationshipTypeEnum.PREREQUISITE_OF,
            target="c_2",
            curriculum_id="cyclic",
            status=RelationshipStatusEnum.ACCEPTED,
        )
    )
    graph.add_relationship(
        ConceptRelationship.create(
            source="c_2",
            relationship_type=RelationshipTypeEnum.PREREQUISITE_OF,
            target="c_1",
            curriculum_id="cyclic",
            status=RelationshipStatusEnum.ACCEPTED,
        )
    )

    with pytest.raises(PrerequisiteCycleError):
        derive_topological_depth(graph)


def test_schema_v4_round_trip(tmp_path, mini_dag_graph):
    csv_file = tmp_path / "test_concepts.csv"
    count = export_to_schema_v4_csv(mini_dag_graph, csv_file)
    assert count == 4

    # Verify headers in file
    lines = csv_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(SCHEMA_V4_HEADERS)

    # Re-import
    imported = import_from_schema_v4_csv(csv_file, curriculum_id="mini_dag")
    assert len(imported.concepts) == 4
    assert len(imported.relationships) == 4

    imported_depths = derive_topological_depth(imported)
    assert imported_depths == {"c_a": 0, "c_b": 1, "c_c": 1, "c_d": 2}


def test_schema_v4_validation_unknown_prereq(tmp_path):
    csv_file = tmp_path / "bad_prereq.csv"
    csv_content = (
        "concept_id,subject,concept_name,topic_group,prerequisite_ids,curriculum_status,topological_depth\n"
        "c_1,physics,Concept 1,Mechanics,unknown_id,active,1\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(SchemaV4ValidationError, match="references unknown prerequisite_id 'unknown_id'"):
        import_from_schema_v4_csv(csv_file)


def test_schema_v4_validation_self_loop(tmp_path):
    csv_file = tmp_path / "self_loop.csv"
    csv_content = (
        "concept_id,subject,concept_name,topic_group,prerequisite_ids,curriculum_status,topological_depth\n"
        "c_1,physics,Concept 1,Mechanics,c_1,active,0\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(SchemaV4ValidationError, match="cannot be its own prerequisite"):
        import_from_schema_v4_csv(csv_file)


def test_schema_v4_validation_duplicate_id(tmp_path):
    csv_file = tmp_path / "duplicate.csv"
    csv_content = (
        "concept_id,subject,concept_name,topic_group,prerequisite_ids,curriculum_status,topological_depth\n"
        "c_1,physics,Concept 1,Mechanics,,active,0\n"
        "c_1,physics,Concept 1 Dup,Mechanics,,active,0\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(SchemaV4ValidationError, match="duplicate concept_id 'c_1'"):
        import_from_schema_v4_csv(csv_file)


def test_schema_v4_validation_depth_mismatch(tmp_path):
    csv_file = tmp_path / "depth_mismatch.csv"
    csv_content = (
        "concept_id,subject,concept_name,topic_group,prerequisite_ids,curriculum_status,topological_depth\n"
        "c_1,physics,Concept 1,Mechanics,,active,5\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(SchemaV4ValidationError, match="Topological depth mismatch"):
        import_from_schema_v4_csv(csv_file)


def test_schema_v4_full_canonical_spec_round_trip(tmp_path):
    spec = load_spec("curriculum/data/jee_curriculum_spec.json")
    graph = seed_curriculum(spec)
    csv_file = tmp_path / "canonical_concepts.csv"

    exported_count = export_to_schema_v4_csv(graph, csv_file)
    assert exported_count == len(graph.concepts)

    imported_graph = import_from_schema_v4_csv(csv_file, curriculum_id=graph.curriculum_id)
    assert len(imported_graph.concepts) == len(graph.concepts)
    assert len(imported_graph.prerequisite_edges(include_unreviewed=False)) == len(
        graph.prerequisite_edges(include_unreviewed=False)
    )
