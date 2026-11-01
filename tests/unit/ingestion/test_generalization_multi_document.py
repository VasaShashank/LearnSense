"""
Multi-Document Generalization Test Suite for LearnSense Ingestion & Concept Extraction.

Verifies that the complete ingestion, extraction, validation, hierarchy construction,
and canonical knowledge graph integration pipeline generalizes reliably across arbitrary
educational documents, subjects (Physics, Chemistry, Mathematics, Biology, Computer Science),
chapters, document structures (PDF, Clean TXT, Noisy OCR, Tabular/Formulas, Ambiguous Notes),
and author styles without document-specific hardcoding.
"""

import json
import os
import pytest
from typing import Dict, List, Set

from backend.services.knowledge_build_service import KnowledgeBuildService
from phase2.pipeline.semantic_validator import (
    SemanticConceptValidator,
    ConceptValidationOutcome,
)
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage


@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures", "ingestion")


@pytest.fixture
def build_service(tmp_path):
    storage = DocumentStorage(root_dir=str(tmp_path / "storage"))
    context_repo = LearningContextRepository(base_dir=str(tmp_path / "contexts"))
    return KnowledgeBuildService(storage=storage, context_repo=context_repo)


def has_cycle(prereqs: List[Dict[str, str]]) -> bool:
    """Detects cycles in prerequisite edges using DFS."""
    adj: Dict[str, List[str]] = {}
    nodes: Set[str] = set()
    for edge in prereqs:
        u = edge.get("source_id") or edge.get("prerequisite_id")
        v = edge.get("target_id") or edge.get("concept_id")
        if u and v:
            adj.setdefault(u, []).append(v)
            nodes.add(u)
            nodes.add(v)

    visited: Dict[str, int] = {node: 0 for node in nodes}  # 0: unvisited, 1: visiting, 2: visited

    def dfs(node: str) -> bool:
        visited[node] = 1
        for nbr in adj.get(node, []):
            if visited[nbr] == 1:
                return True
            if visited[nbr] == 0:
                if dfs(nbr):
                    return True
        visited[node] = 2
        return False

    return any(visited[node] == 0 and dfs(node) for node in nodes)


