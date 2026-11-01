"""
Unit and regression tests for Knowledge Graph Visualization,
Academic Concept Grounding, Cycle-Safe DAG Synthesis, and Learning Path Connectivity.

Verifies:
1. Academic soundness of the 14 Mechanics concepts (Newton's Laws, Friction, Centripetal Motion).
2. Directed Acyclic Graph (DAG) guarantees (zero pedagogical cycles).
3. Cross-chapter edge preservation across Newton's Laws -> Friction -> Centripetal Motion.
4. Complete connectivity (zero floating / orphaned concepts).
5. Multi-subject generalization (all ingested documents produce cycle-safe DAGs).
6. Learning path sequential progression integrity starting from foundational concepts.
"""

from __future__ import annotations

import pytest
from typing import Dict, List, Set

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService


LAWS_OF_MOTION_DOC_ID = (
    "doc_121418-jee-main-2023-24-laws-of-motion-revision-notes-free-pdf-download"
)


def _build_adj_and_in_degrees(concepts: List[Dict]) -> tuple[Dict[str, Set[str]], Dict[str, int]]:
    cid_set = {c["concept_id"] for c in concepts}
    adj: Dict[str, Set[str]] = {cid: set() for cid in cid_set}
    in_degree: Dict[str, int] = {cid: 0 for cid in cid_set}

    for c in concepts:
        tgt = c["concept_id"]
        for p in c.get("prerequisites", []):
            if p in cid_set:
                adj[p].add(tgt)
                in_degree[tgt] += 1

    return adj, in_degree


def _topological_sort(concepts: List[Dict]) -> List[str]:
    adj, in_degree = _build_adj_and_in_degrees(concepts)
    queue = [cid for cid, deg in in_degree.items() if deg == 0]
    visited = []

    while queue:
        curr = queue.pop(0)
        visited.append(curr)
        for nxt in adj[curr]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    return visited


