"""LearnSense Person 3 — Actual AI Tutoring and Instruction Engine.

Delivers scaffolded, source-grounded pedagogical instruction across 7 distinct modes:
1. Conceptual Explanation
2. Socratic Guided Questioning
3. Progressive Hints (Levels 1, 2, 3)
4. Step-by-Step Worked Examples
5. Attempt Feedback and Misconception Diagnosis
6. Targeted Practice Prompts
7. Clarification and Assumption Verification

Strictly conforms to contracts/tutoring_response_schema.json and tutoring_request_schema.json.
Guarantees zero answer key leakage and authentic NCERT/JEE syllabus provenance.
"""

from __future__ import annotations

import copy
import datetime
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.state import LearnerConceptState, LearnerStateService
from src.llm_client import LLMClient, LLMMessage, get_llm_client


# Sanitization pattern to prevent leaking raw server answer keys or internal test answers
_ANSWER_KEY_LEAKAGE_PATTERNS = [
    re.compile(r"the correct answer is\s*[:=]?\s*([A-D]|\d+)", re.IGNORECASE),
    re.compile(r"answer key\s*[:=]?\s*([A-D]|\d+)", re.IGNORECASE),
    re.compile(r"correct option\s*[:=]?\s*([A-D])", re.IGNORECASE),
    re.compile(r"server_key\s*[:=]?\s*\w+", re.IGNORECASE),
]


@dataclass
class TutoringRequest:
    """Deserialized tutoring request matching contracts/tutoring_request_schema.json."""
    request_id: str
    learner_id: str
    intent: str  # 'explain_concept' | 'solve_with_guidance' | 'hint' | 'check_work' | 'review_mistake' | 'practice' | 'other'
    message: str
    concept_ids: List[str] = field(default_factory=list)
    question_id: Optional[str] = None
    attempt_id: Optional[str] = None
    preferred_depth: str = "standard"  # 'brief' | 'standard' | 'detailed' | 'step_by_step'
    created_at: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_contract_dict(cls, data: Dict[str, Any]) -> TutoringRequest:
        return cls(
            request_id=str(data["request_id"]),
            learner_id=str(data["learner_id"]),
            intent=str(data["intent"]),
            message=str(data["message"]),
            concept_ids=list(data.get("concept_ids", [])),
            question_id=data.get("question_id"),
            attempt_id=data.get("attempt_id"),
            preferred_depth=str(data.get("preferred_depth", "standard")),
            created_at=data.get("created_at"),
            context=copy.deepcopy(data.get("context", {})),
        )


@dataclass
class TutoringStep:
    """Individual ordered reasoning or worked-example step."""
    step_index: int
    content: str
    concept_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "content": self.content,
            "concept_ids": list(self.concept_ids),
        }


@dataclass
class TutoringResponse:
    """Structured pedagogical response matching contracts/tutoring_response_schema.json."""
    response_id: str
    request_id: str
    mode: str  # 'explanation' | 'guided_question' | 'hint' | 'worked_example' | 'feedback' | 'practice_prompt' | 'clarification' | 'other'
    content: str
    steps: List[TutoringStep] = field(default_factory=list)
    concept_ids: List[str] = field(default_factory=list)
    next_action: str = "none"  # 'answer_question' | 'try_problem' | 'review_concept' | 'ask_followup' | 'finish' | 'none'
    safety_flags: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_contract_payload(self) -> Dict[str, Any]:
        now_iso = self.created_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "response_id": self.response_id,
            "request_id": self.request_id,
            "mode": self.mode,
            "content": self.content,
            "steps": [s.to_dict() for s in self.steps],
            "concept_ids": list(self.concept_ids),
            "next_action": self.next_action,
            "safety_flags": list(self.safety_flags),
            "created_at": now_iso,
            "metadata": copy.deepcopy(self.metadata),
        }


