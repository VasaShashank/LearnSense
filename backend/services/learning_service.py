"""
Learning Service Facade for Taproot Application Layer.
Orchestrates onboarding self-assessment, diagnostic assessment creation/submission, learning activities, quiz processing, and KT updates.
"""

from typing import Dict, List, Optional, Any
from storage.repositories import SessionRepository, QuestionBankRepository
from phase4.models import KnowledgeInitializationSession, SelfAssessmentStatus
from phase4.integration.phase3_adapter import Phase3Adapter
from phase3.question_bank.models import QuestionBank, QuestionBankItem, QuestionType
from phase5.validation import LearnerStateValidator, IdempotencyTracker, PlanningValidator
from backend.services.learner_service import LearnerService
from backend.services.knowledge_service import KnowledgeService


class LearningService:
    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        question_bank_repo: Optional[QuestionBankRepository] = None,
        learner_service: Optional[LearnerService] = None,
        knowledge_service: Optional[KnowledgeService] = None,
    ):
        self.session_repo = session_repo or SessionRepository()
        self.bank_repo = question_bank_repo or QuestionBankRepository()
        self.learner_service = learner_service or LearnerService()
        self.knowledge_service = knowledge_service or KnowledgeService()

        self.adapter = Phase3Adapter()
        self.idempotency_tracker = IdempotencyTracker()
        self.learner_state_validator = LearnerStateValidator(idempotency_tracker=self.idempotency_tracker)
        self.planning_validator = PlanningValidator()

    def _generate_concept_question(self, subject_id: str, concept_id: str) -> QuestionBankItem:
        c_name = concept_id.replace("_", " ").title()
        s_name = subject_id.replace("_", " ").title()
        c_desc = ""
        q_id = f"q_{concept_id}_1"

        try:
            ctx = self.knowledge_service.get_learning_context(subject_id)
            if ctx and concept_id in ctx.concepts:
                c_view = ctx.concepts[concept_id]
                c_name = c_view.canonical_name or c_name
                c_desc = c_view.description or ""
        except Exception:
            pass

        # 1. PRIMARY: Dynamic Groq LLM generation for any subject or uploaded PDF
        prompt = (
            f"You are an expert university professor creating an authentic diagnostic multiple-choice question.\n"
            f"SUBJECT: {s_name}\n"
            f"CONCEPT: {c_name}\n"
            + (f"CONCEPT DEFINITION: {c_desc}\n" if c_desc else "")
            + f"RULES:\n"
            f"1. Directly test a concrete, fundamental mechanism or property of '{c_name}' in '{s_name}'.\n"
            f"2. Provide 4 concrete, technically sound options directly using the specific terminology of '{c_name}'. Exactly ONE option must be correct.\n"
            f"3. The 3 wrong options must be realistic, plausible student misconceptions or common confusion points regarding '{c_name}'.\n"
            f"4. NEVER use generic boilerplate or filler phrases. All 4 options must be substantive statements specifically discussing '{c_name}'.\n"
            f"5. Use standard ASCII characters for equations and symbols.\n"
        )

        schema = {
            "question_text": "string (concrete question testing specific technical property)",
            "options": ["string (option 1)", "string (option 2)", "string (option 3)", "string (option 4)"],
            "correct_answer": "string (exact match of the correct option)",
            "explanation": "string (detailed explanation addressing why the correct answer is right and why the distractors are wrong)"
        }

        try:
            res = self.adapter.llm_adapter.generate_json(prompt, schema)
            q_text = res.get("question_text", "").strip()
            opts = res.get("options", [])
            corr = res.get("correct_answer", "").strip()
            expl = res.get("explanation", "").strip()

            is_generic = any(
                phrase in (opt or "").lower()
                for opt in opts
                for phrase in [
                    "decorative element",
                    "configuration setting",
                    "foundational mathematical or analytical",
                    "foundational mathematical or theoretical",
                    "localized formulation",
                    "historical artifact",
                    "string (option"
                ]
            )
            if q_text and len(opts) >= 4 and not is_generic:
                if corr not in opts:
                    clean_corr = corr.strip().rstrip(".)").upper()
                    if clean_corr in ["A", "B", "C", "D"] and len(opts) >= 4:
                        idx = ["A", "B", "C", "D"].index(clean_corr)
                        corr = opts[idx]
                    else:
                        matched = next((o for o in opts if clean_corr and clean_corr in o.upper()[:4]), None)
                        if matched:
                            corr = matched
                        else:
                            opts[0] = corr
                return QuestionBankItem(
                    question_id=q_id,
                    concept_ids=[concept_id],
                    question_type=QuestionType.MCQ,
                    question_text=q_text,
                    options=opts[:4],
                    correct_answer=corr or opts[0],
                    explanation=expl or f"{c_name} is a key concept within {s_name}.",
                    allow_dont_know_option=True,
                )
        except Exception:
            pass

        # 2. SECONDARY: Curated authentic domain questions for standard foundational subjects
        curated = {
            "vectors": {
                "question_text": "Which statement correctly distinguishes a mathematical vector from a scalar in linear algebra and machine learning?",
                "options": [
                    "A vector possesses both magnitude and direction in coordinate space, whereas a scalar has magnitude only.",
                    "A vector only has magnitude along the horizontal x-axis, whereas a scalar has orientation in multiple dimensions.",
                    "A vector represents a matrix of derivatives, while a scalar represents a matrix determinant.",
                    "A vector can only take discrete integer coordinates, whereas a scalar is always continuous."
                ],
                "correct_answer": "A vector possesses both magnitude and direction in coordinate space, whereas a scalar has magnitude only.",
                "explanation": "Vectors encode both directional orientation and magnitude across n dimensions, whereas scalars are single real numbers."
            },
            "matrices": {
                "question_text": "What is the primary geometric effect of multiplying an input vector by a square matrix in linear algebra?",
                "options": [
                    "It applies a linear transformation such as rotation, reflection, or scaling to the vector.",
                    "It always projects the vector onto a strictly lower-dimensional subspace.",
                    "It calculates the scalar Euclidean distance between the vector and the origin.",
                    "It converts the vector elements into a set of probability distributions."
                ],
                "correct_answer": "It applies a linear transformation such as rotation, reflection, or scaling to the vector.",
                "explanation": "Matrix-vector multiplication performs linear transformations in coordinate space."
            },
            "gradient_descent": {
                "question_text": "In gradient descent optimization, why is parameter updating performed in the opposite direction of the gradient vector?",
                "options": [
                    "The gradient vector points in the direction of steepest ascent, so moving in the negative direction minimizes the loss function.",
                    "Moving opposite to the gradient guarantees finding the global minimum regardless of loss surface non-convexity.",
                    "The gradient magnitude becomes zero only when moving against the vector trajectory.",
                    "The negative gradient vector directly inverts the Hessian matrix without computational overhead."
                ],
                "correct_answer": "The gradient vector points in the direction of steepest ascent, so moving in the negative direction minimizes the loss function.",
                "explanation": "The gradient points in the direction of steepest increase; stepping in the opposite direction descends the loss surface."
            },
            "linear_algebra": {
                "question_text": "Which dimensional condition is required for the matrix product AB of two matrices A and B to be defined?",
                "options": [
                    "The number of columns in matrix A must equal the number of rows in matrix B.",
                    "Both matrix A and matrix B must have identical square dimensions.",
                    "The determinants of both matrix A and matrix B must be non-zero.",
                    "The rows of matrix A must equal the columns of matrix B."
                ],
                "correct_answer": "The number of columns in matrix A must equal the number of rows in matrix B.",
                "explanation": "Matrix multiplication requires the inner dimensions to match: (m x k) multiplied by (k x n) yields (m x n)."
            },
            "linear_regression": {
                "question_text": "What mathematical criterion does Ordinary Least Squares (OLS) optimize when fitting a linear regression model?",
                "options": [
                    "Minimizing the sum of squared residuals between observed targets and model predictions.",
                    "Maximizing the margin of separation between positive and negative target values.",
                    "Minimizing the absolute difference between input feature variances.",
                    "Maximizing the entropy of the predicted response variable distribution."
                ],
                "correct_answer": "Minimizing the sum of squared residuals between observed targets and model predictions.",
                "explanation": "Linear regression minimizes the residual sum of squares (RSS) between true and predicted targets."
            },
            "logistic_regression": {
                "question_text": "Why is the sigmoid (logistic) function utilized in binary logistic regression rather than linear regression?",
                "options": [
                    "It maps continuous linear combinations of features into bounded probabilities between 0 and 1.",
                    "It ensures that decision boundaries are always non-linear circles or ellipses.",
                    "It eliminates the need for computing parameter gradients during training.",
                    "It penalizes large feature weights by automatically applying L2 regularization."
                ],
                "correct_answer": "It maps continuous linear combinations of features into bounded probabilities between 0 and 1.",
                "explanation": "The sigmoid function sigma(z) = 1 / (1 + e^-z) squashes linear outputs into the range (0, 1) for probability interpretation."
            },
            "loss_functions": {
                "question_text": "Why is Cross-Entropy loss preferred over Mean Squared Error (MSE) for classification with softmax output layers?",
                "options": [
                    "Cross-entropy penalizes confident incorrect predictions with large gradients, avoiding vanishing gradients.",
                    "Cross-entropy always yields an integer score directly indicating the predicted class index.",
                    "Mean Squared Error cannot be mathematically computed for probability vectors.",
                    "Cross-entropy guarantees that all model weights remain strictly positive."
                ],
                "correct_answer": "Cross-entropy penalizes confident incorrect predictions with large gradients, avoiding vanishing gradients.",
                "explanation": "Cross-entropy provides steeper gradient signals when predictions strongly disagree with true class labels."
            },
            "neural_networks": {
                "question_text": "What critical capability do non-linear activation functions (like ReLU) provide to multi-layer neural networks?",
                "options": [
                    "They allow deep networks to approximate complex non-linear functions instead of collapsing into a single linear map.",
                    "They ensure that the number of hidden layer neurons exactly equals the number of input features.",
                    "They prevent any weight values from ever becoming negative during backpropagation.",
                    "They convert feedforward networks into recurrent memory structures automatically."
                ],
                "correct_answer": "They allow deep networks to approximate complex non-linear functions instead of collapsing into a single linear map.",
                "explanation": "Without non-linear activations, composing multiple linear layers mathematically reduces to a single linear transformation."
            },
            "backpropagation": {
                "question_text": "How does backpropagation compute the partial derivatives of the loss with respect to weights in early layers?",
                "options": [
                    "By applying the calculus Chain Rule backwards from output layer to input layer, reusing intermediate gradients.",
                    "By inverting the weight matrix of each layer using numerical Gaussian elimination.",
                    "By recalculating all forward activations from scratch for every individual parameter.",
                    "By computing random perturbations of each weight and measuring empirical output changes."
                ],
                "correct_answer": "By applying the calculus Chain Rule backwards from output layer to input layer, reusing intermediate gradients.",
                "explanation": "Backpropagation computes errors via the Chain Rule from output to input, caching activation derivatives for efficiency."
            },
            "regularization": {
                "question_text": "What is a primary distinction between L1 (Lasso) and L2 (Ridge) regularization penalties?",
                "options": [
                    "L1 regularization encourages exact parameter sparsity (zeros), whereas L2 shrinks weights smoothly towards zero.",
                    "L2 regularization eliminates features completely, while L1 only scales feature coefficients.",
                    "L1 regularization can only be used with decision trees, while L2 is reserved for neural networks.",
                    "L2 regularization penalizes the absolute value of weights, while L1 penalizes squared values."
                ],
                "correct_answer": "L1 regularization encourages exact parameter sparsity (zeros), whereas L2 shrinks weights smoothly towards zero.",
                "explanation": "L1 has non-differentiable corners at zero leading to sparse feature selection; L2 shrinks weights proportionally."
            },
            "overfitting": {
                "question_text": "Which symptom is a classic hallmark of an overfitted machine learning model?",
                "options": [
                    "Very low error on the training dataset but significantly higher error on unseen validation data.",
                    "High error on both the training set and the validation set (high bias).",
                    "Model prediction time increasing exponentially with dataset size.",
                    "Weights that fail to update despite repeated gradient descent iterations."
                ],
                "correct_answer": "Very low error on the training dataset but significantly higher error on unseen validation data.",
                "explanation": "Overfitting occurs when a high-variance model memorizes training noise instead of learning underlying generalizable patterns."
            },
            "validation": {
                "question_text": "What is the primary danger of using test set evaluation performance to guide hyperparameter selection?",
                "options": [
                    "Data leakage occurs, causing overoptimistic test estimates that fail to generalize to future data.",
                    "The training loss becomes mathematically undefined due to duplicate record counting.",
                    "Cross-validation folds become impossible to partition without label permutation.",
                    "Gradient descent steps reverse direction whenever validation metrics are observed."
                ],
                "correct_answer": "Data leakage occurs, causing overoptimistic test estimates that fail to generalize to future data.",
                "explanation": "Tuning on test data leaks test information into model design, destroying the integrity of unbiased generalization evaluation."
            },
            "limits_intro": {
                "question_text": "What does it mean mathematically to state that the limit of f(x) as x approaches c is L?",
                "options": [
                    "Values of f(x) can be made arbitrarily close to L by taking x sufficiently close to c, without requiring f(c) = L.",
                    "The function must be explicitly defined and continuous at x = c with f(c) = L.",
                    "The derivative of f(x) evaluated at c must be equal to L.",
                    "The value of f(x) must oscillate symmetrically around L on either side of c."
                ],
                "correct_answer": "Values of f(x) can be made arbitrarily close to L by taking x sufficiently close to c, without requiring f(c) = L.",
                "explanation": "A limit describes the value a function approaches near a point, irrespective of whether the function is defined at that point."
            },
            "continuity": {
                "question_text": "Which three conditions must be satisfied for a function f(x) to be continuous at a point x = c?",
                "options": [
                    "f(c) is defined, the limit of f(x) as x -> c exists, and the limit equals f(c).",
                    "f'(c) exists, f''(c) exists, and f(c) is non-zero.",
                    "f(x) is strictly increasing on an open interval containing c.",
                    "The left-hand limit equals the derivative evaluated at c."
                ],
                "correct_answer": "f(c) is defined, the limit of f(x) as x -> c exists, and the limit equals f(c).",
                "explanation": "Continuity requires that the point is in the domain, the two-sided limit exists, and the limit matches the actual function value."
            },
            "derivatives_def": {
                "question_text": "According to the formal limit definition, what does the derivative f'(x) represent?",
                "options": [
                    "The limit of [f(x+h) - f(x)] / h as h approaches 0, representing instantaneous rate of change.",
                    "The average rate of change calculated over a fixed finite interval [x, x+1].",
                    "The total accumulated area under the curve f(t) between t = 0 and t = x.",
                    "The reciprocal of the secant slope evaluated at x = 0."
                ],
                "correct_answer": "The limit of [f(x+h) - f(x)] / h as h approaches 0, representing instantaneous rate of change.",
                "explanation": "The derivative is defined as the limit of the difference quotient as the step size h approaches zero."
            },
            "chain_rule": {
                "question_text": "How does the Chain Rule differentiate a composite function F(x) = f(g(x))?",
                "options": [
                    "F'(x) = f'(g(x)) * g'(x) (derivative of outer function evaluated at inner, times derivative of inner).",
                    "F'(x) = f'(x) * g'(x) (product of the individual derivatives).",
                    "F'(x) = f'(g'(x)) (outer derivative evaluated at inner derivative).",
                    "F'(x) = [f'(x) * g(x) - f(x) * g'(x)] / [g(x)]^2."
                ],
                "correct_answer": "F'(x) = f'(g(x)) * g'(x) (derivative of outer function evaluated at inner, times derivative of inner).",
                "explanation": "The Chain Rule states that d/dx[f(g(x))] = f'(g(x)) * g'(x)."
            },
            "power_rule": {
                "question_text": "According to the Power Rule of differentiation, what is d/dx [x^n] for any constant exponent n?",
                "options": [
                    "n * x^(n - 1)",
                    "x^(n + 1) / (n + 1)",
                    "n * x^n",
                    "(n - 1) * x^(n - 2)"
                ],
                "correct_answer": "n * x^(n - 1)",
                "explanation": "The Power Rule states d/dx[x^n] = n * x^(n-1)."
            },
            "product_rule": {
                "question_text": "What is the correct differentiation formula for the product of two functions d/dx [u(x) * v(x)]?",
                "options": [
                    "u'(x) * v(x) + u(x) * v'(x)",
                    "u'(x) * v'(x)",
                    "u'(x) * v(x) - u(x) * v'(x)",
                    "[u'(x) * v(x) + u(x) * v'(x)] / [v(x)]^2"
                ],
                "correct_answer": "u'(x) * v(x) + u(x) * v'(x)",
                "explanation": "The Product Rule states that (uv)' = u'v + uv'."
            },
            "implicit_diff": {
                "question_text": "When applying implicit differentiation to an equation containing y^2 with respect to x, what is d/dx [y^2]?",
                "options": [
                    "2y * (dy/dx)",
                    "2y",
                    "2x * (dy/dx)",
                    "y^2 * (dy/dx)"
                ],
                "correct_answer": "2y * (dy/dx)",
                "explanation": "Because y is an implicit function of x, applying the chain rule yields d/dx[y^2] = 2y * (dy/dx)."
            },
            "related_rates": {
                "question_text": "In related rates problems, what mathematical tool connects rates of change of geometric variables with respect to time t?",
                "options": [
                    "The Chain Rule, differentiating an underlying geometric relationship implicitly with respect to t.",
                    "The Fundamental Theorem of Calculus, integrating rates over a fixed time interval.",
                    "L'Hopital's Rule, evaluating indeterminate quotient forms as time approaches infinity.",
                    "Taylor series expansions truncated to second-order terms."
                ],
                "correct_answer": "The Chain Rule, differentiating an underlying geometric relationship implicitly with respect to t.",
                "explanation": "Related rates differentiate geometric constraints (e.g. Pythagorean theorem, volume) with respect to time using the Chain Rule."
            },
            "extrema": {
                "question_text": "At an interior point x = c on an open interval, what is a necessary condition for f(c) to be a local extremum of a differentiable function f?",
                "options": [
                    "f'(c) must equal 0 (or be undefined), establishing c as a critical point.",
                    "f''(c) must be strictly equal to 0.",
                    "The function value f(c) must equal the global average of the function.",
                    "The left-hand derivative must be strictly greater than the right-hand derivative."
                ],
                "correct_answer": "f'(c) must equal 0 (or be undefined), establishing c as a critical point.",
                "explanation": "Fermat's Theorem on Stationary Points establishes that if f has a local extremum at c and is differentiable, f'(c) = 0."
            },
            "mean_value_thm": {
                "question_text": "What does the Mean Value Theorem guarantee for a function f continuous on [a, b] and differentiable on (a, b)?",
                "options": [
                    "There exists at least one point c in (a, b) where f'(c) = [f(b) - f(a)] / (b - a).",
                    "The function must achieve a value of 0 at some point within the interval.",
                    "The maximum value of the function equals the average of f(a) and f(b).",
                    "The second derivative f''(x) must remain strictly positive across [a, b]."
                ],
                "correct_answer": "There exists at least one point c in (a, b) where f'(c) = [f(b) - f(a)] / (b - a).",
                "explanation": "The Mean Value Theorem proves the existence of an interior point where instantaneous rate equals average rate."
            },
            "integrals_def": {
                "question_text": "What does the definite integral of f(x) from a to b represent geometrically when f(x) takes both positive and negative values?",
                "options": [
                    "The net signed area between the graph of f(x) and the x-axis (areas above x-axis minus areas below).",
                    "The total perimeter of the region bounded by f(x) and the vertical lines x = a and x = b.",
                    "The instantaneous slope of the tangent line evaluated at the midpoint (a + b) / 2.",
                    "The maximum Euclidean distance from any point on f(x) to the origin."
                ],
                "correct_answer": "The net signed area between the graph of f(x) and the x-axis (areas above x-axis minus areas below).",
                "explanation": "Riemann integration computes net signed area, where regions below the horizontal axis subtract from the total."
            },
            "ftc": {
                "question_text": "According to Part 1 of the Fundamental Theorem of Calculus, if g(x) = int_a^x f(t) dt where f is continuous, what is g'(x)?",
                "options": [
                    "f(x)",
                    "f'(x)",
                    "f(x) - f(a)",
                    "f'(x) - f'(a)"
                ],
                "correct_answer": "f(x)",
                "explanation": "The Fundamental Theorem establishes that differentiation and definite integration with a variable upper limit are inverse operations: d/dx[int_a^x f(t) dt] = f(x)."
            }
        }

        if concept_id.lower() in curated:
            item = curated[concept_id.lower()]
            return QuestionBankItem(
                question_id=q_id,
                concept_ids=[concept_id],
                question_type=QuestionType.MCQ,
                question_text=item["question_text"],
                options=item["options"],
                correct_answer=item["correct_answer"],
                explanation=item["explanation"],
                allow_dont_know_option=True,
            )

        # 3. Dynamic grounded fallback for any arbitrary new concept
        c_def_clean = c_desc or f"Core pedagogical concept defining {c_name} in {s_name}."
        return QuestionBankItem(
            question_id=q_id,
            concept_ids=[concept_id],
            question_type=QuestionType.MCQ,
            question_text=f"Which statement accurately reflects the definition and core mechanism of {c_name} in {s_name}?",
            options=[
                c_def_clean,
                f"{c_name} operates in the inverse manner by counteracting changes in {s_name}.",
                f"{c_name} is an unconstrained heuristic applied only when {s_name} data is missing.",
                f"{c_name} functions as an auxiliary index without direct theoretical importance in {s_name}."
            ],
            correct_answer=c_def_clean,
            explanation=f"{c_name}: {c_def_clean}",
            allow_dont_know_option=True,
        )

    def get_or_create_question_bank(self, subject_id: str, concept_ids: List[str]) -> QuestionBank:
        bank = self.bank_repo.load_bank(subject_id)
        if not bank:
            bank = QuestionBank(
                document_id=subject_id,
                chapter_id="ch_all",
                questions={},
            )

        updated = False
        for cid in concept_ids:
            existing_q = next((q for q in bank.questions.values() if cid in q.concept_ids), None)
            is_dummy = (
                existing_q is None
                or any(
                    phrase in (opt or "").lower()
                    for opt in (existing_q.options or [])
                    for phrase in [
                        "decorative element",
                        "configuration setting",
                        "foundational mathematical or analytical",
                        "foundational mathematical or theoretical",
                        "localized formulation",
                        "historical artifact"
                    ]
                )
            )
            if is_dummy:
                new_q = self._generate_concept_question(subject_id, cid)
                bank.questions[new_q.question_id] = new_q
                updated = True

        if updated or not self.bank_repo.load_bank(subject_id):
            self.bank_repo.save_bank(bank)
        return bank

    def submit_self_assessment(
        self,
        learner_id: str,
        subject_id: str,
        selections: Dict[str, SelfAssessmentStatus],
        all_concept_ids: List[str],
    ) -> KnowledgeInitializationSession:
        val_res = self.planning_validator.validate_self_assessment(selections, all_concept_ids)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        session = self.adapter.self_assessment_handler.create_session(
            learner_id=learner_id,
            subject_id=subject_id,
            selections=selections,
            all_subject_concept_ids=all_concept_ids,
        )
        self.session_repo.save_session(session)
        # Ensure learner state exists
        self.learner_service.get_or_create_learner_state(learner_id, all_concept_ids)
        # Pre-populate question bank for all concepts of this subject
        self.get_or_create_question_bank(subject_id, all_concept_ids)
        return session

    def start_diagnostic(self, session_id: str) -> Dict[str, Any]:
        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")

        bank = self.get_or_create_question_bank(session.subject_id, session.know_concept_ids)
        questions = self.adapter.diagnostic_orchestrator.create_diagnostic_quiz(session, bank)

        val_res = self.planning_validator.validate_diagnostic_quiz_creation(session, questions)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        dumped_questions = []
        for q in questions:
            q_dict = q.model_dump(mode="json")
            q_dict["item_id"] = q_dict.get("question_id", "")
            q_dict["prompt"] = q_dict.get("question_text", "")
            dumped_questions.append(q_dict)

        self.session_repo.save_session(session)
        return {
            "session_id": session.session_id,
            "know_concepts": session.know_concept_ids,
            "question_count": len(questions),
            "questions": dumped_questions,
        }

    def submit_diagnostic(self, session_id: str, responses: Dict[str, float]) -> Dict[str, Any]:
        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")

        all_concepts = session.know_concept_ids + session.dont_know_concept_ids + session.unanswered_concept_ids
        learner_state = self.learner_service.get_or_create_learner_state(session.learner_id, all_concepts)
        bank = self.get_or_create_question_bank(session.subject_id, session.know_concept_ids)

        updated_masteries = self.adapter.diagnostic_orchestrator.submit_diagnostic_responses(
            init_session=session,
            learner_state=learner_state,
            question_responses=responses,
            question_bank=bank,
        )

        self.session_repo.save_session(session)
        self.learner_service.save_learner_state(learner_state)

        return {
            "session_id": session.session_id,
            "diagnostic_completed": session.diagnostic_completed,
            "diagnostic_score": session.diagnostic_score,
            "updated_masteries": updated_masteries,
        }

    def process_activity_response(
        self,
        learner_id: str,
        subject_id: str,
        concept_ids: List[str],
        correctness: float,
        all_subject_concept_ids: List[str],
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        learner_state = self.learner_service.get_or_create_learner_state(learner_id, all_subject_concept_ids)
        learning_context = self.knowledge_service.get_learning_context(subject_id, all_subject_concept_ids)

        val_res = self.learner_state_validator.validate_response_submission(
            learner_id=learner_id,
            concept_ids=concept_ids,
            correctness=correctness,
            request_id=request_id,
            valid_subject_concepts=set(all_subject_concept_ids),
        )
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        if val_res.metadata.get("duplicate_submission", False):
            path = self.adapter.path_generator.generate_path(learning_context, learner_state, all_subject_concept_ids)
            next_target = self.adapter.target_selector.select_next_target(path, learner_state, learning_context)
            return {
                "duplicate_submission": True,
                "updated_masteries": {
                    cid: learner_state.concept_states[cid].mastery_probability
                    for cid in concept_ids if cid in learner_state.concept_states
                },
                "path": path.model_dump(mode="json"),
                "next_target": next_target.model_dump(mode="json") if next_target else None,
            }

        updated_masteries, path, next_target = self.adapter.handle_activity_response_and_replan(
            learner_state=learner_state,
            learning_context=learning_context,
            subject_concept_ids=all_subject_concept_ids,
            concept_ids=concept_ids,
            correctness=correctness,
        )

        self.learner_service.save_learner_state(learner_state)
        if request_id:
            self.idempotency_tracker.mark_processed(request_id)

        return {
            "duplicate_submission": False,
            "updated_masteries": updated_masteries,
            "path": path.model_dump(mode="json"),
            "next_target": next_target.model_dump(mode="json") if next_target else None,
        }

    def get_concept_question(self, subject_id: str, concept_id: str) -> Dict[str, Any]:
        """
        Retrieves or generates an authentic, domain-specific multiple-choice question for a concept.
        """
        bank = self.get_or_create_question_bank(subject_id, [concept_id])
        q = next((item for item in bank.questions.values() if concept_id in item.concept_ids), None)
        if not q:
            q = self._generate_concept_question(subject_id, concept_id)
            bank.questions[q.question_id] = q
            self.bank_repo.save_bank(bank)

        return {
            "question_id": q.question_id,
            "concept_id": concept_id,
            "question_text": q.question_text,
            "options": q.options,
            "correct_answer": q.correct_answer,
            "explanation": q.explanation,
        }

    def get_concept_learning_content(self, subject_id: str, concept_id: str) -> Dict[str, Any]:
        """
        Retrieves or generates comprehensive pedagogical learning content for a concept,
        including theoretical overview, mental model/intuition, key principles, step-by-step worked example,
        common pitfalls, and key takeaway.
        """
        cache_key = f"{subject_id}::{concept_id}"
        if not hasattr(self, "_content_cache"):
            self._content_cache = {}
        if cache_key in self._content_cache:
            return self._content_cache[cache_key]

        c_name = concept_id.replace("_", " ").title()
        s_name = subject_id.replace("_", " ").title()
        c_desc = ""

        try:
            ctx = self.knowledge_service.get_learning_context(subject_id)
            if ctx and concept_id in ctx.concepts:
                c_view = ctx.concepts[concept_id]
                c_name = c_view.canonical_name or c_name
                c_desc = c_view.description or ""
        except Exception:
            pass

        prompt = (
            f"You are an elite university educator preparing comprehensive pedagogical learning content for a student.\n"
            f"SUBJECT: {s_name}\n"
            f"CONCEPT: {c_name}\n"
            + (f"CONCEPT DEFINITION: {c_desc}\n" if c_desc else "")
            + f"RULES:\n"
            f"1. Provide an in-depth, intuitive, and technically rigorous educational lesson on this concept.\n"
            f"2. Structure into:\n"
            f"   - overview: clear 2-3 paragraph intuitive and technical explanation\n"
            f"   - intuition: the underlying 'why' and mental model (real-world analogy or visual model)\n"
            f"   - key_principles: list of 3-5 core rules, properties, or formulas\n"
            f"   - worked_example: step-by-step solved problem or practical case study demonstrating the concept\n"
            f"   - common_misconceptions: 2-3 specific pitfalls and traps students often fall into\n"
            f"   - key_takeaway: one crisp rule-of-thumb sentence\n"
            f"3. Use standard ASCII characters for equations and symbols.\n"
        )

        schema = {
            "concept_name": "string",
            "overview": "string",
            "intuition": "string",
            "key_principles": ["string"],
            "worked_example": {
                "problem": "string",
                "steps": ["string"],
                "solution": "string"
            },
            "common_misconceptions": ["string"],
            "key_takeaway": "string"
        }

        try:
            res = self.adapter.llm_adapter.generate_json(prompt, schema)
            if res and res.get("overview"):
                result = {
                    "concept_id": concept_id,
                    "concept_name": res.get("concept_name") or c_name,
                    "subject_id": subject_id,
                    "overview": res.get("overview", ""),
                    "intuition": res.get("intuition", ""),
                    "key_principles": res.get("key_principles", []),
                    "worked_example": res.get("worked_example", {
                        "problem": f"Apply {c_name} to a standard scenario.",
                        "steps": ["Identify relevant inputs and boundary conditions.", "Execute fundamental transformation."],
                        "solution": f"Verified result according to {c_name} principles."
                    }),
                    "common_misconceptions": res.get("common_misconceptions", []),
                    "key_takeaway": res.get("key_takeaway", f"Mastery of {c_name} requires careful verification of its core assumptions.")
                }
                self._content_cache[cache_key] = result
                return result
        except Exception as e:
            import logging
            logging.getLogger("LearningService").warning(f"Error generating learning content for {concept_id}: {e}")

        # Fallback learning content
        fallback = {
            "concept_id": concept_id,
            "concept_name": c_name,
            "subject_id": subject_id,
            "overview": c_desc or f"{c_name} represents a foundational pillar within {s_name}. Understanding its principles enables rigorous problem solving and connects prerequisite theory to practical applications.",
            "intuition": f"Think of {c_name} as a structured mechanism that transforms incoming mathematical or conceptual representations into reliable inferences.",
            "key_principles": [
                f"Core invariant: {c_name} preserves foundational constraints across domain operations.",
                f"Composable structure: Interacts directly with prerequisite dependencies to build higher-order mastery.",
                f"Empirical verification: Solutions can be checked by substituting edge-case parameters."
            ],
            "worked_example": {
                "problem": f"Demonstrate the fundamental operation of {c_name}.",
                "steps": [
                    "Step 1: Identify the underlying problem domain and state initial assumptions.",
                    "Step 2: Apply the governing transformation rules of the concept.",
                    "Step 3: Simplify and verify consistency with prerequisite constraints."
                ],
                "solution": f"Consistent and verifiable result obtained under {c_name} formulation."
            },
            "common_misconceptions": [
                f"Assuming {c_name} applies without checking whether its prerequisite conditions are satisfied.",
                "Confusing intermediate algorithmic steps with final equilibrium states."
            ],
            "key_takeaway": f"Always verify the boundary conditions and prerequisite definitions before applying {c_name}."
        }
        self._content_cache[cache_key] = fallback
        return fallback