class TestKnowledgeGraphVisualization:
    @pytest.fixture(autouse=True)
    def setup_services(self):
        self.ks = KnowledgeService()
        self.ls = LearnerService(knowledge_service=self.ks)

    def test_laws_of_motion_graph_acyclic(self):
        """Graph must be a strict DAG without circular prerequisite dependencies."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        concepts = graph["concepts"]
        assert len(concepts) == 14, f"Expected 14 canonical concepts, found {len(concepts)}"

        topological_order = _topological_sort(concepts)
        assert len(topological_order) == len(concepts), (
            f"Prerequisite cycle detected! Visited {len(topological_order)} of {len(concepts)} concepts. "
            f"Unresolved concepts: {set(c['concept_id'] for c in concepts) - set(topological_order)}"
        )

    def test_laws_of_motion_all_concepts_connected(self):
        """No concept node should appear disconnected / orphaned when it is part of the curriculum."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        concepts = graph["concepts"]
        adj, in_degree = _build_adj_and_in_degrees(concepts)

        for c in concepts:
            cid = c["concept_id"]
            name = c["name"]
            in_d = in_degree[cid]
            out_d = len(adj[cid])
            total_edges = in_d + out_d
            assert total_edges > 0, f"Concept '{name}' ({cid}) is completely disconnected (0 edges)!"

    def test_laws_of_motion_cross_chapter_connectivity(self):
        """Verify cross-chapter prerequisite links connecting mechanics topics."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        concepts = graph["concepts"]
        name_to_concept = {c["name"].lower().strip(): c for c in concepts}

        # Topic 1 (Newton's Laws) -> Topic 2 (Friction)
        second_law = name_to_concept.get("newton's second law")
        static_friction = name_to_concept.get("static friction")
        assert second_law is not None, "Missing Newton's Second Law"
        assert static_friction is not None, "Missing Static Friction"
        assert second_law["concept_id"] in static_friction["prerequisites"], (
            "Newton's Second Law must be a prerequisite for Static Friction across chapters"
        )

        # Topic 1 (Newton's Laws) -> Topic 3 (Centripetal Motion)
        centripetal_accel = name_to_concept.get("centripetal acceleration")
        assert centripetal_accel is not None, "Missing Centripetal Acceleration"
        assert second_law["concept_id"] in centripetal_accel["prerequisites"], (
            "Newton's Second Law must be a prerequisite for Centripetal Acceleration across chapters"
        )

        # Topic 2 (Friction) -> Topic 3 (Centripetal Motion)
        assert static_friction["concept_id"] in centripetal_accel["prerequisites"], (
            "Static Friction must be a prerequisite for Centripetal Acceleration across chapters"
        )

    def test_laws_of_motion_pedagogical_ordering(self):
        """Verify academic progression within each chapter."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        concepts = graph["concepts"]
        name_to_concept = {c["name"].lower().strip(): c for c in concepts}

        first_law = name_to_concept["newton's first law"]
        net_force = name_to_concept["net force"]
        second_law = name_to_concept["newton's second law"]
        third_law = name_to_concept["newton's third law"]

        # Topic 1: Newton's Laws
        assert first_law["concept_id"] in net_force["prerequisites"]
        assert net_force["concept_id"] in second_law["prerequisites"]
        assert second_law["concept_id"] in third_law["prerequisites"]

        # Topic 2: Friction
        static_friction = name_to_concept["static friction"]
        kinetic_friction = name_to_concept["kinetic friction"]
        coeff_static = name_to_concept["coefficient of static friction"]
        coeff_kinetic = name_to_concept["coefficient of kinetic friction"]
        assert static_friction["concept_id"] in kinetic_friction["prerequisites"]
        assert static_friction["concept_id"] in coeff_static["prerequisites"]
        assert kinetic_friction["concept_id"] in coeff_kinetic["prerequisites"]

        # Topic 3: Centripetal Motion
        angular_vel = name_to_concept["angular velocity"]
        centripetal_acc = name_to_concept["centripetal acceleration"]
        tangential_acc = name_to_concept["tangential acceleration"]
        net_acc = name_to_concept["net acceleration in circular motion"]
        assert angular_vel["concept_id"] in centripetal_acc["prerequisites"]
        assert angular_vel["concept_id"] in tangential_acc["prerequisites"]
        assert centripetal_acc["concept_id"] in net_acc["prerequisites"]
        assert tangential_acc["concept_id"] in net_acc["prerequisites"]

    def test_all_persisted_subjects_acyclic(self):
        """Verify that all stored educational documents generate cycle-safe DAGs."""
        subjects = self.ks.list_subjects()
        assert len(subjects) > 0, "No subjects found in storage"

        cyclic_subjects = []
        for s in subjects:
            s_id = s["id"]
            try:
                g = self.ks.get_subject_graph(s_id)
                concepts = g["concepts"]
                if not concepts:
                    continue
                topo = _topological_sort(concepts)
                if len(topo) < len(concepts):
                    cyclic_subjects.append(s_id)
            except Exception as e:
                pytest.fail(f"Failed to generate graph for {s_id}: {e}")

        assert not cyclic_subjects, f"Found cycles in subjects: {cyclic_subjects}"

    def test_learning_path_progression_integrity(self):
        """Verify that get_gaps_and_path outputs a cycle-safe learning path starting with roots."""
        res = self.ls.get_gaps_and_path("test_learner", LAWS_OF_MOTION_DOC_ID)
        assert res is not None
        assert "learning_path" in res
        nodes = res["learning_path"]["nodes"]
        assert len(nodes) > 0

        # Foundational concepts like Newton's First Law or Angular Velocity must appear early
        first_few_names = [n["name"].lower().strip() for n in nodes[:3]]
        assert any("first law" in name or "angular velocity" in name for name in first_few_names), (
            f"Expected foundational concepts at start of learning path, got: {first_few_names}"
        )
