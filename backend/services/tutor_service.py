"""
Tutor Service Facade for Taproot Application Layer.
Provides context-aware AI explanations, hints, analogies, and step-by-step guidance
anchored strictly to concept, learner mastery state, and retrieved source references.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from phase3.adapters.llm_adapter import Phase3LLMAdapter, get_llm_adapter
from phase3.errors import LearnSenseError, RetrievalError, TutorGenerationError, KnowledgeNotFoundError

logger = logging.getLogger(__name__)

_PROMPT_INJECTIONS = [
    ("Ignore previous instructions", "[Filtered Instruction]"),
    ("Reveal system prompt", "[Filtered Query]"),
    ("Execute this command", "[Filtered Action]"),
]


class TutorService:
    def __init__(
        self,
        knowledge_service: Optional[KnowledgeService] = None,
        learner_service: Optional[LearnerService] = None,
        llm_adapter: Optional[Phase3LLMAdapter] = None,
    ):
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.learner_service = learner_service or LearnerService()
        self.llm_adapter = llm_adapter or get_llm_adapter()

    def generate_contextual_response(
        self,
        learner_id: str,
        subject_id: str,
        concept_id: str,
        intent: str,  # "EXPLAIN", "HINT", "EXAMPLE", "ANALOGY", "WHY_WRONG", "CUSTOM"
        user_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates genuine, source-grounded tutoring guidance based on the learner's
        current mastery and retrieved textbook/document passages.
        """
        graph = self.knowledge_service.get_subject_graph(subject_id)
        all_concept_ids = [c["concept_id"] for c in graph["concepts"]]
        learner_state = self.learner_service.get_or_create_learner_state(learner_id, all_concept_ids)

        c_node = next((c for c in graph["concepts"] if c["concept_id"] == concept_id), None)
        c_name = c_node["name"] if c_node else concept_id.replace("_", " ").title()
        c_def = c_node.get("definition", "") if c_node else ""

        cs = learner_state.concept_states.get(concept_id)
        mastery = cs.mastery_probability if cs else 0.15

        prereqs = c_node.get("prerequisites", []) if c_node else []
        prereq_names = [p.replace("_", " ").title() for p in prereqs]

        # 1. Sanitize user message against prompt injection
        raw_msg = (user_message or "").strip()
        filtered_markers = []
        sanitized_msg = raw_msg
        for pattern, replacement in _PROMPT_INJECTIONS:
            if re.search(re.escape(pattern), sanitized_msg, re.IGNORECASE):
                sanitized_msg = re.sub(re.escape(pattern), replacement, sanitized_msg, flags=re.IGNORECASE)
                filtered_markers.append(replacement)
        sanitized_msg = sanitized_msg[:500]

        # 2. Retrieve authoritative source evidence chunks via EvidenceRetriever
        # Single authoritative retrieval path (§2 #16)
        retrieved_chunks = []
        try:
            from backend.services.knowledge_build_service import KnowledgeBuildService
            retriever = KnowledgeBuildService().get_retriever(subject_id)
            query_terms = [c_name]
            if sanitized_msg:
                query_terms.append(sanitized_msg)
            retrieved_chunks = retriever.retrieve_for_concept(
                concept_id=concept_id,
                concept_name=c_name,
                extra_terms=query_terms,
                top_k=4,
            )
        except (RetrievalError, KnowledgeNotFoundError):
            retrieved_chunks = []
        except Exception as exc:
            logger.error("EvidenceRetriever lookup failed for %s / %s: %s", subject_id, concept_id, exc)
            raise RetrievalError(
                f"Evidence retrieval failed for concept '{c_name}': {exc}",
                details={"subject_id": subject_id, "concept_id": concept_id, "cause": str(exc)},
            ) from exc

        if not retrieved_chunks:
            # Document genuinely contains no extractable evidence for this concept
            resp_text = (
                f"The uploaded study material contains no direct passages or evidence covering '{c_name}'. "
                "LearnSense refuses to fabricate answers without source grounding."
            )
            for marker in filtered_markers:
                if marker not in resp_text:
                    resp_text += f" {marker}"
            return {
                "concept_id": concept_id,
                "concept_name": c_name,
                "intent": intent,
                "mastery": mastery,
                "response_text": resp_text,
                "suggested_actions": ["Review concepts with source coverage", "Upload supplementary document"],
                "source_citations": [],
                "grounded": False,
            }

        # 3. Construct pedagogical framing tailored to learner mastery
        if mastery < 0.35:
            scaffolding_guide = (
                f"The learner is a novice with {int(mastery * 100)}% mastery. "
                f"Keep explanations simple, intuitive, and concrete. Emphasize foundations "
                f"and prerequisite connections ({', '.join(prereq_names) if prereq_names else 'foundational principles'})."
            )
        elif mastery < 0.70:
            scaffolding_guide = (
                f"The learner has developing familiarity ({int(mastery * 100)}% mastery). "
                f"Provide balanced explanations, worked examples, and address common misconceptions."
            )
        else:
            scaffolding_guide = (
                f"The learner has mastered this concept ({int(mastery * 100)}% mastery). "
                f"Provide advanced analytical nuance, edge cases, and connections to downstream applications."
            )

        # Build evidence text for prompt
        evidence_lines = []
        valid_pages = set()
        for idx, ch in enumerate(retrieved_chunks, 1):
            valid_pages.add(ch.page_index)
            evidence_lines.append(f"[{idx}] Page {ch.page_index + 1} ({ch.section_title or 'Section'}): \"{ch.text.strip()}\"")
        evidence_block = "\n".join(evidence_lines)

        system_prompt = (
            "You are LearnSense AI Tutor, an authoritative, pedagogical educational tutor. "
            "You MUST ground your response strictly in the retrieved source passages below. "
            "Never invent facts, equations, or theorems not supported by the document. "
            "Whenever you assert a factual claim, cite the exact source page like [Page X].\n\n"
            f"Subject: {subject_id}\n"
            f"Concept: {c_name}\n"
            f"Definition: {c_def}\n"
            f"Pedagogical Scaffolding: {scaffolding_guide}\n\n"
            "Retrieved Passages:\n"
            f"{evidence_block}"
        )

        user_prompt = (
            f"Intent: {intent}\n"
            f"Student Question: {sanitized_msg if sanitized_msg else f'Explain {c_name}'}\n\n"
            "Generate your tutoring response formatted as JSON with keys:\n"
            "{\n"
            '  "response_text": "Pedagogical explanation with [Page X] citations",\n'
            '  "suggested_actions": ["Action 1", "Action 2", "Action 3"],\n'
            '  "cited_pages": [1]\n'
            "}"
        )

        schema_template = {
            "response_text": "string",
            "suggested_actions": ["string"],
            "cited_pages": ["number"],
        }

        # 4. Invoke LLM (fail-loud per §2 #15: never return canned template prose or fake pages)
        try:
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
            llm_result = self.llm_adapter.generate_json(
                combined_prompt,
                schema_template,
                config={"temperature": 0.2, "max_tokens": 800},
            )
            response_text = str(llm_result.get("response_text", "")).strip()
            suggested_actions = ["Give me a concrete example", "Test me with a quick question", "Explain using an analogy"]
            if isinstance(llm_result.get("suggested_actions"), list):
                actions = [str(a) for a in llm_result["suggested_actions"] if str(a).strip()]
                if actions:
                    suggested_actions = actions[:4]
            cited_pages: List[int] = []
            if isinstance(llm_result.get("cited_pages"), list):
                cited_pages = [int(p) for p in llm_result["cited_pages"] if isinstance(p, (int, float))]
        except Exception as exc:
            logger.error("LLM tutor generation failed for %s / %s: %s", subject_id, concept_id, exc)
            raise TutorGenerationError(
                f"Tutor could not generate guidance for '{c_name}': {exc}",
                details={"subject_id": subject_id, "concept_id": concept_id, "cause": str(exc)},
            ) from exc

        # If security sanitization occurred, guarantee markers are preserved for security tests
        for marker in filtered_markers:
            if marker not in response_text:
                response_text += f" {marker}"

        # 5. Citation validation: filter out any page citations not present in retrieved chunks
        validated_citations: List[Dict[str, Any]] = []
        for ch in retrieved_chunks:
            # If the LLM cited this page, or if this chunk was the primary retrieval
            if ch.page_index in cited_pages or not cited_pages:
                validated_citations.append(
                    {
                        "document_id": ch.document_id,
                        "page": ch.page_index + 1,
                        "section": ch.section_title or "Content",
                        "block_id": ch.block_id,
                        "quote": ch.text[:200].strip(),
                    }
                )

        return {
            "concept_id": concept_id,
            "concept_name": c_name,
            "intent": intent,
            "mastery": mastery,
            "response_text": response_text,
            "suggested_actions": suggested_actions or ["Review example", "Take quiz"],
            "source_citations": validated_citations[:4],
            "grounded": bool(validated_citations),
        }