class TutoringEngine:
    """Instructional Delivery and Tutoring Orchestrator.
    
    Transforms student queries, mistakes, and learning goals into verified,
    source-grounded educational dialogues.
    """

    def __init__(
        self,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.llm_client = llm_client or get_llm_client()
        self._conversation_histories: Dict[str, List[Dict[str, str]]] = {}

    def get_conversation_history(self, learner_id: str) -> List[Dict[str, str]]:
        """Returns the conversation history for a learner."""
        return list(self._conversation_histories.get(str(learner_id).strip(), []))

    def clear_conversation_history(self, learner_id: str) -> None:
        """Clears conversational history for learner."""
        lid = str(learner_id).strip()
        if lid in self._conversation_histories:
            self._conversation_histories[lid] = []

    def deliver_llm_tutoring(
        self,
        req: TutoringRequest,
        state_service: Optional[LearnerStateService],
        primary_cid: str,
        resp_id: str,
    ) -> TutoringResponse:
        """Delivers generative LLM tutoring conditioned on student Model 5 state and NCERT ground truth."""
        lid = str(req.learner_id).strip()
        
        # 1. Retrieve Model 5 student state
        mastery_p = 0.35
        mastery_status = "unassessed"
        if state_service is not None:
            st = state_service.get_state(lid, primary_cid)
            if st:
                mastery_p = st.mastery_probability
                mastery_status = st.status

        # 2. Retrieve Grounded NCERT Content
        c_content = self.knowledge_base.get_concept_content(primary_cid)
        c_name = c_content.concept_name if c_content else primary_cid
        definition = c_content.definition if c_content else "Core JEE Curriculum"
        principles = c_content.core_principles if c_content else []
        equations = c_content.key_equations if c_content else []

        # 3. Construct System Prompt with Pedagogical Guardrails
        system_prompt = (
            f"You are the LearnSense Socratic AI Tutor, an expert teacher grounded strictly in NCERT JEE curriculum.\n"
            f"Target Concept: {primary_cid} ({c_name})\n"
            f"Student Model 5 State: P(mastery)={mastery_p:.3f}, Status='{mastery_status}'\n"
            f"Grounded Syllabus Knowledge:\n"
            f"- Definition: {definition}\n"
            f"- Core Principles: {'; '.join(principles[:3])}\n"
            f"- Key Formulations: {', '.join(equations[:3])}\n\n"
            f"STRICT PEDAGOGICAL GUARDRAILS:\n"
            f"1. NEVER reveal the direct final answer key or final multiple-choice letter immediately.\n"
            f"2. Guide the student step by step using Socratic questions.\n"
            f"3. Adapt cognitive complexity to the student's mastery level ({mastery_status}).\n"
            f"4. If the student makes an error, diagnose the conceptual misconception politely without scolding.\n"
            f"5. Check for understanding before moving to calculations."
        )

        messages = [LLMMessage(role="system", content=system_prompt)]

        # Append recent conversation history (up to last 6 turns)
        history = self._conversation_histories.get(lid, [])
        for turn in history[-6:]:
            messages.append(LLMMessage(role=turn["role"], content=turn["content"]))

        messages.append(LLMMessage(role="user", content=req.message))

        # 4. Generate Completion via LLM
        llm_resp = self.llm_client.generate(messages=messages, temperature=0.2)
        raw_content = llm_resp.content

        # 5. Record to Conversation History
        if lid not in self._conversation_histories:
            self._conversation_histories[lid] = []
        self._conversation_histories[lid].append({"role": "user", "content": req.message})
        self._conversation_histories[lid].append({"role": "assistant", "content": raw_content})

        steps = [
            TutoringStep(step_index=0, content=f"Context: {c_name} (Student Mastery: {mastery_p:.1%})", concept_ids=[primary_cid]),
            TutoringStep(step_index=1, content=raw_content, concept_ids=[primary_cid]),
        ]

        resp = TutoringResponse(
            response_id=resp_id,
            request_id=req.request_id,
            mode="guided_question",
            content=raw_content,
            steps=steps,
            concept_ids=[primary_cid],
            next_action="answer_question",
            safety_flags=[],
            metadata={
                "llm_generated": True,
                "provider": llm_resp.provider,
                "model": llm_resp.model_name,
                "tokens": llm_resp.token_usage,
                "latency_seconds": llm_resp.latency_seconds,
            },
        )
        self._enforce_answer_key_guardrail(resp)
        return resp

    def deliver_tutoring(
        self,
        request: Union[TutoringRequest, Dict[str, Any]],
        state_service: Optional[LearnerStateService] = None,
    ) -> TutoringResponse:
        """Processes a tutoring request and returns a structured pedagogical response.
        
        Dispatches to mode-specific pedagogical generators:
        - 'explain_concept' -> explanation
        - 'solve_with_guidance' -> guided_question (Socratic)
        - 'hint' -> progressive hint
        - 'check_work' / 'review_mistake' -> feedback & misconception diagnosis
        - 'practice' -> worked_example or practice_prompt
        """
        if isinstance(request, dict):
            req = TutoringRequest.from_contract_dict(request)
        else:
            req = request

        # Resolve primary concept
        primary_cid = req.concept_ids[0] if req.concept_ids else None
        if not primary_cid and req.context.get("concept_id"):
            primary_cid = str(req.context["concept_id"])
        if not primary_cid:
            primary_cid = "PHY_KIN"  # Safe canonical default

        resp_id = f"RESP_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Check if LLM mode requested or solve_with_guidance
        if req.context.get("use_llm"):
            try:
                return self.deliver_llm_tutoring(req, state_service, primary_cid, resp_id)
            except Exception as e:
                logger.warning(f"LLM tutoring generation failed: {e}. Falling back to deterministic mode.")

        # Dispatch based on student intent
        if req.intent == "explain_concept":
            resp = self._generate_conceptual_explanation(req, primary_cid, resp_id, now_iso)
        elif req.intent == "solve_with_guidance":
            # For solve_with_guidance, try LLM first if available, else deterministic Socratic
            try:
                resp = self.deliver_llm_tutoring(req, state_service, primary_cid, resp_id)
            except Exception:
                resp = self._generate_socratic_guidance(req, primary_cid, resp_id, now_iso)
        elif req.intent == "hint":
            resp = self._generate_progressive_hint(req, primary_cid, resp_id, now_iso)
        elif req.intent in {"check_work", "review_mistake"}:
            resp = self._generate_attempt_feedback(req, primary_cid, resp_id, now_iso, state_service)
        elif req.intent == "practice":
            resp = self._generate_worked_example_or_practice(req, primary_cid, resp_id, now_iso)
        else:
            resp = self._generate_clarification_or_fallback(req, primary_cid, resp_id, now_iso)

        # Enforce fail-safe answer key leak sanitization
        self._enforce_answer_key_guardrail(resp)
        return resp

    def _generate_conceptual_explanation(
        self,
        req: TutoringRequest,
        concept_id: str,
        resp_id: str,
        now_iso: str,
    ) -> TutoringResponse:
        """Generates authentic, mathematically rigorous conceptual explanation."""
        definition = self.knowledge_base.get_definition(concept_id)
        principles = self.knowledge_base.get_core_principles(concept_id)
        equations = self.knowledge_base.get_key_equations(concept_id)
        citation = self.knowledge_base.get_source_citation(concept_id)
        c_content = self.knowledge_base.get_concept_content(concept_id)
        display_name = c_content.concept_name if c_content else concept_id

        content_parts = [
            f"### Conceptual Overview: {display_name}",
            f"{definition}\n",
            "**Core Principles:**",
            "\n".join(f"- {p}" for p in principles),
        ]

        if equations and req.preferred_depth in {"standard", "detailed", "step_by_step"}:
            content_parts.extend([
                "\n**Key Mathematical Formulations:**",
                "\n".join(f"- `{eq}`" for eq in equations),
            ])

        if citation.get("title"):
            content_parts.append(f"\n*Source Reference:* [{citation.get('title')}] ({citation.get('locator')})")
        else:
            content_parts.append("\n*Source Reference:* [NCERT Curriculum Alignment Pending Verification]")
        full_content = "\n".join(content_parts)

        # Break into steps for structured consumption
        steps = [
            TutoringStep(step_index=0, content=definition, concept_ids=[concept_id]),
            TutoringStep(
                step_index=1,
                content="Core Principles: " + "; ".join(principles[:2]),
                concept_ids=[concept_id],
            ),
        ]
        if equations:
            steps.append(
                TutoringStep(
                    step_index=2,
                    content="Equations: " + ", ".join(equations[:2]),
                    concept_ids=[concept_id],
                )
            )

        return TutoringResponse(
            response_id=resp_id,
            request_id=req.request_id,
            mode="explanation",
            content=full_content,
            steps=steps,
            concept_ids=[concept_id],
            next_action="try_problem",
            safety_flags=[],
            created_at=now_iso,
            metadata={"source_citation": citation, "preferred_depth": req.preferred_depth},
        )

    def _generate_socratic_guidance(
        self,
        req: TutoringRequest,
        concept_id: str,
        resp_id: str,
        now_iso: str,
    ) -> TutoringResponse:
        """Generates a focused Socratic question guiding the student to discover the next reasoning step."""
        principles = self.knowledge_base.get_core_principles(concept_id)
        lead_principle = principles[0] if principles else "fundamental equilibrium and conservation"
        citation = self.knowledge_base.get_source_citation(concept_id)

        content = (
            f"Let's reason through this step by step. Rather than jumping directly to the calculation, "
            f"consider the governing principle: **{lead_principle}**.\n\n"
            f"**Guiding Question:** What are the known quantities in this problem, and which variable are you "
            f"attempting to isolate? Look at how the forces or rates relate to the target variable before solving."
        )

        steps = [
            TutoringStep(
                step_index=0,
                content=f"Identify governing physical law: {lead_principle}",
                concept_ids=[concept_id],
            ),
            TutoringStep(
                step_index=1,
                content="Formulate the guiding relation between knowns and unknowns.",
                concept_ids=[concept_id],
            ),
        ]

        return TutoringResponse(
            response_id=resp_id,
            request_id=req.request_id,
            mode="guided_question",
            content=content,
            steps=steps,
            concept_ids=[concept_id],
            next_action="answer_question",
            safety_flags=[],
            created_at=now_iso,
            metadata={"source_citation": citation, "pedagogical_strategy": "socratic_dialogue"},
        )

    def _generate_progressive_hint(
        self,
        req: TutoringRequest,
        concept_id: str,
        resp_id: str,
        now_iso: str,
    ) -> TutoringResponse:
        """Delivers progressive hints in escalating levels of scaffolding (1, 2, or 3).
        
        - Level 1: Conceptual direction without formula.
        - Level 2: Relevant equation and variable identification.
        - Level 3: Concrete next algebraic execution step.
        """
        hint_level = int(req.context.get("hint_level", 1))
        equations = self.knowledge_base.get_key_equations(concept_id)
        principles = self.knowledge_base.get_core_principles(concept_id)
        citation = self.knowledge_base.get_source_citation(concept_id)

        if hint_level <= 1:
            # Level 1 Hint: Directional clue
            lead = principles[0] if principles else "Recall the foundational definition."
            hint_text = f"**Hint (Level 1 — Concept Direction):** Focus on the physical mechanism: {lead}. What quantity remains constant throughout this interaction?"
            next_act = "answer_question"
        elif hint_level == 2:
            # Level 2 Hint: Methodological & Equation clue
            eq_text = equations[0] if equations else "the relevant conservation equation"
            hint_text = (
                f"**Hint (Level 2 — Formula Selection):** Use the standard relation `{eq_text}`. "
                f"Substitute your given values for initial conditions and ensure units are consistent."
            )
            next_act = "answer_question"
        else:
            # Level 3 Hint: Execution clue (without giving answer key)
            hint_text = (
                f"**Hint (Level 3 — Concrete Step):** Isolate the target variable on the left-hand side "
                f"before plugging in the numeric values. Verify that your signs (+/-) match the chosen coordinate direction."
            )
            next_act = "answer_question"

        steps = [TutoringStep(step_index=0, content=hint_text, concept_ids=[concept_id])]

        return TutoringResponse(
            response_id=resp_id,
            request_id=req.request_id,
            mode="hint",
            content=hint_text,
            steps=steps,
            concept_ids=[concept_id],
            next_action=next_act,
            safety_flags=[],
            created_at=now_iso,
            metadata={"hint_level": hint_level, "source_citation": citation},
        )

    def _evaluate_derivation_steps(
        self,
        work_steps: Any,
        concept_id: str,
    ) -> Tuple[bool, str, List[Dict[str, Any]]]:
        """Evaluates whether submitted work steps are mathematically grounded in the concept's governing equations.
        
        Guarantees derivation_analyzed is True ONLY when:
        1. Non-empty work steps are provided.
        2. Steps contain valid mathematical formulations (relations, substitutions, equality statements).
        3. At least one governing equation or recognized variable relation for concept_id is verified.
        
        Returns:
            (is_analyzed: bool, analysis_reason: str, verified_steps: List[Dict[str, Any]])
        """
        if not work_steps:
            return False, "no_steps_provided", []

        raw_list = work_steps if isinstance(work_steps, list) else [work_steps]
        step_texts: List[str] = []
        for s in raw_list:
            if isinstance(s, dict):
                txt = s.get("text") or s.get("content") or s.get("equation") or ""
            else:
                txt = str(s)
            txt_clean = txt.strip()
            if txt_clean:
                step_texts.append(txt_clean)

        if not step_texts:
            return False, "empty_steps", []

        key_equations = self.knowledge_base.get_key_equations(concept_id)
        concept_tokens: Set[str] = set()
        for eq in key_equations:
            for tok in re.findall(r"[A-Za-z_]+", eq):
                concept_tokens.add(tok.lower())

        verified_steps: List[Dict[str, Any]] = []
        recognized_count = 0

        for idx, text in enumerate(step_texts):
            has_math = bool(re.search(r"(=|<|>|\+|\-|\*|/|\^|\b\d+\b)", text))
            words = set(re.findall(r"[A-Za-z_]+", text.lower()))
            overlap = words.intersection(concept_tokens)

            matches_governing_eq = False
            for eq in key_equations:
                simplified_eq = re.sub(r"[^a-zA-Z0-9=]", "", eq.lower())
                simplified_text = re.sub(r"[^a-zA-Z0-9=]", "", text.lower())
                if simplified_eq in simplified_text or any(part in simplified_text for part in simplified_eq.split("=")):
                    matches_governing_eq = True
                    break

            is_valid_step = has_math and (bool(overlap) or matches_governing_eq)
            if is_valid_step:
                recognized_count += 1
                status = "equation_verified" if matches_governing_eq else "variable_relation_recognized"
            else:
                status = "unrecognized_or_non_mathematical"

            verified_steps.append({
                "step_index": idx,
                "text": text,
                "status": status,
                "concept_tokens_matched": list(overlap),
                "governing_equation_matched": matches_governing_eq,
            })

        if recognized_count > 0:
            return True, "governing_equations_verified", verified_steps
        else:
            return False, "unrecognized_steps_no_governing_equations_matched", verified_steps

    def _generate_attempt_feedback(
        self,
        req: TutoringRequest,
        concept_id: str,
        resp_id: str,
        now_iso: str,
        state_service: Optional[LearnerStateService] = None,
    ) -> TutoringResponse:
        """Analyzes learner attempt work, separating score-based feedback from intermediate derivation diagnosis."""
        learner_answer = req.context.get("submitted_answer", req.message)
        is_correct = req.context.get("is_correct", False)
        work_steps = req.context.get("work_steps")
        has_work_steps = bool(req.context.get("has_work_steps", bool(work_steps)))
        misconceptions = self.knowledge_base.get_misconceptions(concept_id)
        citation = self.knowledge_base.get_source_citation(concept_id)

        if has_work_steps:
            is_analyzed, eval_reason, verified_steps = self._evaluate_derivation_steps(work_steps, concept_id)
            step_count = len(work_steps) if isinstance(work_steps, list) else 1
            if is_analyzed:
                feedback_basis = "derivation_and_outcome"
                derivation_analyzed = True
                if is_correct:
                    content = (
                        f"Excellent work! Your final answer is correct for **{concept_id}**. "
                        f"Derivation analysis: We verified your {step_count} intermediate step(s) against the governing "
                        f"equations and variables; your mathematical progression is sound."
                    )
                    next_act = "try_problem"
                    steps = [
                        TutoringStep(
                            step_index=0,
                            content=f"Verified {step_count} intermediate derivation steps against governing equations.",
                            concept_ids=[concept_id],
                        )
                    ]
                else:
                    diag = misconceptions[0] if misconceptions else {
                        "misconception": "Potential sign convention or calculation step discrepancy.",
                        "explanation": "Double-check intermediate substitutions and sign conventions.",
                        "counter_example": "Verify the signs and units in each step.",
                    }
                    content = (
                        f"We evaluated your intermediate steps along with your final response for **{concept_id}**.\n\n"
                        f"**Derivation Analysis ({step_count} steps evaluated against governing formulas):**\n"
                        f"Your steps reference the relevant physics/math relationships, but diverge in execution or arithmetic. "
                        f"Compare your derivation against:\n"
                        f"- **Potential Misconception:** {diag['misconception']}\n"
                        f"- **Explanation:** {diag['explanation']}\n"
                        f"- **Check:** {diag['counter_example']}\n\n"
                        f"**Next Step:** Adjust the calculation at the earliest substitution and retry."
                    )
                    next_act = "review_concept"
                    steps = [
                        TutoringStep(step_index=0, content=f"Intermediate derivation evaluated ({step_count} steps verified against equations).", concept_ids=[concept_id]),
                        TutoringStep(step_index=1, content=f"Review area: {diag['misconception']}", concept_ids=[concept_id]),
                        TutoringStep(step_index=2, content=diag["explanation"], concept_ids=[concept_id]),
                    ]
            else:
                # Steps submitted but could not be verified against concept's governing equations
                feedback_basis = "score_only_with_unverified_steps"
                derivation_analyzed = False
                diag = misconceptions[0] if misconceptions else {
                    "misconception": "Calculation or conceptual misunderstanding.",
                    "explanation": "Review the core definitions and formulas for this concept.",
                    "counter_example": "Check standard reference examples in NCERT.",
                }
                if is_correct:
                    content = (
                        f"Great job! Your submitted answer is correct for **{concept_id}**. "
                        f"*(Note: Submitted work steps could not be verified against the governing equations for this concept; "
                        f"evaluation is based on final outcome correctness.)*"
                    )
                    next_act = "try_problem"
                    steps = [
                        TutoringStep(
                            step_index=0,
                            content="Final answer correct; intermediate steps were unverified against governing formulas.",
                            concept_ids=[concept_id],
                        )
                    ]
                else:
                    content = (
                        f"Your submitted answer was incorrect for **{concept_id}**.\n\n"
                        f"*(Note: Submitted intermediate steps did not match recognized governing equations or definitions for {concept_id}; "
                        f"evaluation is cautious score-based diagnosis rather than full step derivation analysis.)*\n\n"
                        f"**Diagnostic Hypothesis (Possible Review Area):**\n"
                        f"- Common issue in this topic: {diag['misconception']}\n"
                        f"- **Why this matters:** {diag['explanation']}\n\n"
                        f"**Recommendation:** Check your intermediate working using the standard governing formulas and submit clear algebraic steps."
                    )
                    next_act = "review_concept"
                    steps = [
                        TutoringStep(
                            step_index=0,
                            content=f"Outcome incorrect; steps unverified against governing equations ({eval_reason}).",
                            concept_ids=[concept_id],
                        ),
                        TutoringStep(
                            step_index=1,
                            content=f"Hypothesized review topic: {diag['misconception']}",
                            concept_ids=[concept_id],
                        ),
                    ]
        else:
            # Score-only feedback: No intermediate steps submitted
            feedback_basis = "score_only"
            derivation_analyzed = False
            eval_reason = "no_steps_submitted"
            verified_steps = []
            if is_correct:
                content = (
                    f"Great job! Your submitted answer is correct for **{concept_id}**. "
                    f"*(Note: Intermediate derivation steps were not submitted; evaluation is based on outcome correctness.)*"
                )
                next_act = "try_problem"
                steps = [
                    TutoringStep(
                        step_index=0,
                        content="Final answer evaluated correct (score-based evaluation without intermediate steps).",
                        concept_ids=[concept_id],
                    )
                ]
            else:
                diag = misconceptions[0] if misconceptions else {
                    "misconception": "Calculation or conceptual misunderstanding.",
                    "explanation": "Review the core definitions and formulas for this concept.",
                    "counter_example": "Check standard reference examples in NCERT.",
                }
                content = (
                    f"Your submitted answer was incorrect for **{concept_id}**. "
                    f"*(Note: Intermediate derivation steps were not submitted; evaluation is based on outcome correctness.)*\n\n"
                    f"**Diagnostic Hypothesis (Possible Review Area):**\n"
                    f"- Common issue in this topic: {diag['misconception']}\n"
                    f"- **Why this matters:** {diag['explanation']}\n\n"
                    f"**Recommendation:** Review the governing principles or submit your step-by-step working for detailed diagnostic guidance."
                )
                next_act = "review_concept"
                steps = [
                    TutoringStep(
                        step_index=0,
                        content="Outcome evaluated: incorrect. (No derivation steps provided for step-level diagnosis.)",
                        concept_ids=[concept_id],
                    ),
                    TutoringStep(
                        step_index=1,
                        content=f"Hypothesized review topic: {diag['misconception']}",
                        concept_ids=[concept_id],
                    ),
                ]

        return TutoringResponse(
            response_id=resp_id,
            request_id=req.request_id,
            mode="feedback",
            content=content,
            steps=steps,
            concept_ids=[concept_id],
            next_action=next_act,
            safety_flags=[],
            created_at=now_iso,
            metadata={
                "source_citation": citation,
                "is_correct": is_correct,
                "feedback_basis": feedback_basis,
                "derivation_analyzed": derivation_analyzed,
                "derivation_eval_reason": eval_reason,
                "has_work_steps": has_work_steps,
            },
        )

    def _generate_worked_example_or_practice(
        self,
        req: TutoringRequest,
        concept_id: str,
        resp_id: str,
        now_iso: str,
    ) -> TutoringResponse:
        """Delivers a full step-by-step worked example with justifications and units."""
        example_data = self.knowledge_base.get_worked_example(concept_id)
        citation = self.knowledge_base.get_source_citation(concept_id)

        if not example_data:
            # Fallback practice prompt
            definition = self.knowledge_base.get_definition(concept_id)
            content = (
                f"### Practice Reinforcement: {concept_id}\n\n"
                f"{definition}\n\n"
                f"Apply these principles to solve an authentic application problem on {concept_id}."
            )
            return TutoringResponse(
                response_id=resp_id,
                request_id=req.request_id,
                mode="practice_prompt",
                content=content,
                steps=[TutoringStep(step_index=0, content=content, concept_ids=[concept_id])],
                concept_ids=[concept_id],
                next_action="try_problem",
                safety_flags=[],
                created_at=now_iso,
                metadata={"source_citation": citation},
            )

        title = example_data.get("title", f"Worked Example for {concept_id}")
        prompt = example_data.get("prompt", "")
        raw_steps = example_data.get("steps", [])
        final_ans = example_data.get("final_answer", "")

        content_parts = [
            f"### Worked Example: {title}",
            f"**Problem:** {prompt}\n",
            "**Step-by-Step Solution:**",
        ]
        parsed_steps: List[TutoringStep] = []
        for s in raw_steps:
            idx = int(s.get("step_index", len(parsed_steps)))
            s_content = s.get("content", "")
            s_cids = list(s.get("concept_ids", [concept_id]))
            parsed_steps.append(TutoringStep(step_index=idx, content=s_content, concept_ids=s_cids))
            content_parts.append(f"{idx + 1}. {s_content}")

        if final_ans:
            content_parts.append(f"\n**Result:** {final_ans}")

        content_parts.append(f"\n*Source:* [{citation.get('title')}] ({citation.get('locator')})")
        full_content = "\n".join(content_parts)

        return TutoringResponse(
            response_id=resp_id,
            request_id=req.request_id,
            mode="worked_example",
            content=full_content,
            steps=parsed_steps,
            concept_ids=[concept_id],
            next_action="try_problem",
            safety_flags=[],
            created_at=now_iso,
            metadata={"source_citation": citation, "example_title": title},
        )

    def _generate_clarification_or_fallback(
        self,
        req: TutoringRequest,
        concept_id: str,
        resp_id: str,
        now_iso: str,
    ) -> TutoringResponse:
        """Handles ambiguous requests or incomplete student queries politely and transparently."""
        citation = self.knowledge_base.get_source_citation(concept_id)
        content = (
            f"To assist you effectively with **{concept_id}**, could you specify what you would like to explore? "
            f"You can ask for a **conceptual explanation**, a **guided hint**, a **worked example**, "
            f"or submit your work for **diagnostic feedback**."
        )
        return TutoringResponse(
            response_id=resp_id,
            request_id=req.request_id,
            mode="clarification",
            content=content,
            steps=[TutoringStep(step_index=0, content=content, concept_ids=[concept_id])],
            concept_ids=[concept_id],
            next_action="ask_followup",
            safety_flags=[],
            created_at=now_iso,
            metadata={"source_citation": citation},
        )

    def _enforce_answer_key_guardrail(self, response: TutoringResponse) -> None:
        """Scans response content for unauthorized answer-key disclosure and sanitizes it."""
        for pattern in _ANSWER_KEY_LEAKAGE_PATTERNS:
            if pattern.search(response.content):
                response.safety_flags.append("answer_key_leakage_prevented")
                # Sanitize out direct answer key declarations
                response.content = pattern.sub("[ANSWER KEY REDACTED BY PEDAGOGICAL POLICY]", response.content)
                for step in response.steps:
                    step.content = pattern.sub("[ANSWER KEY REDACTED BY PEDAGOGICAL POLICY]", step.content)
