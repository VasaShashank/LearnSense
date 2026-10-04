import React, { useEffect, useState } from 'react';
import type { Subject, Question, ConceptNode, TopicTerritory } from '../../api/client';
import { ApiClient, ApiError } from '../../api/client';
import { CheckCircle2, XCircle, HelpCircle, ArrowRight, BookOpen, Brain, ShieldCheck, Upload, RefreshCw, Orbit, AlertTriangle } from 'lucide-react';

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
  /**
   * Which half of onboarding this render represents.
   *
   * `SOURCE_SELECTION` shows the existing source library + ingestion panel.
   * `CALIBRATION` shows strength rating and verification ONLY.
   *
   * This prop exists because the component's default step used to be
   * `SELECT_SUBJECT`, so *every* unresolved state -- no learner, resume error,
   * resume timeout -- rendered the upload page and made ingestion the generic
   * fallback route. The parent now decides which half is valid; the component
   * can no longer fall into it by accident.
   */
  mode?: 'SOURCE_SELECTION' | 'CALIBRATION';
  /** When true, forces the self-assessment survey quiz to open even if the subject was previously calibrated. */
  forceSurvey?: boolean;
  /** Notifies the parent that the subject list changed (e.g. after an upload). */
  onSubjectsChanged?: () => void;
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
  mode = 'SOURCE_SELECTION',
  forceSurvey = false,
  onSubjectsChanged,
}) => {
  // Default step is decided by mode or forceSurvey
  const [step, setStep] = useState<'SELECT_SUBJECT' | 'SELF_ASSESSMENT' | 'DIAGNOSTIC' | 'COMPLETED'>(
    mode === 'CALIBRATION' || forceSurvey ? 'SELF_ASSESSMENT' : 'SELECT_SUBJECT',
  );
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);
  const [learnerId] = useState<string>('student_alex');
  const [concepts, setConcepts] = useState<ConceptNode[]>([]);
  const [topics, setTopics] = useState<TopicTerritory[]>([]);
  const [selfAssessmentSelections, setSelfAssessmentSelections] = useState<Record<string, string>>({});
  const [confidenceSelections, setConfidenceSelections] = useState<Record<string, Confidence>>({});
  const [sessionId, setSessionId] = useState<string>('');
  // `diagnosticQuestions` is the plan the server produced; `diagnosticNext` is the
  // item it wants answered RIGHT NOW. The next item is chosen from the learner's
  // post-answer state, so it is not necessarily the next entry in the plan.
  const [_diagnosticQuestions, setDiagnosticQuestions] = useState<Question[]>([]);
  const [diagnosticNext, setDiagnosticNext] = useState<Question | null>(null);
  const [_diagnosticAnswers, setDiagnosticAnswers] = useState<Record<string, string>>({});
  const [answeredCount, setAnsweredCount] = useState<number>(0);
  const [totalPlanned, setTotalPlanned] = useState<number>(0);
  const [answering, setAnswering] = useState<boolean>(false);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);
  // The option currently being submitted, kept so a failed request can be retried
  // without asking the learner to pick again.
  const [pendingAnswer, setPendingAnswer] = useState<{
    questionId: string;
    option: string;
    isDontKnow: boolean;
  } | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [uploadingPdf, setUploadingPdf] = useState<boolean>(false);
  const [uploadStage, setUploadStage] = useState<string>('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [subjectCalibrationStatus, setSubjectCalibrationStatus] = useState<Record<string, { needs_calibration: boolean; diagnostic_completed: boolean }>>({});

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

  // 1. Select Subject - loads data and checks calibration status
  const handleSelectSubject = async (sub: Subject, bypassGate: boolean = false) => {
    setSelectedSubject(sub);
    setLoading(true);
    try {
      const graph = await ApiClient.getSubjectGraph(sub.id, learnerId);
      setConcepts(graph.concepts);
      setTopics(graph.topics || []);

      // If not forcing the survey quiz, check if subject is already fully calibrated
      if (!bypassGate && !forceSurvey) {
        const calibrationStatus = await ApiClient.getCalibrationStatus(learnerId, sub.id);
        if (!calibrationStatus.needs_calibration && calibrationStatus.diagnostic_completed) {
          clearDraft(sub.id);
          onCompleteOnboarding(sub.id, learnerId);
          return;
        }
      }

      // Subject needs calibration (or survey is requested) - load self-assessment data and auto-proceed
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
      // Auto-proceed to self-assessment survey
      setStep('SELF_ASSESSMENT');
    } catch (err) {
      console.error('Failed to load subject graph', err);
    } finally {
      setLoading(false);
    }
  };

  // Check calibration status for all subjects on mount to show badges
  useEffect(() => {
    const checkAllCalibrationStatus = async () => {
      const statusMap: Record<string, { needs_calibration: boolean; diagnostic_completed: boolean }> = {};
      await Promise.all(
        subjects.map(async (s) => {
          try {
            const status = await ApiClient.getCalibrationStatus(learnerId, s.id);
            statusMap[s.id] = {
              needs_calibration: status.needs_calibration,
              diagnostic_completed: status.diagnostic_completed,
            };
          } catch {
            // Best-effort - if check fails, assume needs calibration
            statusMap[s.id] = { needs_calibration: true, diagnostic_completed: false };
          }
        })
      );
      setSubjectCalibrationStatus(statusMap);
    };
    checkAllCalibrationStatus();
  }, [subjects, learnerId]);

  // 1b. Handle PDF/File Upload — ingestion states: uploading → processing →
  // extracting → ready for self-assessment. Self-assessment is only shown once
  // the concept graph exists; failures surface a clear error with retry.
  // CRITICAL: The backend uploadSource handles the full ingestion pipeline
  // (OCR → chunking → embedding → indexing) and only returns when complete.
  // We then verify the concept graph is available before proceeding.
  const handleOnboardingPdfUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingPdf(true);
    setUploadError(null);

    try {
      setUploadStage('uploading');
      // Backend runs full pipeline: OCR → chunking → embedding → indexing
      // This call waits for complete ingestion before returning
      const res = await ApiClient.uploadSource(file, (stage) => setUploadStage(stage));
      setUploadStage('verifying ingestion complete');
      const cleanTitle = file.name.replace(/\.[^/.]+$/, '').replace(/_/g, ' ').toUpperCase();
      const newSub: Subject = {
        id: res.document_id,
        title: cleanTitle,
        concept_count: res.concept_count || 10,
        page_count: res.page_count || 1,
        has_ekr: true,
      };
      setSelectedSubject(newSub);
      
      // Verify concept graph is available (ingestion must be complete)
      setUploadStage('loading knowledge graph');
      const graph = await ApiClient.getSubjectGraph(newSub.id, learnerId);
      
      // Verify graph has concepts (ingestion successful)
      if (!graph.concepts || graph.concepts.length === 0) {
        throw new Error('Ingestion completed but no concepts were extracted. The document may be empty or unsupported.');
      }
      
      setConcepts(graph.concepts);
      setTopics(graph.topics || []);
      
      // Load self-assessment data
      setUploadStage('preparing self-assessment');
      const draft = loadDraft(newSub.id);
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
      setUploadStage('ingestion complete');
      // Only proceed to self-assessment after successful ingestion verification
      setStep('SELF_ASSESSMENT');
      // Let the parent re-resolve routing state: the new source now exists and
      // this learner needs calibration for it.
      onSubjectsChanged?.();
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
        setDiagnosticQuestions(diagData.questions ?? []);
        setAnsweredCount(diagData.answered_count ?? 0);
        setTotalPlanned(diagData.total_planned ?? diagData.question_count ?? 0);
        // Previously the resume handler reset answers and the index to 0, so a
        // refresh mid-quiz silently discarded everything the learner had done.
        // Position now comes from the server.
        setDiagnosticAnswers(
          Object.fromEntries((diagData.answered_question_ids ?? []).map((qid) => [qid, ''])),
        );

        if (diagData.status === 'error') {
          setDiagnosticError(diagData.error ?? 'The verification test could not be prepared. Please retry.');
          setDiagnosticNext(null);
          setStep('DIAGNOSTIC');
          return;
        }
        if (diagData.status === 'completed' || !diagData.next_question) {
          clearDraft(sub.id);
          onCompleteOnboarding(sub.id, learnerId);
          return;
        }
        setDiagnosticNext(diagData.next_question);
        setStep('DIAGNOSTIC');
      } catch (err) {
        console.error('Failed to resume diagnostic', err);
        // Surface a retry instead of dropping the learner on the upload page.
        setDiagnosticError(
          err instanceof ApiError
            ? `Could not resume your verification test: ${err.message}`
            : 'Could not resume your verification test. Please retry.',
        );
        setStep('DIAGNOSTIC');
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

  // Transition to self-assessment survey when initialSubject is provided
  const initialSubjectHandled = React.useRef<string | null>(null);
  useEffect(() => {
    if (!initialSubject || resumeInitSession) return;
    if (initialSubjectHandled.current === initialSubject.id) return;
    initialSubjectHandled.current = initialSubject.id;
    handleSelectSubject(initialSubject, Boolean(forceSurvey || mode === 'CALIBRATION'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSubject?.id, mode, forceSurvey]);

  // 2. Submit Self Assessment — self-assessment + confidence is the initial
  // hypothesis only. The server stores it separately from BKT evidence and the
  // diagnostic below verifies it before any learning path is generated.
  const handleSubmitSelfAssessment = async () => {
    if (!selectedSubject) return;
    setLoading(true);
    setSubmitError(null);
    try {
      console.log('[CALIBRATION] Submitting self-assessment...');
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
      console.log('[CALIBRATION] Self-assessment submitted, session ID:', session.session_id);

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
      console.log('[CALIBRATION] Verification count:', verifyCount);
      
      if (verifyCount === 0) {
        console.log('[CALIBRATION] No concepts need verification, skipping to onboarding completion');
        clearDraft(selectedSubject.id);
        onCompleteOnboarding(selectedSubject.id, learnerId);
        return;
      }

      console.log('[CALIBRATION] Starting diagnostic generation...');
      const diagData = await ApiClient.startDiagnostic(session.session_id, learnerId);

      // A generation failure is an ERROR state, not a pass. Previously both
      // `start_diagnostic` (server) and this branch (client) treated "no
      // questions" as "verification complete", so an LLM/bank failure silently
      // promoted an unverified learner straight to the dashboard.
      if (diagData.status === 'error') {
        setDiagnosticError(
          diagData.error ?? 'The verification test could not be prepared. Please retry.',
        );
        setDiagnosticQuestions([]);
        setDiagnosticNext(null);
        setStep('DIAGNOSTIC');
        return;
      }

      setDiagnosticQuestions(diagData.questions ?? []);
      setAnsweredCount(diagData.answered_count ?? 0);
      setTotalPlanned(diagData.total_planned ?? diagData.question_count ?? 0);

      if (!diagData.next_question) {
        // Genuinely nothing to verify (empty verification set) -> proceed.
        clearDraft(selectedSubject.id);
        onCompleteOnboarding(selectedSubject.id, learnerId);
        return;
      }
      setDiagnosticNext(diagData.next_question);
      setStep('DIAGNOSTIC');
    } catch (err) {
      console.error('[CALIBRATION] Failed to submit self assessment', err);
      setSubmitError(
        err instanceof ApiError
          ? `Could not start the verification test: ${err.message}`
          : 'Could not start the verification test. Please try again.',
      );
    } finally {
      setLoading(false);
      console.log('[CALIBRATION] Loading state cleared');
    }
  };

  // 3. Submit ONE diagnostic answer.
  //
  // The quiz is per-answer rather than batched:
  //   * the server grades the response and updates BKT immediately,
  //   * the next question is selected from the learner's post-answer state,
  //   * a refresh re-enters the same assessment with the same answers,
  //   * re-sending a question is reported as a duplicate and changes nothing.
  //
  // Correctness is never computed here. The previous implementation collected
  // every answer in local React state and posted them all at the end, which made
  // the quiz a fixed batch, lost everything on refresh, and had no way to
  // protect against a double submit.
  const handleAnswerDiagnosticQuestion = async (
    questionId: string,
    selectedOption: string,
    isDontKnow = false,
  ) => {
    if (answering || pendingAnswer) return;
    setAnswering(true);
    setDiagnosticError(null);
    setPendingAnswer({ questionId, option: selectedOption, isDontKnow });

    try {
      const res = await ApiClient.submitDiagnosticAnswer(
        sessionId,
        learnerId,
        questionId,
        isDontKnow ? null : selectedOption,
        isDontKnow,
      );

      setDiagnosticAnswers((prev) => ({ ...prev, [questionId]: selectedOption }));
      setAnsweredCount(res.answered_count);
      setTotalPlanned(res.total_planned || totalPlanned);
      setPendingAnswer(null);

      if (res.complete) {
        if (selectedSubject) {
          clearDraft(selectedSubject.id);
          onCompleteOnboarding(selectedSubject.id, learnerId);
        }
        return;
      }

      if (!res.next_question) {
        // Server stopped without finalizing -> surface it rather than guessing.
        setDiagnosticError('The verification test stopped unexpectedly. Please retry.');
        return;
      }
      setDiagnosticNext(res.next_question);
    } catch (err) {
      console.error('Failed to submit diagnostic answer', err);
      setDiagnosticError(
        err instanceof ApiError
          ? `Your answer was not saved: ${err.message}`
          : 'Your answer was not saved. Retry to submit it again.',
      );
      // `pendingAnswer` is intentionally kept so Retry can re-send the exact
      // same response. The server de-duplicates, so a retry is always safe.
    } finally {
      setAnswering(false);
    }
  };

  const retryPendingAnswer = () => {
    const p = pendingAnswer;
    if (!p) return;
    setPendingAnswer(null);
    void handleAnswerDiagnosticQuestion(p.questionId, p.option, p.isDontKnow);
  };

  /**
   * Retry after question-generation or resume failure.
   * Re-runs start_diagnostic on the same session, which reuses the existing
   * plan and reports the answers already recorded.
   */
  const retryDiagnostic = async () => {
    setDiagnosticError(null);
    setLoading(true);
    try {
      const diagData = await ApiClient.startDiagnostic(sessionId, learnerId);
      if (diagData.status === 'error') {
        setDiagnosticError(diagData.error ?? 'The verification test could not be prepared. Please retry.');
        return;
      }
      setDiagnosticQuestions(diagData.questions ?? []);
      setAnsweredCount(diagData.answered_count ?? 0);
      setTotalPlanned(diagData.total_planned ?? diagData.question_count ?? 0);
      if (!diagData.next_question) {
        if (selectedSubject) {
          clearDraft(selectedSubject.id);
          onCompleteOnboarding(selectedSubject.id, learnerId);
        }
        return;
      }
      setDiagnosticNext(diagData.next_question);
    } catch (err) {
      setDiagnosticError(
        err instanceof ApiError
          ? `Could not load the verification test: ${err.message}`
          : 'Could not load the verification test. Please retry.',
      );
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

        {/* Step 1: Upload Material or Select Subject.
            Only reachable in SOURCE_SELECTION mode: the calibration stages must
            never render the ingestion panel as their fallback. */}
        {step === 'SELECT_SUBJECT' && mode === 'SOURCE_SELECTION' && (
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
                            : uploadStage === 'loading knowledge base'
                              ? 'Loading knowledge base...'
                              : uploadStage === 'ready for self-assessment'
                                ? 'Ready for self-assessment...'
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
              {subjects.map((s) => {
                const status = subjectCalibrationStatus[s.id];
                const isReady = status && !status.needs_calibration && status.diagnostic_completed;
                return (
                  <div
                    key={s.id}
                    onClick={() => handleSelectSubject(s)}
                    className="p-4 rounded-2xl universe-panel-interactive cursor-pointer flex items-center justify-between group"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2.5 rounded-xl bg-space-950 border border-white/[0.08] text-cyan-400 group-hover:text-cyan-300 transition-colors">
                        <BookOpen className="w-4 h-4" />
                      </div>
                      <div className="flex-1">
                        <h4 className="text-xs font-display font-bold text-white group-hover:text-cyan-300 transition-colors">
                          {s.title}
                        </h4>
                        <div className="flex items-center gap-2 text-[10px] text-universe-slate mt-0.5 font-mono">
                          <span>{s.concept_count} Concepts</span>
                          <span>•</span>
                          <span>{s.page_count} Pages</span>
                        </div>
                        {status && (
                          <div className="flex items-center gap-1.5 mt-1.5">
                            {isReady ? (
                              <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 text-[9px] font-mono font-bold border border-emerald-500/30">
                                READY TO CONTINUE
                              </span>
                            ) : status.needs_calibration ? (
                              <span className="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 text-[9px] font-mono font-bold border border-amber-500/30">
                                NEEDS CALIBRATION
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 text-[9px] font-mono font-bold border border-cyan-500/30">
                                IN PROGRESS
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-universe-slate group-hover:text-cyan-400 transition-colors" />
                  </div>
                );
              })}
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

            {submitError && (
              <div className="p-3.5 rounded-xl bg-rose-950/50 border border-rose-500/40 text-xs text-rose-200 font-sans flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p>{submitError}</p>
                  <button
                    onClick={() => setSubmitError(null)}
                    className="text-rose-300 hover:text-rose-100 underline font-mono text-[11px]"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            <div className="pt-4 border-t border-white/[0.08] flex items-center justify-between gap-4">
              <div className="text-xs text-universe-slate font-sans">
                {loading ? (
                  <span className="font-mono text-cyan-400">Preparing your verification test…</span>
                ) : verifyCount > 0 ? (
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
                onClick={() => {
                  setSubmitError(null);
                  handleSubmitSelfAssessment();
                }}
                disabled={loading}
                className="py-3 px-6 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center gap-2 shadow-[0_0_20px_rgba(0,240,255,0.25)] transition-all shrink-0 disabled:opacity-50"
              >
                <span>
                  {loading
                    ? 'Starting…'
                    : verifyCount > 0
                      ? `Begin Diagnostic (${verifyCount})`
                      : 'Construct Learning Atlas'}
                </span>
                {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Adaptive Verification Assessment */}
        {step === 'DIAGNOSTIC' && (
          <div className="space-y-6 animate-fade-in relative z-10">
            {(() => {
              // ERROR state first: a failed question generation or a failed answer
              // submission must offer RETRY, never silently advance to the Atlas.
              if (diagnosticError) {
                return (
                  <div className="text-center py-10 space-y-5">
                    <div className="flex items-center justify-center gap-3">
                      <AlertTriangle className="w-6 h-6 text-amber-400" />
                      <h2 className="text-lg font-display font-bold text-white">
                        Verification could not continue
                      </h2>
                    </div>
                    <p className="text-xs text-universe-slate font-sans leading-relaxed max-w-md mx-auto">
                      {diagnosticError}
                    </p>
                    <p className="text-[11px] text-universe-slate/80 font-sans leading-relaxed max-w-md mx-auto">
                      {answeredCount > 0
                        ? `${answeredCount} answer${answeredCount === 1 ? '' : 's'} already saved on the server. Retrying reuses them.`
                        : 'Nothing has been recorded yet, so retrying is safe.'}
                    </p>
                    <div className="flex items-center justify-center gap-3 flex-wrap">
                      <button
                        onClick={retryPendingAnswer}
                        disabled={!pendingAnswer || answering}
                        className="py-2.5 px-5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs disabled:opacity-40"
                      >
                        {answering ? 'Submitting...' : 'Retry Answer'}
                      </button>
                      <button
                        onClick={() => void retryDiagnostic()}
                        disabled={loading || answering}
                        className="py-2.5 px-5 rounded-xl bg-space-850 border border-white/10 text-universe-text font-display font-bold text-xs disabled:opacity-40"
                      >
                        {loading ? 'Loading...' : 'Reload Verification'}
                      </button>
                    </div>
                  </div>
                );
              }

              // The item the SERVER wants answered now. It is chosen from the
              // learner's post-answer state, so it is not simply questions[idx+1].
              const q = diagnosticNext;

              if (!q) {
                return (
                  <div className="text-center py-12 space-y-3">
                    <p className="text-xs text-universe-slate font-mono">No verification items required.</p>
                    <button
                      onClick={() => selectedSubject && onCompleteOnboarding(selectedSubject.id, learnerId)}
                      className="py-2.5 px-5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs"
                    >
                      Enter Learning Atlas
                    </button>
                  </div>
                );
              }

              const qText = q.question_text || q.prompt || 'Assess your understanding of this concept:';
              const qId = q.question_id || q.item_id || 'q_current';
              const rawOptions = Array.isArray(q.options) && q.options.length > 0 ? q.options : [];

              const isDontKnowText = (text: string) => {
                const lower = text.toLowerCase();
                return lower.includes("don't know") || lower.includes("dont know") || lower.includes("unsure");
              };

              const hasDontKnowInOptions = rawOptions.some(isDontKnowText);

              const onOptionClick = (optText: string) => {
                void handleAnswerDiagnosticQuestion(
                  qId,
                  isDontKnowText(optText) ? "I don't know" : optText.trim(),
                  isDontKnowText(optText),
                );
              };

              return (
                <div className="space-y-6">
                  <div className="pb-4 border-b border-white/[0.08] flex items-center justify-between">
                    <div>
                      <span className="text-[10px] font-mono tracking-widest text-emerald-400 font-bold uppercase">
                        VERIFICATION {answeredCount + 1}
                        {totalPlanned > 0 ? ` // UP TO ${totalPlanned}` : ''}
                      </span>
                      <h2 className="text-xl font-display font-bold text-white mt-0.5">
                        Verify Your Understanding
                      </h2>
                      <p className="text-[11px] text-universe-slate font-sans mt-0.5">
                        Each question is chosen based on what you have answered so far, so the test
                        adapts to you. Answers are saved as you go.
                      </p>
                    </div>
                    <Brain className="w-5 h-5 text-emerald-400 shrink-0" />
                  </div>

                  <div className="space-y-4">
                    <div className="p-5 rounded-2xl bg-space-950/70 border border-white/[0.06]">
                      <p className="text-xs sm:text-sm font-sans text-universe-text leading-relaxed break-words overflow-wrap-anywhere">
                        {qText}
                      </p>
                    </div>

                    <div className="space-y-2">
                      {rawOptions.map((opt, optIdx) => (
                        <button
                          key={optIdx}
                          disabled={answering}
                          onClick={() => onOptionClick(opt)}
                          className={`w-full p-3.5 rounded-xl border border-white/[0.06] bg-space-950/50 hover:bg-space-850 hover:border-cyan-400/40 text-left text-xs text-universe-text transition-all font-sans flex items-center justify-between disabled:opacity-50 break-words overflow-wrap-anywhere ${
                            isDontKnowText(opt) ? 'text-amber-300 hover:border-amber-400/40 bg-amber-950/20' : ''
                          }`}
                        >
                          <span className="flex-1">{opt}</span>
                          {isDontKnowText(opt) && <ShieldCheck className="w-4 h-4 text-amber-400 shrink-0 ml-2" />}
                        </button>
                      ))}

                      {q.allow_dont_know_option && !hasDontKnowInOptions && (
                        <button
                          disabled={answering}
                          onClick={() => void handleAnswerDiagnosticQuestion(qId, "I don't know", true)}
                          className="w-full p-3.5 rounded-xl border border-amber-500/30 bg-amber-950/30 hover:bg-amber-900/40 text-left text-xs font-mono text-amber-200 transition-all flex items-center gap-2 disabled:opacity-50"
                        >
                          <ShieldCheck className="w-4 h-4 text-amber-400" />
                          <span>I don&apos;t know this concept yet</span>
                        </button>
                      )}

                      {answering && (
                        <p className="text-[11px] font-mono text-cyan-300 text-center pt-2">
                          Saving your answer...
                        </p>
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
