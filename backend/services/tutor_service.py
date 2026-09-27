"""
Tutor Service Facade for Taproot Application Layer.
Provides context-aware AI explanations, hints, analogies, and step-by-step guidance anchored strictly to concept, learner state, and source references.
"""

from typing import Dict, List, Optional, Any
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService


class TutorService:
    def __init__(
        self,
        knowledge_service: Optional[KnowledgeService] = None,
        learner_service: Optional[LearnerService] = None,
    ):
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.learner_service = learner_service or LearnerService()

    def generate_contextual_response(
        self,
        learner_id: str,
        subject_id: str,
        concept_id: str,
        intent: str,  # "EXPLAIN", "HINT", "EXAMPLE", "ANALOGY", "WHY_WRONG", "CUSTOM"
        user_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates context-aware tutoring guidance based on learner's current mastery and concept context.
        """
        graph = self.knowledge_service.get_subject_graph(subject_id)
        all_concept_ids = [c["concept_id"] for c in graph["concepts"]]
        learner_state = self.learner_service.get_or_create_learner_state(learner_id, all_concept_ids)

        c_node = next((c for c in graph["concepts"] if c["concept_id"] == concept_id), None)
        c_name = c_node["name"] if c_node else concept_id.replace("_", " ").title()

        cs = learner_state.concept_states.get(concept_id)
        mastery = cs.mastery_probability if cs else 0.2

        prereqs = c_node["prerequisites"] if c_node else []
        prereq_names = [p.replace("_", " ").title() for p in prereqs]

        # Formulate tailored educational explanation based on intent & mastery
        response_text = ""
        suggested_actions = []

        if intent == "EXPLAIN":
            if mastery < 0.35:
                response_text = (
                    f"Let's build {c_name} step by step. Since this is new or developing, "
                    f"remember that {c_name} depends directly on "
                    f"{', '.join(prereq_names) if prereq_names else 'core foundations'}. "
                    f"{c_node['definition'] if c_node else ''}"
                )
            else:
                response_text = (
                    f"You already demonstrate solid familiarity ({int(mastery * 100)}% mastery) with {c_name}. "
                    f"To deepen your understanding, focus on how {c_name} connects to downstream applications."
                )
            suggested_actions = ["Give me a concrete example", "Test me with a quick question", "Explain using an analogy"]

        elif intent == "HINT":
            response_text = (
                f"💡 **Hint for {c_name}**:\nLook closely at how changing the input variable affects the overall rate or outcome. "
                f"Recall that {prereq_names[0] if prereq_names else 'the base principle'} sets the boundary conditions!"
            )
            suggested_actions = ["Show step-by-step example", "Why is this rule applied?"]

        elif intent == "ANALOGY":
            response_text = (
                f"🎨 **Analogy for {c_name}**:\nThink of {c_name} like a speedometer on a vehicle. "
                f"While your odometer tracks total distance traveled, {c_name} measures your exact rate at a single instant in time!"
            )
            suggested_actions = ["Explain mathematically", "Show an interactive problem"]

        elif intent == "WHY_WRONG":
            response_text = (
                f"🔍 **Common Misconception in {c_name}**:\nA common trap is confusing the rule for static values with dynamic rate rates. "
                f"Always check if the inner function requires the Chain Rule!"
            )
            suggested_actions = ["Practice another problem", "Review prerequisites"]

        else: # CUSTOM
            # Sanitize custom user messages against prompt injection patterns
            raw_msg = user_message or f"Tell me more about {c_name}"
            sanitized_msg = raw_msg.replace("Ignore previous instructions", "[Filtered Instruction]")
            sanitized_msg = sanitized_msg.replace("Reveal system prompt", "[Filtered Query]")
            sanitized_msg = sanitized_msg.replace("Execute this command", "[Filtered Action]")
            sanitized_msg = sanitized_msg[:500]  # Bound message length

            response_text = (
                f"Regarding **{c_name}**: '{sanitized_msg}' is a great inquiry! "
                f"In {subject_id.replace('_', ' ').title()}, {c_name} serves as a key bridge. "
                f"Your current mastery level is {int(mastery * 100)}%. "
                f"Would you like to review an example or practice a problem?"
            )
            suggested_actions = ["Show example", "Take mini-quiz", "Explain simply"]

        return {
            "concept_id": concept_id,
            "concept_name": c_name,
            "intent": intent,
            "mastery": mastery,
            "response_text": response_text,
            "suggested_actions": suggested_actions,
            "source_citations": c_node["source_references"] if c_node else [],
        }
