import React, { useState } from 'react';
import type { Subject, Question, ConceptNode } from '../../api/client';
import { ApiClient } from '../../api/client';
import { CheckCircle2, XCircle, HelpCircle, ArrowRight, Sparkles, BookOpen, Brain, ShieldCheck, Upload, RefreshCw } from 'lucide-react';

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
  const [uploadingPdf, setUploadingPdf] = useState<boolean>(false);
  const [uploadStage, setUploadStage] = useState<string>('');
  const [uploadError, setUploadError] = useState<string | null>(null);

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

  // 1b. Handle PDF Upload as primary onboarding pathway
  const handleOnboardingPdfUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingPdf(true);
    setUploadError(null);

    try {
      const res = await ApiClient.uploadSource(file, (stage) => setUploadStage(stage));
      const cleanTitle = file.name.replace(/\.[^/.]+$/, '').replace(/_/g, ' ').toUpperCase();
      const newSub: Subject = {
        id: res.document_id,
        title: cleanTitle,
        concept_count: res.concept_count || 10,
        page_count: res.page_count || 1,
        has_ekr: true,
      };
      await handleSelectSubject(newSub);
    } catch (err: any) {
      console.error('Failed to process uploaded file', err);
      setUploadError(err.message || 'Failed to parse and synthesize Knowledge Atlas from document.');
    } finally {
      setUploadingPdf(false);
      setUploadStage('');
      e.target.value = '';
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
      if (!diagData.questions || diagData.questions.length === 0) {
        onCompleteOnboarding(selectedSubject.id, learnerId);
      } else {
        setDiagnosticQuestions(diagData.questions);
        setCurrentQuestionIdx(0);
        setDiagnosticAnswers({});
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
    const nextAnswers = { ...diagnosticAnswers, [item_id]: correctness };
    setDiagnosticAnswers(nextAnswers);
    if (currentQuestionIdx + 1 < diagnosticQuestions.length) {
      setCurrentQuestionIdx((prev) => prev + 1);
    } else {
      // Diagnostic complete - pass nextAnswers directly to avoid async state staleness
      handleSubmitDiagnostic(nextAnswers);
    }
  };

  const handleSubmitDiagnostic = async (finalAnswers?: Record<string, number>) => {
    setLoading(true);
    try {
      const payload = finalAnswers || diagnosticAnswers;
      await ApiClient.submitDiagnostic(sessionId, payload);
      if (selectedSubject) {
        onCompleteOnboarding(selectedSubject.id, learnerId);
      }
    } catch (err) {
      console.error('Failed to submit diagnostic', err);
      if (selectedSubject) {
        onCompleteOnboarding(selectedSubject.id, learnerId);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-slate-950 text-white">
      <div className="w-full max-w-3xl glass-panel p-8 rounded-3xl border border-slate-800 shadow-2xl relative overflow-hidden">
        {/* Step 1: Upload PDF or Select Subject */}
        {step === 'SELECT_SUBJECT' && (
          <div>
            <div className="text-center max-w-lg mx-auto mb-6">
              <span className="px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-500/50 text-cyan-300 text-xs font-mono font-bold tracking-widest uppercase">
                LEARNSENSE ONBOARDING
              </span>
              <h1 className="text-3xl font-extrabold text-white mt-3 tracking-tight">
                Upload Your Course Material
              </h1>
              <p className="text-xs text-slate-400 mt-2">
                Upload any PDF textbook, PowerPoint slides (.pptx), Word document (.docx), or diagrams (.png, .jpg) to automatically synthesize your personalized Knowledge Atlas.
              </p>
            </div>

            {/* Primary Action: Upload Course Material */}
            <div className="mb-6 p-6 rounded-3xl border-2 border-dashed border-cyan-500/50 bg-cyan-950/20 hover:bg-cyan-950/40 hover:border-cyan-400 transition-all text-center relative group">
              <input
                type="file"
                accept=".pdf,.pptx,.docx,.png,.jpg,.jpeg"
                id="onboarding-pdf-input"
                disabled={uploadingPdf}
                onChange={handleOnboardingPdfUpload}
                className="hidden"
              />
              <label
                htmlFor="onboarding-pdf-input"
                className="cursor-pointer flex flex-col items-center justify-center space-y-3"
              >
                <div className="w-14 h-14 rounded-2xl bg-cyan-500/20 border border-cyan-400/40 flex items-center justify-center text-cyan-300 group-hover:scale-110 transition-transform shadow-glow-cyan">
                  {uploadingPdf ? (
                    <RefreshCw className="w-7 h-7 animate-spin text-cyan-400" />
                  ) : (
                    <Upload className="w-7 h-7" />
                  )}
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">
                    {uploadingPdf ? 'Analyzing Material & Synthesizing Knowledge Atlas...' : 'Upload Course Material (PDF, PPTX, DOCX, IMG)'}
                  </h3>
                  <p className="text-xs text-slate-400 mt-1 max-w-md">
                    {uploadingPdf
                      ? uploadStage.startsWith('processing (')
                        ? `Ingesting PDF — ${uploadStage.replace('processing (', '').replace(')', '')} • Extracting chapters, concepts & question bank…`
                        : 'Extracting chapters, slide notes, prerequisite concepts, and generating curriculum question bank with Groq LLM...'
                      : 'Drop any PDF, PowerPoint slides (.pptx), Word doc (.docx), or diagram images (.png, .jpg) to dynamically construct an intelligent learning map.'}
                  </p>
                </div>
                {!uploadingPdf && (
                  <span className="py-2 px-5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center gap-2 shadow-glow-cyan transition-all mt-1">
                    <Upload className="w-3.5 h-3.5" />
                    <span>Select Document or Slides</span>
                  </span>
                )}
              </label>
            </div>

            {uploadError && (
              <div className="mb-6 p-3 rounded-xl bg-rose-950/80 border border-rose-500/50 text-xs text-rose-300 font-mono text-center">
                {uploadError}
              </div>
            )}

            {/* Secondary Action: Select existing subject */}
            <div className="flex items-center gap-4 my-6">
              <div className="h-px bg-slate-800 flex-1" />
              <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
                Or choose an existing subject
              </span>
              <div className="h-px bg-slate-800 flex-1" />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {subjects.map((s) => (
                <div
                  key={s.id}
                  onClick={() => handleSelectSubject(s)}
                  className="p-5 rounded-2xl border border-slate-800 bg-slate-900/60 hover:border-cyan-400/80 hover:bg-slate-900 cursor-pointer transition-all duration-300 group shadow-lg flex items-center justify-between"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-slate-950 border border-slate-800 text-cyan-400 group-hover:scale-110 transition-transform">
                      <BookOpen className="w-5 h-5" />
                    </div>
                    <div>
                      <h4 className="text-sm font-bold text-white group-hover:text-cyan-300 transition-colors">
                        {s.title}
                      </h4>
                      <div className="flex items-center gap-2 text-[11px] text-slate-400 mt-0.5 font-mono">
                        <span>{s.concept_count} Concepts</span>
                        <span>•</span>
                        <span>{s.page_count} Pages</span>
                      </div>
                    </div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-cyan-400 transition-colors" />
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

            {(() => {
              const knowCount = Object.values(selfAssessmentSelections).filter((v) => v === 'KNOW').length;
              return (
                <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between gap-4">
                  <div className="text-xs text-slate-400">
                    {knowCount > 0 ? (
                      <span>
                        <strong className="text-cyan-400 font-bold">{knowCount}</strong> {knowCount === 1 ? 'concept' : 'concepts'} selected for diagnostic quiz.
                      </span>
                    ) : (
                      <span>
                        No concepts marked as <strong className="text-slate-300">KNOW</strong>. Click below to begin with all concepts at baseline.
                      </span>
                    )}
                  </div>

                  <button
                    onClick={handleSubmitSelfAssessment}
                    disabled={loading}
                    className="py-3 px-6 rounded-2xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center gap-2 shadow-glow-cyan transition-all shrink-0 disabled:opacity-50"
                  >
                    <span>{knowCount > 0 ? `Start Diagnostic Quiz (${knowCount})` : 'Start Learning Path'}</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              );
            })()}
          </div>
        )}

        {/* Step 3: Diagnostic Assessment */}
        {step === 'DIAGNOSTIC' && (
          <div>
            {diagnosticQuestions.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-sm text-slate-400">No diagnostic questions found for the selected concepts.</p>
                <button
                  onClick={() => selectedSubject && onCompleteOnboarding(selectedSubject.id, learnerId)}
                  className="mt-4 py-2.5 px-5 rounded-xl bg-cyan-500 text-slate-950 font-bold text-xs"
                >
                  Continue to Learning Path
                </button>
              </div>
            ) : (() => {
              const q = diagnosticQuestions[currentQuestionIdx];
              if (!q) {
                return (
                  <div className="text-center py-12">
                    <p className="text-sm text-slate-400">Diagnostic completed.</p>
                    <button
                      onClick={() => handleSubmitDiagnostic()}
                      className="mt-4 py-2.5 px-5 rounded-xl bg-cyan-500 text-slate-950 font-bold text-xs"
                    >
                      Finish Diagnostic
                    </button>
                  </div>
                );
              }

              const qText = q.question_text || q.prompt || 'Assess your understanding of this concept:';
              const qId = q.question_id || q.item_id || `q_${currentQuestionIdx}`;
              const rawOptions = Array.isArray(q.options) && q.options.length > 0 ? q.options : [];


              const isDontKnowText = (text: string) => {
                const lower = text.toLowerCase();
                return lower.includes("don't know") || lower.includes("dont know") || lower.includes("unsure");
              };

              const hasDontKnowInOptions = rawOptions.some(isDontKnowText);

              const onOptionClick = (optText: string, optIdx: number) => {
                if (isDontKnowText(optText)) {
                  handleAnswerDiagnosticQuestion(qId, 0.0);
                  return;
                }
                let correctness = 0.0;
                if (q.correct_answer) {
                  correctness = optText.trim() === q.correct_answer.trim() ? 1.0 : 0.0;
                } else {
                  correctness = optIdx === 0 ? 1.0 : 0.0;
                }
                handleAnswerDiagnosticQuestion(qId, correctness);
              };

              return (
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

                  <div className="space-y-4">
                    <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
                      <p className="text-sm font-semibold text-slate-100 leading-relaxed">
                        {qText}
                      </p>
                    </div>

                    <div className="space-y-2">
                      {rawOptions.map((opt, optIdx) => (
                        <button
                          key={optIdx}
                          disabled={loading}
                          onClick={() => onOptionClick(opt, optIdx)}
                          className={`w-full p-3.5 rounded-xl border border-slate-800 bg-slate-900/50 hover:bg-slate-800 hover:border-cyan-400/60 text-left text-xs text-slate-200 transition-all font-sans flex items-center justify-between disabled:opacity-50 ${
                            isDontKnowText(opt) ? 'text-amber-300 hover:border-amber-400/60 bg-amber-950/20' : ''
                          }`}
                        >
                          <span>{opt}</span>
                          {isDontKnowText(opt) && <ShieldCheck className="w-4 h-4 text-amber-400 shrink-0" />}
                        </button>
                      ))}

                      {q.allow_dont_know_option && !hasDontKnowInOptions && (
                        <button
                          disabled={loading}
                          onClick={() => handleAnswerDiagnosticQuestion(qId, 0.0)}
                          className="w-full p-3.5 rounded-xl border border-amber-500/40 bg-amber-950/30 hover:bg-amber-900/50 text-left text-xs font-mono text-amber-200 transition-all flex items-center gap-2 disabled:opacity-50"
                        >
                          <ShieldCheck className="w-4 h-4 text-amber-400" />
                          <span>I don't know this yet</span>
                        </button>
                      )}
                    </div>
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
