import React, { useEffect, useState } from 'react';
import type { Subject, Question, ConceptNode, TopicTerritory } from '../../api/client';
import { ApiClient } from '../../api/client';
import { CheckCircle2, XCircle, HelpCircle, ArrowRight, BookOpen, Brain, ShieldCheck, Upload, RefreshCw, Orbit } from 'lucide-react';

export interface OnboardingWorkflowProps {
  subjects: Subject[];
  onCompleteOnboarding: (subjectId: string, learnerId: string) => void;
  resumeInitSession?: {
    session_id: string;
    subject_id: string;
  } | null;
  // When set, skip subject selection and jump straight to self-assessment for
  // this subject (used when an already-onboarded learner adds new material).
  initialSubject?: Subject | null;
}

type Confidence = 'Low' | 'Medium' | 'High';

const CONFIDENCE_ORDER: Confidence[] = ['Low', 'Medium', 'High'];

function draftKey(learnerId: string, subjectId: string): string {
  return `learnsense.self_assessment_draft.${learnerId}.${subjectId}`;
}

export const OnboardingWorkflow: React.FC<OnboardingWorkflowProps> = ({
  subjects,
  onCompleteOnboarding,
  resumeInitSession,
  initialSubject,
}) => {
  const [step, setStep] = useState<'SELECT_SUBJECT' | 'SELF_ASSESSMENT' | 'DIAGNOSTIC' | 'COMPLETED'>('SELECT_SUBJECT');
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);
  const [learnerId] = useState<string>('student_alex');
  const [concepts, setConcepts] = useState<ConceptNode[]>([]);
  const [topics, setTopics] = useState<TopicTerritory[]>([]);
  const [selfAssessmentSelections, setSelfAssessmentSelections] = useState<Record<string, string>>({});
  const [confidenceSelections, setConfidenceSelections] = useState<Record<string, Confidence>>({});
  const [sessionId, setSessionId] = useState<string>('');
  const [diagnosticQuestions, setDiagnosticQuestions] = useState<Question[]>([]);
  const [diagnosticAnswers, setDiagnosticAnswers] = useState<Record<string, string>>({});
  const [currentQuestionIdx, setCurrentQuestionIdx] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [uploadingPdf, setUploadingPdf] = useState<boolean>(false);
  const [uploadStage, setUploadStage] = useState<string>('');
  const [uploadError, setUploadError] = useState<string | null>(null);

  const setLevel = (conceptId: string, level: string) => {
    setSelfAssessmentSelections((prev) => {
      const next = { ...prev, [conceptId]: level };
      persistDraft(selectedSubject?.id, next, confidenceSelections);
      return next;
    });
  };

  const setConfidence = (conceptId: string, confidence: Confidence) => {
    setConfidenceSelections((prev) => {
      const next = { ...prev, [conceptId]: confidence };
      persistDraft(selectedSubject?.id, selfAssessmentSelectionsRef.current, next);
      return next;
    });
  };

  // Ref mirror so persistDraft inside setConfidence sees latest levels.
  const selfAssessmentSelectionsRef = React.useRef(selfAssessmentSelections);
  React.useEffect(() => {
    selfAssessmentSelectionsRef.current = selfAssessmentSelections;
  }, [selfAssessmentSelections]);

  const persistDraft = (
    subjectId: string | undefined,
    levels: Record<string, string>,
    confidences: Record<string, Confidence>,
  ) => {
    if (!subjectId) return;
    try {
      localStorage.setItem(draftKey(learnerId, subjectId), JSON.stringify({ levels, confidences }));
    } catch {
      // Draft persistence is best-effort.
    }
  };

  const loadDraft = (subjectId: string): { levels: Record<string, string>; confidences: Record<string, Confidence> } | null => {
    try {
      const raw = localStorage.getItem(draftKey(learnerId, subjectId));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.levels === 'object') return parsed;
      return null;
    } catch {
      return null;
    }
  };

  const clearDraft = (subjectId: string) => {
    try {
      localStorage.removeItem(draftKey(learnerId, subjectId));
      localStorage.removeItem(`learnsense.diagnostic_session.${learnerId}.${subjectId}`);
    } catch {
      // best-effort
    }
  };

  // 1. Select Subject
  const handleSelectSubject = async (sub: Subject) => {
    setSelectedSubject(sub);
    setLoading(true);
    try {
      const graph = await ApiClient.getSubjectGraph(sub.id, learnerId);
      setConcepts(graph.concepts);
      setTopics(graph.topics || []);
      const draft = loadDraft(sub.id);
      const initMap: Record<string, string> = {};
      const initConf: Record<string, Confidence> = {};
      graph.concepts.forEach((c) => {
        initMap[c.concept_id] = draft?.levels?.[c.concept_id] || 'UNANSWERED';
        const dc = draft?.confidences?.[c.concept_id];
        initConf[c.concept_id] = dc === 'Low' || dc === 'Medium' || dc === 'High' ? dc : 'Medium';
      });
      setSelfAssessmentSelections(initMap);
      selfAssessmentSelectionsRef.current = initMap;
      setConfidenceSelections(initConf);
      setStep('SELF_ASSESSMENT');
    } catch (err) {
      console.error('Failed to load subject graph', err);
    } finally {
      setLoading(false);
    }
  };

  // 1b. Handle PDF/File Upload — ingestion states: uploading → processing →
  // extracting → ready for self-assessment. Self-assessment is only shown once
  // the concept graph exists; failures surface a clear error with retry.
  const handleOnboardingPdfUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingPdf(true);
    setUploadError(null);

    try {
      setUploadStage('uploading');
      const res = await ApiClient.uploadSource(file, (stage) => setUploadStage(stage));
      setUploadStage('extracting concepts');
      const cleanTitle = file.name.replace(/\.[^/.]+$/, '').replace(/_/g, ' ').toUpperCase();
      const newSub: Subject = {
        id: res.document_id,
        title: cleanTitle,
        concept_count: res.concept_count || 10,
        page_count: res.page_count || 1,
        has_ekr: true,
      };
      setUploadStage('preparing assessment');
      await handleSelectSubject(newSub);
      setUploadStage('ready for self-assessment');
    } catch (err: any) {
      console.error('Failed to process uploaded file', err);
      setUploadError(err.message || 'Ingestion failed. Check the file and try again.');
    } finally {
      setUploadingPdf(false);
      setUploadStage('');
      e.target.value = '';
    }
  };

  // Resume an interrupted diagnostic after browser refresh (Batch 13).
  useEffect(() => {
    if (!resumeInitSession) return;    let cancelled = false;
    const resume = async () => {
      setLoading(true);
      try {
        const sub: Subject = {
          id: resumeInitSession.subject_id,
          title: resumeInitSession.subject_id.replace(/_/g, ' ').toUpperCase(),
          concept_count: 0,
          page_count: 1,
          has_ekr: true,
        };
        setSelectedSubject(sub);
        try {
          const graph = await ApiClient.getSubjectGraph(sub.id, learnerId);
          if (!cancelled) {
            setConcepts(graph.concepts);
            setTopics(graph.topics || []);
          }
        } catch {
          // Graph load is best-effort during resume.
        }
        setSessionId(resumeInitSession.session_id);
        try {
          localStorage.setItem(
            `learnsense.diagnostic_session.${learnerId}.${sub.id}`,
            resumeInitSession.session_id,
          );
        } catch {
          // best-effort
        }
        const diagData = await ApiClient.startDiagnostic(resumeInitSession.session_id, learnerId);
        if (cancelled) return;
        if (!diagData.questions || diagData.questions.length === 0) {
          onCompleteOnboarding(sub.id, learnerId);
        } else {
          setDiagnosticQuestions(diagData.questions);
          setCurrentQuestionIdx(0);
          setDiagnosticAnswers({});
          setStep('DIAGNOSTIC');
        }
      } catch (err) {
        console.error('Failed to resume diagnostic', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    resume();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeInitSession?.session_id]);

  // Jump straight to self-assessment for a newly ingested subject when the
  // learner is already onboarded (calibration gate from the Sources view).
  const initialSubjectHandled = React.useRef<string | null>(null);
  useEffect(() => {
    if (!initialSubject || resumeInitSession) return;
    if (initialSubjectHandled.current === initialSubject.id) return;
    initialSubjectHandled.current = initialSubject.id;
    handleSelectSubject(initialSubject);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSubject?.id]);

  // 2. Submit Self Assessment — self-assessment + confidence is the initial
  // hypothesis only. The server stores it separately from BKT evidence and the
  // diagnostic below verifies it before any learning path is generated.
  const handleSubmitSelfAssessment = async () => {
    if (!selectedSubject) return;
    setLoading(true);
    try {
      const allConceptIds = concepts.map((c) => c.concept_id);
      const apiConfidences: Record<string, string> = {};
      allConceptIds.forEach((cid) => {
        const c = confidenceSelections[cid] || 'Medium';
        apiConfidences[cid] = c.toUpperCase();
      });
      const session = await ApiClient.submitSelfAssessment({
        learner_id: learnerId,
        subject_id: selectedSubject.id,
        selections: selfAssessmentSelections,
        all_subject_concept_ids: allConceptIds,
        confidences: apiConfidences,
      });

      setSessionId(session.session_id);
      try {
        localStorage.setItem(
          `learnsense.diagnostic_session.${learnerId}.${selectedSubject.id}`,
          session.session_id,
        );
      } catch {
        // best-effort
      }

      // Verification set = Strong claims + Unsure concepts. Confident Weak
      // (DONT_KNOW) needs no probing: its gap already drives the path.
      const verifyCount = Object.values(selfAssessmentSelections).filter(
        (v) => v === 'KNOW' || v === 'UNANSWERED',
      ).length;
      if (verifyCount === 0) {
        clearDraft(selectedSubject.id);
        onCompleteOnboarding(selectedSubject.id, learnerId);
        return;
      }

      const diagData = await ApiClient.startDiagnostic(session.session_id, learnerId);
      if (!diagData.questions || diagData.questions.length === 0) {
        clearDraft(selectedSubject.id);
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
  const handleAnswerDiagnosticQuestion = (item_id: string, selectedOption: string) => {
    const nextAnswers = { ...diagnosticAnswers, [item_id]: selectedOption };
    setDiagnosticAnswers(nextAnswers);
    if (currentQuestionIdx + 1 < diagnosticQuestions.length) {
      setCurrentQuestionIdx((prev) => prev + 1);
    } else {
      handleSubmitDiagnostic(nextAnswers);
    }
  };

  const handleSubmitDiagnostic = async (finalAnswers?: Record<string, string>) => {
    setLoading(true);
    try {
      const payload = finalAnswers || diagnosticAnswers;
      await ApiClient.submitDiagnosticRaw(sessionId, learnerId, payload);
      if (selectedSubject) {
        clearDraft(selectedSubject.id);
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

  const verifyCount = Object.values(selfAssessmentSelections).filter(
    (v) => v === 'KNOW' || v === 'UNANSWERED',
  ).length;

  // Group concepts under their extracted topics so the learner rates
  // knowledge topic by topic. Concepts without a topic fall under Other.
  const topicGroups: { key: string; title: string; concepts: ConceptNode[] }[] = (() => {
    if (topics.length === 0) {
      return [{ key: 'all', title: '', concepts }];
    }
    const byId = new Map(topics.map((t) => [t.id, t]));
    const grouped = new Map<string, ConceptNode[]>();
    const other: ConceptNode[] = [];
    concepts.forEach((c) => {
      const tid = c.topic_id || '';
      if (tid && byId.has(tid)) {
        const arr = grouped.get(tid) || [];
        arr.push(c);
        grouped.set(tid, arr);
      } else {
        other.push(c);
      }
    });
    const groups = topics
      .filter((t) => grouped.has(t.id))
      .map((t) => ({ key: t.id, title: t.name, concepts: grouped.get(t.id) || [] }));
    if (other.length > 0) {
      groups.push({ key: 'other', title: 'Other concepts', concepts: other });
    }
    return groups.length > 0 ? groups : [{ key: 'all', title: '', concepts }];
  })();

  const markTopic = (conceptIds: string[], level: string) => {
    setSelfAssessmentSelections((prev) => {
      const next = { ...prev };
      conceptIds.forEach((cid) => {
        next[cid] = level;
      });
      persistDraft(selectedSubject?.id, next, confidenceSelections);
      return next;
    });
  };

  return (
    <div className="min-h-screen universe-canvas flex items-center justify-center p-4 sm:p-8 text-white antialiased">
      <div className="w-full max-w-3xl universe-panel rounded-3xl p-6 sm:p-10 relative overflow-hidden shadow-[0_32px_80px_rgba(0,0,0,0.8)] border border-white/[0.08]">

        {/* Subtle Ambient Light Orb */}
        <div className="absolute -top-24 -right-24 w-80 h-80 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 -left-24 w-80 h-80 bg-violet-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Step 1: Upload Material or Select Subject */}
        {step === 'SELECT_SUBJECT' && (
          <div className="space-y-8 animate-fade-in relative z-10">
            <div className="text-center max-w-lg mx-auto space-y-2">
              <span className="px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-500/40 text-cyan-300 text-[10px] font-mono font-bold tracking-widest uppercase">
                LEARNSENSE // ONBOARDING
              </span>
              <h1 className="text-3xl sm:text-4xl font-display font-extrabold text-white tracking-tight">
                Construct Your Knowledge Universe
              </h1>
              <p className="text-xs text-universe-slate font-sans leading-relaxed">
                Ingest any textbook PDF, lecture slides (.pptx), Word document (.docx), or diagrams to automatically synthesize your interactive topological Atlas.
              </p>
            </div>

            {/* Primary Action: Upload Document */}
            <div className="p-8 rounded-3xl border-2 border-dashed border-cyan-500/30 bg-space-950/40 hover:bg-space-900/60 hover:border-cyan-400/60 transition-all text-center group cursor-pointer relative">
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
                <div className="w-14 h-14 rounded-2xl bg-cyan-500/10 border border-cyan-400/30 flex items-center justify-center text-cyan-300 group-hover:scale-105 transition-transform shadow-[0_0_20px_rgba(0,240,255,0.15)]">
                  {uploadingPdf ? (
                    <RefreshCw className="w-6 h-6 animate-spin text-cyan-400" />
                  ) : (
                    <Upload className="w-6 h-6" />
                  )}
                </div>

                <div className="space-y-1">
                  <h3 className="text-base font-display font-bold text-white">
                    {uploadingPdf ? 'Synthesizing Knowledge Topology...' : 'Ingest Course Material (PDF, PPTX, DOCX, IMG)'}
                  </h3>
                  <p className="text-xs text-universe-slate max-w-md mx-auto font-sans leading-relaxed">
                    {uploadingPdf
                      ? uploadStage === 'uploading'
                        ? 'Uploading your document...'
                        : uploadStage.startsWith('processing (')
                          ? `Processing / ingesting: ${uploadStage.replace('processing (', '').replace(')', '')}`
                          : uploadStage === 'extracting concepts'
                            ? 'Extracting concepts from your document...'
                            : uploadStage === 'preparing assessment'
                              ? 'Preparing your self-assessment...'
                              : 'Extracting chapters, prerequisite concepts, and generating grounded curriculum question bank...'
                      : 'Drop any course material or textbook file to generate your grounded personalized learning universe.'}
                  </p>
                </div>

                {!uploadingPdf && (
                  <span className="py-2.5 px-6 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center gap-2 shadow-[0_0_20px_rgba(0,240,255,0.25)] transition-all mt-2">
                    <Upload className="w-3.5 h-3.5" />
                    <span>Select File to Ingest</span>
                  </span>
                )}
              </label>
            </div>

            {uploadError && (
              <div className="p-3.5 rounded-xl bg-rose-950/50 border border-rose-500/40 text-xs text-rose-300 font-mono text-center space-y-2">
                <p>Ingestion failed: {uploadError}</p>
                <p className="text-rose-300/70">Check the file and try again — no partial learning state was created.</p>
              </div>
            )}

            {/* Secondary Action: Select existing subject */}
            <div className="flex items-center gap-4 my-6">
              <div className="h-px bg-white/[0.08] flex-1" />
              <span className="text-[10px] font-mono uppercase tracking-widest text-universe-slate/70">
                Or explore an existing knowledge base
              </span>
              <div className="h-px bg-white/[0.08] flex-1" />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {subjects.map((s) => (
                <div
                  key={s.id}
                  onClick={() => handleSelectSubject(s)}
                  className="p-4 rounded-2xl universe-panel-interactive cursor-pointer flex items-center justify-between group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-space-950 border border-white/[0.08] text-cyan-400 group-hover:text-cyan-300 transition-colors">
                      <BookOpen className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-display font-bold text-white group-hover:text-cyan-300 transition-colors">
                        {s.title}
                      </h4>
                      <div className="flex items-center gap-2 text-[10px] text-universe-slate mt-0.5 font-mono">
                        <span>{s.concept_count} Concepts</span>
                        <span>•</span>
                        <span>{s.page_count} Pages</span>
                      </div>
                    </div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-universe-slate group-hover:text-cyan-400 transition-colors" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 2: Concept Familiarity Self Assessment + Confidence */}
        {step === 'SELF_ASSESSMENT' && selectedSubject && (
          <div className="space-y-6 animate-fade-in relative z-10">
            <div className="pb-4 border-b border-white/[0.08] flex items-center justify-between">
              <div>
                <span className="text-[10px] font-mono tracking-widest text-cyan-400 font-bold uppercase">
                  STEP 2 OF 3 // TOPOLOGY INITIALIZATION
                </span>
                <h2 className="text-xl sm:text-2xl font-display font-bold text-white mt-1">
                  Baseline Knowledge Calibration
                </h2>
                <p className="text-xs text-universe-slate font-sans mt-1 max-w-xl leading-relaxed">
                  Before we build your learning path, rate your knowledge in each extracted
                  topic below and tell us how confident you feel. We&apos;ll use a short
                  adaptive assessment to verify your current understanding. Your
                  self-assessment is a starting point, not a final judgment.
                </p>
              </div>
              <Orbit className="w-6 h-6 text-cyan-400 shrink-0" />
            </div>

            <div className="max-h-96 overflow-y-auto space-y-4 pr-2">
              {topicGroups.map((group) => (
                <div key={group.key} className="space-y-2.5">
                  {group.title && (
                    <div className="flex items-center justify-between gap-3 pt-1">
                      <h3 className="text-[11px] font-mono font-bold uppercase tracking-widest text-cyan-300">
                        {group.title}
                        <span className="text-universe-slate/60 font-normal"> ({group.concepts.length})</span>
                      </h3>
                      <div className="flex items-center gap-1">
                        <span className="text-[10px] font-mono text-universe-slate/60 mr-1">Mark all:</span>
                        {(['KNOW', 'UNANSWERED', 'DONT_KNOW'] as const).map((level) => (
                          <button
                            key={level}
                            onClick={() => markTopic(group.concepts.map((c) => c.concept_id), level)}
                            className="px-2 py-0.5 rounded-md text-[10px] font-mono text-universe-slate hover:text-cyan-300 hover:bg-cyan-400/10 border border-transparent hover:border-cyan-400/30 transition-all"
                          >
                            {level === 'KNOW' ? 'Strong' : level === 'UNANSWERED' ? 'Unsure' : 'Weak'}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {group.concepts.map((c) => {
                const currentStatus = selfAssessmentSelections[c.concept_id] || 'UNANSWERED';
                const currentConf: Confidence = confidenceSelections[c.concept_id] || 'Medium';
                return (
                  <div
                    key={c.concept_id}
                    className="p-3.5 rounded-xl bg-space-950/60 border border-white/[0.06] flex flex-col gap-3"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <h4 className="text-xs font-display font-bold text-white">{c.name}</h4>
                        <p className="text-[11px] text-universe-slate line-clamp-1 font-sans">{c.definition}</p>
                      </div>

                      <div className="flex items-center gap-1.5 shrink-0">
                        <button
                          onClick={() => setLevel(c.concept_id, 'KNOW')}
                          className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1 transition-all ${
                            currentStatus === 'KNOW'
                              ? 'bg-emerald-500 text-space-950 shadow-[0_0_12px_rgba(16,185,129,0.3)]'
                              : 'bg-space-850 text-universe-slate hover:text-white border border-white/[0.06]'
                          }`}
                        >
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Strong</span>
                        </button>

                        <button
                          onClick={() => setLevel(c.concept_id, 'UNANSWERED')}
                          className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1 transition-all ${
                            currentStatus === 'UNANSWERED'
                              ? 'bg-amber-400 text-space-950 shadow-[0_0_12px_rgba(245,158,11,0.3)] ring-1 ring-amber-300'
                              : 'bg-space-850 text-universe-slate hover:text-white border border-white/[0.06]'
                          }`}
                        >
                          <HelpCircle className="w-3 h-3" />
                          <span>Unsure</span>
                        </button>

                        <button
                          onClick={() => setLevel(c.concept_id, 'DONT_KNOW')}
                          className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1 transition-all ${
                            currentStatus === 'DONT_KNOW'
                              ? 'bg-rose-500 text-space-950 shadow-[0_0_12px_rgba(244,63,94,0.3)]'
                              : 'bg-space-850 text-universe-slate hover:text-white border border-white/[0.06]'
                          }`}
                        >
                          <XCircle className="w-3 h-3" />
                          <span>Weak</span>
                        </button>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 pl-0.5">
                      <span className="text-[10px] font-mono uppercase tracking-widest text-universe-slate/70">
                        Confidence:
                      </span>
                      <div className="flex items-center gap-1">
                        {CONFIDENCE_ORDER.map((level) => (
                          <button
                            key={level}
                            onClick={() => setConfidence(c.concept_id, level)}
                            className={`px-2.5 py-1 rounded-md text-[11px] font-mono font-bold transition-all ${
                              currentConf === level
                                ? 'bg-cyan-400/20 text-cyan-300 border border-cyan-400/50'
                                : 'text-universe-slate hover:text-white border border-transparent'
                            }`}
                          >
                            {level}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })}
                </div>
              ))}
            </div>

            <div className="pt-4 border-t border-white/[0.08] flex items-center justify-between gap-4">
              <div className="text-xs text-universe-slate font-sans">
                {verifyCount > 0 ? (
                  <span>
                    <strong className="text-cyan-400 font-mono font-bold">{verifyCount}</strong> concepts queued for diagnostic verification.
                  </span>
                ) : (
                  <span>
                    All concepts set to baseline. Click below to begin personalized learning vector.
                  </span>
                )}
              </div>

              <button
                onClick={handleSubmitSelfAssessment}
                disabled={loading}
                className="py-3 px-6 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center gap-2 shadow-[0_0_20px_rgba(0,240,255,0.25)] transition-all shrink-0 disabled:opacity-50"
              >
                <span>{verifyCount > 0 ? `Begin Diagnostic (${verifyCount})` : 'Construct Learning Atlas'}</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Diagnostic Assessment */}
        {step === 'DIAGNOSTIC' && (
          <div className="space-y-6 animate-fade-in relative z-10">
            {diagnosticQuestions.length === 0 ? (
              <div className="text-center py-12 space-y-3">
                <p className="text-xs text-universe-slate font-mono">No diagnostic items required.</p>
                <button
                  onClick={() => selectedSubject && onCompleteOnboarding(selectedSubject.id, learnerId)}
                  className="py-2.5 px-5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs"
                >
                  Enter Learning Atlas
                </button>
              </div>
            ) : (() => {
              const q = diagnosticQuestions[currentQuestionIdx];
              if (!q) {
                return (
                  <div className="text-center py-12 space-y-3">
                    <p className="text-xs text-universe-slate font-mono">Diagnostic assessment completed.</p>
                    <button
                      onClick={() => handleSubmitDiagnostic()}
                      className="py-2.5 px-5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs"
                    >
                      Calibrate Knowledge State
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

              const onOptionClick = (optText: string) => {
                if (isDontKnowText(optText)) {
                  handleAnswerDiagnosticQuestion(qId, "I don't know");
                  return;
                }
                handleAnswerDiagnosticQuestion(qId, optText.trim());
              };

              return (
                <div className="space-y-6">
                  <div className="pb-4 border-b border-white/[0.08] flex items-center justify-between">
                    <div>
                      <span className="text-[10px] font-mono tracking-widest text-emerald-400 font-bold uppercase">
                        DIAGNOSTIC QUESTION {currentQuestionIdx + 1} OF {diagnosticQuestions.length}
                      </span>
                      <h2 className="text-xl font-display font-bold text-white mt-0.5">
                        Verify Your Understanding
                      </h2>
                      <p className="text-[11px] text-universe-slate font-sans mt-0.5">
                        Your answers help us estimate what you already know — this verifies your
                        self-assessment rather than judging it.
                      </p>
                    </div>
                    <Brain className="w-5 h-5 text-emerald-400 shrink-0" />
                  </div>

                  <div className="space-y-4">
                    <div className="p-5 rounded-2xl bg-space-950/70 border border-white/[0.06]">
                      <p className="text-xs sm:text-sm font-sans text-universe-text leading-relaxed">
                        {qText}
                      </p>
                    </div>

                    <div className="space-y-2">
                      {rawOptions.map((opt, optIdx) => (
                        <button
                          key={optIdx}
                          disabled={loading}
                          onClick={() => onOptionClick(opt)}
                          className={`w-full p-3.5 rounded-xl border border-white/[0.06] bg-space-950/50 hover:bg-space-850 hover:border-cyan-400/40 text-left text-xs text-universe-text transition-all font-sans flex items-center justify-between disabled:opacity-50 ${
                            isDontKnowText(opt) ? 'text-amber-300 hover:border-amber-400/40 bg-amber-950/20' : ''
                          }`}
                        >
                          <span>{opt}</span>
                          {isDontKnowText(opt) && <ShieldCheck className="w-4 h-4 text-amber-400 shrink-0" />}
                        </button>
                      ))}

                      {q.allow_dont_know_option && !hasDontKnowInOptions && (
                        <button
                          disabled={loading}
                          onClick={() => handleAnswerDiagnosticQuestion(qId, "I don't know")}
                          className="w-full p-3.5 rounded-xl border border-amber-500/30 bg-amber-950/30 hover:bg-amber-900/40 text-left text-xs font-mono text-amber-200 transition-all flex items-center gap-2 disabled:opacity-50"
                        >
                          <ShieldCheck className="w-4 h-4 text-amber-400" />
                          <span>I don&apos;t know this concept yet</span>
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
