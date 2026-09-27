import React, { useState } from 'react';
import type { Subject, Question, ConceptNode } from '../../api/client';
import { ApiClient } from '../../api/client';
import { CheckCircle2, XCircle, HelpCircle, ArrowRight, Sparkles, BookOpen, Brain, ShieldCheck } from 'lucide-react';

export interface OnboardingWorkflowProps {
  subjects: Subject[];
  onCompleteOnboarding: (subjectId: string, learnerId: string) => void;
}

export const OnboardingWorkflow: React.FC<OnboardingWorkflowProps> = ({
  subjects,
  onCompleteOnboarding,
}) => {
  const [step, setStep] = useState<'SELECT_SUBJECT' | 'SELF_ASSESSMENT' | 'DIAGNOSTIC' | 'COMPLETED'>('SELECT_SUBJECT');
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);
  const [learnerId] = useState<string>('student_alex');
  const [concepts, setConcepts] = useState<ConceptNode[]>([]);
  const [selfAssessmentSelections, setSelfAssessmentSelections] = useState<Record<string, string>>({});
  const [sessionId, setSessionId] = useState<string>('');
  const [diagnosticQuestions, setDiagnosticQuestions] = useState<Question[]>([]);
  const [diagnosticAnswers, setDiagnosticAnswers] = useState<Record<string, number>>({});
  const [currentQuestionIdx, setCurrentQuestionIdx] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);

  // 1. Select Subject
  const handleSelectSubject = async (sub: Subject) => {
    setSelectedSubject(sub);
    setLoading(true);
    try {
      const graph = await ApiClient.getSubjectGraph(sub.id, learnerId);
      setConcepts(graph.concepts);
      // Initialize self-assessment state as UNANSWERED
      const initMap: Record<string, string> = {};
      graph.concepts.forEach((c) => {
        initMap[c.concept_id] = 'UNANSWERED';
      });
      setSelfAssessmentSelections(initMap);
      setStep('SELF_ASSESSMENT');
    } catch (err) {
      console.error('Failed to load subject graph', err);
    } finally {
      setLoading(false);
    }
  };

  // 2. Submit Self Assessment
  const handleSubmitSelfAssessment = async () => {
    if (!selectedSubject) return;
    setLoading(true);
    try {
      const allConceptIds = concepts.map((c) => c.concept_id);
      const session = await ApiClient.submitSelfAssessment({
        learner_id: learnerId,
        subject_id: selectedSubject.id,
        selections: selfAssessmentSelections,
        all_subject_concept_ids: allConceptIds,
      });

      setSessionId(session.session_id);

      // Part 23 Rule: If zero KNOW concepts selected, DO NOT RUN DIAGNOSTIC. Bypass directly to foundational graph.
      const knowCount = Object.values(selfAssessmentSelections).filter((v) => v === 'KNOW').length;
      if (knowCount === 0) {
        onCompleteOnboarding(selectedSubject.id, learnerId);
        return;
      }

      // Fetch diagnostic quiz for KNOW concepts
      const diagData = await ApiClient.startDiagnostic(session.session_id);
      if (diagData.question_count === 0 || diagData.questions.length === 0) {
        onCompleteOnboarding(selectedSubject.id, learnerId);
      } else {
        setDiagnosticQuestions(diagData.questions);
        setStep('DIAGNOSTIC');
      }
    } catch (err) {
      console.error('Failed to submit self assessment', err);
    } finally {
      setLoading(false);
    }
  };

  // 3. Submit Diagnostic Answer
  const handleAnswerDiagnosticQuestion = (item_id: string, correctness: number) => {
    setDiagnosticAnswers((prev) => ({ ...prev, [item_id]: correctness }));
    if (currentQuestionIdx + 1 < diagnosticQuestions.length) {
      setCurrentQuestionIdx((prev) => prev + 1);
    } else {
      // Diagnostic complete
      handleSubmitDiagnostic();
    }
  };

  const handleSubmitDiagnostic = async () => {
    setLoading(true);
    try {
      await ApiClient.submitDiagnostic(sessionId, diagnosticAnswers);
      if (selectedSubject) {
        onCompleteOnboarding(selectedSubject.id, learnerId);
      }
    } catch (err) {
      console.error('Failed to submit diagnostic', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-slate-950 text-white">
      <div className="w-full max-w-3xl glass-panel p-8 rounded-3xl border border-slate-800 shadow-2xl relative overflow-hidden">
        {/* Step 1: Select Subject */}
        {step === 'SELECT_SUBJECT' && (
          <div>
            <div className="text-center max-w-lg mx-auto mb-8">
              <span className="px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-500/50 text-cyan-300 text-xs font-mono font-bold tracking-widest uppercase">
                WELCOME TO TAPROOT
              </span>
              <h1 className="text-3xl font-extrabold text-white mt-3 tracking-tight">
                Select Your Study Subject
              </h1>
              <p className="text-xs text-slate-400 mt-2">
                Choose a domain to initialize your personalized Knowledge Atlas and diagnostic assessment.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {subjects.map((s) => (
                <div
                  key={s.id}
                  onClick={() => handleSelectSubject(s)}
                  className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 hover:border-cyan-400/80 hover:bg-slate-900 cursor-pointer transition-all duration-300 group shadow-lg"
                >
                  <BookOpen className="w-8 h-8 text-cyan-400 group-hover:scale-110 transition-transform" />
                  <h3 className="text-base font-bold text-white mt-4 group-hover:text-cyan-300 transition-colors">
                    {s.title}
                  </h3>
                  <div className="flex items-center gap-3 text-xs text-slate-400 mt-2 font-mono">
                    <span>{s.concept_count} Concepts</span>
                    <span>•</span>
                    <span>{s.page_count} Pages</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 2: Self Assessment */}
        {step === 'SELF_ASSESSMENT' && selectedSubject && (
          <div>
            <div className="mb-6 pb-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <span className="text-[10px] font-mono tracking-widest text-cyan-400 font-bold uppercase">
                  STEP 2 OF 3 • CONCEPT INITIALIZATION
                </span>
                <h2 className="text-xl font-bold text-white mt-1">
                  Self-Assess Your Familiarity
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Mark concepts you already know. Only <strong className="text-cyan-300">KNOW</strong> concepts are diagnostically tested.
                </p>
              </div>
              <Sparkles className="w-6 h-6 text-cyan-400" />
            </div>

            <div className="max-h-96 overflow-y-auto space-y-3 pr-2">
              {concepts.map((c) => {
                const currentStatus = selfAssessmentSelections[c.concept_id] || 'UNANSWERED';
                return (
                  <div
                    key={c.concept_id}
                    className="p-4 rounded-2xl border border-slate-800 bg-slate-900/50 flex items-center justify-between gap-4"
                  >
                    <div>
                      <h4 className="text-sm font-bold text-white">{c.name}</h4>
                      <p className="text-xs text-slate-400 line-clamp-1 mt-0.5">{c.definition}</p>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() =>
                          setSelfAssessmentSelections((prev) => ({ ...prev, [c.concept_id]: 'KNOW' }))
                        }
                        className={`px-3 py-1.5 rounded-xl text-xs font-bold flex items-center gap-1 transition-all ${
                          currentStatus === 'KNOW'
                            ? 'bg-emerald-500 text-slate-950 shadow-glow-emerald'
                            : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>KNOW</span>
                      </button>

                      <button
                        onClick={() =>
                          setSelfAssessmentSelections((prev) => ({ ...prev, [c.concept_id]: 'DONT_KNOW' }))
                        }
                        className={`px-3 py-1.5 rounded-xl text-xs font-bold flex items-center gap-1 transition-all ${
                          currentStatus === 'DONT_KNOW'
                            ? 'bg-rose-500 text-slate-950 shadow-glow-rose'
                            : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        <XCircle className="w-3.5 h-3.5" />
                        <span>DON'T KNOW</span>
                      </button>

                      <button
                        onClick={() =>
                          setSelfAssessmentSelections((prev) => ({ ...prev, [c.concept_id]: 'UNANSWERED' }))
                        }
                        className={`px-3 py-1.5 rounded-xl text-xs font-bold flex items-center gap-1 transition-all ${
                          currentStatus === 'UNANSWERED'
                            ? 'bg-slate-700 text-white'
                            : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        <HelpCircle className="w-3.5 h-3.5" />
                        <span>UNSURE</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="mt-6 pt-4 border-t border-slate-800 flex justify-end">
              <button
                onClick={handleSubmitSelfAssessment}
                disabled={loading}
                className="py-3 px-6 rounded-2xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center gap-2 shadow-glow-cyan transition-all"
              >
                <span>Continue Diagnostic</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Diagnostic Assessment */}
        {step === 'DIAGNOSTIC' && diagnosticQuestions.length > 0 && (
          <div>
            <div className="mb-6 pb-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <span className="text-[10px] font-mono tracking-widest text-emerald-400 font-bold uppercase">
                  QUESTION {currentQuestionIdx + 1} OF {diagnosticQuestions.length}
                </span>
                <h2 className="text-xl font-bold text-white mt-1">
                  Diagnostic Knowledge Assessment
                </h2>
              </div>
              <Brain className="w-6 h-6 text-emerald-400" />
            </div>

            {(() => {
              const q = diagnosticQuestions[currentQuestionIdx];
              return (
                <div className="space-y-4">
                  <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
                    <p className="text-sm font-semibold text-slate-100 leading-relaxed">{q.prompt}</p>
                  </div>

                  <div className="space-y-2">
                    {q.options.map((opt, optIdx) => (
                      <button
                        key={optIdx}
                        onClick={() => handleAnswerDiagnosticQuestion(q.item_id, 1.0)}
                        className="w-full p-3.5 rounded-xl border border-slate-800 bg-slate-900/50 hover:bg-slate-800 hover:border-cyan-400/60 text-left text-xs text-slate-200 transition-all font-sans"
                      >
                        {opt}
                      </button>
                    ))}

                    {q.allow_dont_know_option && (
                      <button
                        onClick={() => handleAnswerDiagnosticQuestion(q.item_id, 0.0)}
                        className="w-full p-3.5 rounded-xl border border-amber-500/40 bg-amber-950/30 hover:bg-amber-900/50 text-left text-xs font-mono text-amber-200 transition-all flex items-center gap-2"
                      >
                        <ShieldCheck className="w-4 h-4 text-amber-400" />
                        <span>I don't know this yet</span>
                      </button>
                    )}
                  </div>
                </div>
              );
            })()}
          </div>
        )}
      </div>
    </div>
  );
};