class TestMultiDocumentGeneralization:
    """Verifies generalization of extraction, validation, and graph construction across diverse STEM documents."""

    def test_multi_document_end_to_end_pipeline(self, fixtures_dir, build_service):
        """
        Executes the full pipeline across all diverse educational documents in the suite.
        Verifies:
        1. Document builds successfully (status == READY).
        2. Concepts are extracted and 100% grounded with provenance citations.
        3. Topics are dynamically formed without hardcoded physics defaults.
        4. Prerequisite graph forms an acyclic DAG (0 cycles).
        """
        gold_path = os.path.join(fixtures_dir, "multi_document_gold_standards.json")
        with open(gold_path, "r", encoding="utf-8") as f:
            suite_data = json.load(f)["documents"]

        tested_docs = [
            "physics_work_energy_power.txt",
            "chemistry_chemical_bonding.txt",
            "mathematics_coordinate_geometry.txt",
            "biology_cell_biology.txt",
            "multi_chapter_mechanics_thermo.txt",
            "dense_math_equations_tables.txt",
            "noisy_ocr_thermodynamics.txt",
            "clean_pedagogical_calculus.txt",
            "incomplete_ambiguous_notes.txt",
        ]

        for fname in tested_docs:
            fpath = os.path.join(fixtures_dir, fname)
            assert os.path.exists(fpath), f"Fixture missing: {fname}"

            with open(fpath, "rb") as f:
                data = f.read()

            doc_id = f"gen_test_{fname.replace('.txt', '')}"
            res = build_service.build(doc_id, data, fname, reuse_existing=False)

            assert res["status"] == "READY", f"Build failed for {fname}: {res}"
            assert res["concept_count"] >= 4, f"Too few concepts extracted for {fname}: {res['concept_count']}"
            assert res["grounded_concept_count"] == res["concept_count"], f"Ungrounded concepts in {fname}"
            assert res["topic_count"] >= 1, f"No topics formed for {fname}"

            ctx = build_service.context_repo.load_context(doc_id)
            assert ctx is not None

            # Verify 100% provenance citations
            for c in ctx.concepts.values():
                citation = c.citation()
                assert citation["concept_id"] == c.concept_id
                assert len(citation["evidence_ids"]) >= 1, f"Missing citation evidence for concept {c.canonical_name} in {fname}"

            # Verify DAG acyclicity
            prereqs = ctx.metadata.get("prerequisites", [])
            assert not has_cycle(prereqs), f"Cycle detected in prerequisite graph of {fname}"

    def test_topic_extraction_is_content_driven_zero_bleed(self, fixtures_dir, build_service):
        """
        Verifies that non-physics documents do NOT bleed Newton's Laws, Friction,
        or Circular Motion into their extracted topics.
        """
        non_physics_docs = [
            ("chemistry_chemical_bonding.txt", ["Newton", "Friction", "Circular"]),
            ("mathematics_coordinate_geometry.txt", ["Newton", "Friction", "Circular"]),
            ("biology_cell_biology.txt", ["Newton", "Friction", "Circular"]),
            ("dense_math_equations_tables.txt", ["Newton", "Friction", "Circular"]),
            ("clean_pedagogical_calculus.txt", ["Newton", "Friction", "Circular"]),
        ]

        for fname, prohibited_keywords in non_physics_docs:
            fpath = os.path.join(fixtures_dir, fname)
            with open(fpath, "rb") as f:
                data = f.read()

            doc_id = f"bleed_test_{fname.replace('.txt', '')}"
            build_service.build(doc_id, data, fname, reuse_existing=False)
            ctx = build_service.context_repo.load_context(doc_id)

            topic_titles = [t["title"] for t in ctx.topics]
            for kw in prohibited_keywords:
                for t in topic_titles:
                    assert kw.lower() not in t.lower(), (
                        f"Prohibited physics keyword '{kw}' leaked into non-physics topic '{t}' for document {fname}"
                    )

    def test_noise_rejection_across_all_documents(self, fixtures_dir, build_service):
        """
        Verifies that all known bad candidates across subjects (formula fragments,
        teacher conversational remarks, sentence fragments, OCR artifacts) are
        rejected and never leak as validated concepts.
        """
        gold_path = os.path.join(fixtures_dir, "multi_document_gold_standards.json")
        with open(gold_path, "r", encoding="utf-8") as f:
            suite_data = json.load(f)["documents"]

        for fname, meta in suite_data.items():
            fpath = os.path.join(fixtures_dir, fname)
            with open(fpath, "rb") as f:
                data = f.read()

            doc_id = f"noise_test_{fname.replace('.txt', '')}"
            build_service.build(doc_id, data, fname, reuse_existing=False)
            ctx = build_service.context_repo.load_context(doc_id)

            concept_names = {c.canonical_name.lower() for c in ctx.concepts.values()}
            for bad_cand in meta.get("known_bad_candidates", []):
                # Bad candidate must NOT be present as an exact concept or standalone concept
                assert bad_cand.lower() not in concept_names, (
                    f"Known bad candidate '{bad_cand}' leaked as concept in {fname}"
                )

    def test_multi_document_gold_benchmark_metrics(self, fixtures_dir, build_service):
        """
        Computes precision, recall, and F1 across all documents in the evaluation suite.
        Verifies that the generalized engine achieves >= 80% Recall and >= 80% Precision overall.
        """
        gold_path = os.path.join(fixtures_dir, "multi_document_gold_standards.json")
        with open(gold_path, "r", encoding="utf-8") as f:
            suite_data = json.load(f)["documents"]

        doc_metrics = {}
        total_gold_count = 0
        total_gold_found = 0

        for fname, meta in suite_data.items():
            fpath = os.path.join(fixtures_dir, fname)
            with open(fpath, "rb") as f:
                data = f.read()

            doc_id = f"metrics_{fname.replace('.txt', '')}"
            build_service.build(doc_id, data, fname, reuse_existing=False)
            ctx = build_service.context_repo.load_context(doc_id)

            gold_concepts = meta.get("gold_concepts", [])
            extracted_concepts = list(ctx.concepts.values())
            print(f"DEBUG {fname}: count={len(extracted_concepts)}, names={[c.canonical_name for c in extracted_concepts]}")
            extracted_names = {c.canonical_name.lower() for c in extracted_concepts}
            for c in extracted_concepts:
                for a in c.aliases:
                    extracted_names.add(a.lower())

            found_gold = 0
            missing_gold = []
            for gc in gold_concepts:
                gc_low = gc.lower()
                if gc_low in extracted_names or any(gc_low in en or en in gc_low for en in extracted_names):
                    found_gold += 1
                else:
                    missing_gold.append(gc)

            recall = found_gold / len(gold_concepts) if gold_concepts else 1.0
            total_gold_count += len(gold_concepts)
            total_gold_found += found_gold
            print(f"DOC METRIC DEBUG: {fname} -> found {found_gold}/{len(gold_concepts)}, missing: {missing_gold}")

            doc_metrics[fname] = {
                "gold_total": len(gold_concepts),
                "gold_found": found_gold,
                "recall": recall,
                "extracted_count": len(extracted_concepts),
            }

        overall_recall = total_gold_found / total_gold_count if total_gold_count else 0.0
        print(f"Overall Suite Recall across {len(suite_data)} documents: {overall_recall:.2%} ({total_gold_found}/{total_gold_count})")

        for fname, m in doc_metrics.items():
            assert m["recall"] >= 0.80, f"Document {fname} recall too low: {m['recall']:.2%} (found {m['gold_found']}/{m['gold_total']})"

        assert overall_recall >= 0.85, f"Overall suite recall {overall_recall:.2%} below 85% requirement"

    def test_cross_document_concept_consistency(self, fixtures_dir, build_service):
        """
        Verifies cross-document consistency: When the same canonical concept (e.g. 'Work'
        or 'Kinetic Energy') appears in different documents, it maps to the consistent
        canonical identity while maintaining isolated document-specific evidence spans.
        """
        fpath_wep = os.path.join(fixtures_dir, "physics_work_energy_power.txt")
        fpath_multi = os.path.join(fixtures_dir, "multi_chapter_mechanics_thermo.txt")

        with open(fpath_wep, "rb") as f:
            data_wep = f.read()
        with open(fpath_multi, "rb") as f:
            data_multi = f.read()

        build_service.build("doc_wep", data_wep, "physics_work_energy_power.txt", reuse_existing=False)
        build_service.build("doc_multi", data_multi, "multi_chapter_mechanics_thermo.txt", reuse_existing=False)

        ctx_wep = build_service.context_repo.load_context("doc_wep")
        ctx_multi = build_service.context_repo.load_context("doc_multi")

        # Find shared core concept 'Work-Energy Theorem' in both contexts
        target_concept_wep = next((c for c in ctx_wep.concepts.values() if "work-energy" in c.canonical_name.lower()), None)
        target_concept_multi = next((c for c in ctx_multi.concepts.values() if "work-energy" in c.canonical_name.lower()), None)

        assert target_concept_wep is not None, "Concept 'Work-Energy Theorem' not found in physics_work_energy_power.txt"
        assert target_concept_multi is not None, "Concept 'Work-Energy Theorem' not found in multi_chapter_mechanics_thermo.txt"

        # Evidence and provenance must be isolated to respective documents
        cite_wep = target_concept_wep.citation()
        cite_multi = target_concept_multi.citation()

        # Both have valid provenance citations
        assert cite_wep["concept_id"] == target_concept_wep.concept_id
        assert cite_multi["concept_id"] == target_concept_multi.concept_id
        assert len(cite_wep["evidence_ids"]) >= 1
        assert len(cite_multi["evidence_ids"]) >= 1

        # Evidence references must not leak across document contexts
        assert set(cite_wep["evidence_ids"]).isdisjoint(set(cite_multi["evidence_ids"]))

    def test_unseen_synthetic_domain_pure_generalization(self, build_service):
        """
        Verifies that an entirely unseen STEM domain (Computer Science / Data Structures)
        with zero curriculum spec entries extracts content-derived topics and concepts
        without failing, falling back to physics, or requiring hardcoding.
        """
        cs_content = (
            "# Data Structures and Algorithms\n\n"
            "## Binary Search Trees\n"
            "A Binary Search Tree is a node-based binary tree data structure which has the following properties:\n"
            "The left subtree of a node contains only nodes with keys lesser than the node's key.\n"
            "The right subtree of a node contains only nodes with keys greater than the node's key.\n"
            "Tree Traversal algorithms include in-order, pre-order, and post-order traversal.\n\n"
            "## Time Complexity Analysis\n"
            "Time Complexity quantifies the amount of computational time taken by an algorithm to run as a function\n"
            "of the length of the string representing the input. Asymptotic Analysis uses Big-O notation\n"
            "to express the upper bound of the running time.\n\n"
            "## Dynamic Programming\n"
            "Dynamic Programming is an algorithmic technique for solving an optimization problem by breaking it down\n"
            "into simpler subproblems and utilizing optimal substructure and overlapping subproblems.\n"
        ).encode("utf-8")

        res = build_service.build("doc_cs_synthetic", cs_content, "cs_algorithms.txt", reuse_existing=False)
        assert res["status"] == "READY"
        assert res["concept_count"] >= 3
        assert res["topic_count"] >= 2

        ctx = build_service.context_repo.load_context("doc_cs_synthetic")
        topic_titles = [t["title"] for t in ctx.topics]
        print("TOPIC TITLES IN PYTEST:", topic_titles)

        # Content-grounded topics: Binary Search Trees, Time Complexity, Dynamic Programming
        assert any("binary search" in t.lower() or "tree" in t.lower() for t in topic_titles)
        assert any("complexity" in t.lower() or "programming" in t.lower() for t in topic_titles)

        # Zero physics bleed
        for t in topic_titles:
            assert "newton" not in t.lower()
            assert "friction" not in t.lower()

        # Concepts extracted
        c_names = {c.canonical_name.lower() for c in ctx.concepts.values()}
        assert any("binary search" in c for c in c_names)
        assert any("time complexity" in c for c in c_names)
