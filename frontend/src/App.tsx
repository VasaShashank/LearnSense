import { useState, useEffect, useCallback, useRef } from 'react';
import type { Subject, KnowledgeGraphData, LearnerProgress, KnowledgeGap, LearningPathNode, LearningTarget, ConceptNode, SourceDocument, EntryState, EntryStateName } from './api/client';
import { ApiClient } from './api/client';
import { TopNavbar } from './components/navigation/TopNavbar';
import { Dashboard } from './components/dashboard/Dashboard';
import { LearningAtlas } from './components/atlas/LearningAtlas';
import { AccessibleAtlasView } from './components/atlas/AccessibleAtlasView';
import { XRayInspector } from './components/atlas/XRayInspector';
import { ConceptInspector } from './components/inspector/ConceptInspector';
import { LearningPathTimeline } from './components/path/LearningPathTimeline';
import { LearningSession } from './components/session/LearningSession';
import { FinalAssessment } from './components/session/FinalAssessment';
import { ContextualTutor } from './components/tutor/ContextualTutor';
import { SourceLibrary } from './components/sources/SourceLibrary';
import { CommandPalette } from './components/palette/CommandPalette';
import { OnboardingWorkflow } from './components/onboarding/OnboardingWorkflow';
import { Zap, Sparkles, Orbit, AlertTriangle, RefreshCw } from 'lucide-react';

/**
 * The application state machine, rendered exactly as the backend reports it.
 *
 * There is deliberately no "unknown" bucket: if the backend cannot tell us where
 * the learner belongs we show an error with retry. The previous implementation
 * collapsed every un-resolved case into "not onboarded", which rendered the
 * ingestion/upload screen -- so an upload page became the generic fallback route.
 */
type AppStage =
  | 'BOOT'                 // resolving server-authoritative state
  | 'SOURCE_SELECTION'     // no usable knowledge source yet
  | 'CALIBRATION'          // source ready, self-assessment / verification
  | 'DASHBOARD'            // verification complete
  | 'ERROR';               // state could not be resolved -- retry, never ingest

function stageForEntryState(entry: EntryStateName): AppStage {
  switch (entry) {
    case 'NEEDS_CALIBRATION':
    case 'VERIFICATION_IN_PROGRESS':
    case 'VERIFICATION_ERROR':
      return 'CALIBRATION';
    case 'VERIFICATION_COMPLETE':
      return 'DASHBOARD';
    case 'NO_USER':
    case 'SOURCE_SELECTION':
    default:
      return 'SOURCE_SELECTION';
  }
}

export default function App() {
  const [learnerId] = useState<string>('student_alex');
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);
  const [stage, setStage] = useState<AppStage>('BOOT');
  const [, setEntryState] = useState<EntryState | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootAttempt, setBootAttempt] = useState<number>(0);

  const [activeView, setActiveView] = useState<'DASHBOARD' | 'ATLAS' | 'PATH' | 'SOURCES'>('DASHBOARD');
  // Resume / Rehydration State
  const [graphData, setGraphData] = useState<KnowledgeGraphData | null>(null);
  const [progress, setProgress] = useState<LearnerProgress | null>(null);
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [pathNodes, setPathNodes] = useState<LearningPathNode[]>([]);
  const [nextTarget, setNextTarget] = useState<LearningTarget | null>(null);
  const [sources, setSources] = useState<SourceDocument[]>([]);

  // Interactivity States
  const [selectedConcept, setSelectedConcept] = useState<ConceptNode | null>(null);
  const [isXRayMode, setIsXRayMode] = useState<boolean>(false);
  const [isTracingImpact, setIsTracingImpact] = useState<boolean>(false);
  const [impactedConceptIds, setImpactedConceptIds] = useState<string[]>([]);
  const [showAccessibleAtlas, setShowAccessibleAtlas] = useState<boolean>(false);

  // Active Session & Drawer States
  const [activeStudyConcept, setActiveStudyConcept] = useState<ConceptNode | null>(null);
  const [sessionInitialTab, setSessionInitialTab] = useState<'EXPLANATION' | 'PRACTICE'>('EXPLANATION');
  const [isTutorOpen, setIsTutorOpen] = useState<boolean>(false);
  const [tutorConcept, setTutorConcept] = useState<ConceptNode | null>(null);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState<boolean>(false);

  // Final Assessment State
  const [isFinalAssessmentOpen, setIsFinalAssessmentOpen] = useState<boolean>(false);
  const [activeAssessmentId, setActiveAssessmentId] = useState<string | null>(null);

  // Interrupted diagnostic session awaiting resume after refresh. Set only from
  // server state, never from a local guess.
  const [resumeInitSession, setResumeInitSession] = useState<{ session_id: string; subject_id: string } | null>(null);

  // Newly ingested subject that still needs self-assessment -> diagnostic
  // before learning starts. While set, the calibration flow takes over the UI.
  const [pendingCalibration, setPendingCalibration] = useState<Subject | null>(null);

  // Signature "Knowledge Changed" Notification State
  const [knowledgeChangedNotification, setKnowledgeChangedNotification] = useState<string | null>(null);

  // 1. Initial Load Subjects & Sources
  const reloadSubjectsAndSources = useCallback(async () => {
    try {
      const subs = await ApiClient.getSubjects();
      setSubjects(subs);
      const srcs = await ApiClient.getSources();
      setSources(srcs);
    } catch (err) {
      console.error('Failed to load initial data', err);
    }
  }, []);

  useEffect(() => {
    reloadSubjectsAndSources();
  }, [reloadSubjectsAndSources]);

  /**
   * Resolve where the learner belongs, from the server, then render that.
   *
   * This replaces the old `isOnboarded` boolean, which conflated three very
   * different situations (no learner state, a resume timeout, and a resume
   * error) into one screen -- the ingestion page. A timeout or failure now
   * produces an explicit ERROR stage with retry instead of masquerading as a
   * valid "you have no source yet" state.
   */
  useEffect(() => {
    let cancelled = false;

    const boot = async () => {
      setStage('BOOT');
      setBootError(null);
      try {
        const [resumeData, subs] = await Promise.all([
          ApiClient.resumeLearner(learnerId),
          ApiClient.getSubjects(),
        ]);
        if (cancelled) return;
        setSubjects(subs);

        const subjectId = resumeData.subject_id ?? null;
        if (subjectId) {
          const sub = subs.find((s) => s.id === subjectId);
          if (sub) setSelectedSubject(sub);
          // Remember this source server-side so reopening the app resumes it
          // instead of landing on an arbitrary document.
          void ApiClient.setActiveSubject(learnerId, subjectId).catch(() => undefined);
        }

        // SERVER AUTHORITY: the routing decision comes from the backend.
        const entry = await ApiClient.getEntryState(learnerId, subjectId ?? undefined);
        if (cancelled) return;
        setEntryState(entry);

        if (entry.entry_state === 'VERIFICATION_IN_PROGRESS' && entry.session_id && subjectId) {
          setResumeInitSession({ session_id: entry.session_id, subject_id: subjectId });
        } else {
          setResumeInitSession(null);
        }

        setStage(stageForEntryState(entry.entry_state));
      } catch (err) {
        if (cancelled) return;
        console.error('[RESTORE] Could not resolve learner state:', err);
        setBootError(
          err instanceof Error
            ? err.message
            : 'The learning backend did not respond. Your progress is safe on the server.',
        );
        // Deliberately NOT SOURCE_SELECTION: an unreachable backend is an error,
        // not evidence that the learner has no source.
        setStage('ERROR');
      }
    };

    boot();
    return () => {
      cancelled = true;
    };
  }, [learnerId, bootAttempt]);


  // 2. Load Subject Data when subject changes or knowledge updates
  const refreshSubjectData = useCallback(async () => {
    if (!selectedSubject) return;
    try {
      const graph = await ApiClient.getSubjectGraph(selectedSubject.id, learnerId);
      setGraphData(graph);

      const prog = await ApiClient.getLearnerProgress(learnerId, selectedSubject.id);
      setProgress(prog);

      const pathGapRes = await ApiClient.getPathAndGaps(learnerId, selectedSubject.id);
      setGaps(pathGapRes.gaps);
      setPathNodes(pathGapRes.learning_path.nodes);
      setNextTarget(pathGapRes.next_target);
    } catch (err) {
      console.error('Failed to refresh subject data', err);
    }
  }, [selectedSubject, learnerId]);

  useEffect(() => {
    if (stage === 'DASHBOARD' && selectedSubject) {
      refreshSubjectData();
    }
  }, [stage, selectedSubject, refreshSubjectData]);

  /**
   * Re-resolve the routing state from the backend.
   *
   * Every transition that could change where the learner belongs (finishing
   * onboarding, ingesting a new source) funnels through here, so the UI can
   * never drift into showing the dashboard because of a local flag.
   */
  const resolveStage = useCallback(
    async (subjectId?: string) => {
      try {
        const entry = await ApiClient.getEntryState(learnerId, subjectId);
        setEntryState(entry);
        setBootError(null);
        if (entry.entry_state === 'VERIFICATION_IN_PROGRESS' && entry.session_id && entry.subject_id) {
          setResumeInitSession({ session_id: entry.session_id, subject_id: entry.subject_id });
        } else {
          setResumeInitSession(null);
        }
        const next = stageForEntryState(entry.entry_state);
        setStage(next);
        if (next === 'SOURCE_SELECTION') {
          setPendingCalibration(null);
        }
        return next;
      } catch (err) {
        console.error('[STATE] Could not resolve learner routing state:', err);
        setBootError(
          err instanceof Error
            ? err.message
            : 'The learning backend did not respond. Your progress is safe on the server.',
        );
        setStage('ERROR');
        return 'ERROR' as AppStage;
      }
    },
    [learnerId],
  );

  // Calibration gate on subject selection: any subject without a submitted
  // self-assessment (e.g. freshly uploaded material, or material ingested
  // before this gate existed) routes to strength rating + verification test
  // instead of showing default 30% mastery.
  //
  // There is no longer a "skip the gate for subjects loaded during resume"
  // escape hatch. That bypass is exactly what let an unverified learner reach
  // the dashboard with untouched default mastery (30%, 0 explored concepts),
  // because their subject had been restored and therefore treated as trusted.
  // The gate is now driven purely by server-reported entry state.
  const gateCheckedFor = useRef<string | null>(null);

  useEffect(() => {
    if (stage !== 'DASHBOARD' || !selectedSubject || pendingCalibration || resumeInitSession) return;
    const key = `${learnerId}:${selectedSubject.id}`;
    if (gateCheckedFor.current === key) return;
    gateCheckedFor.current = key;
    resolveStage(selectedSubject.id);
  }, [stage, selectedSubject, pendingCalibration, resumeInitSession, learnerId, resolveStage]);

  // Handle Onboarding Completion. Only reached once the server reports the
  // verification as complete -- the completion callback is no longer a
  // self-declared "I am done" signal from the client.
  const handleCompleteOnboarding = (subjectId: string) => {
    const sub = subjects.find((s) => s.id === subjectId) ?? subjects[0];
    setSelectedSubject(sub);
    setResumeInitSession(null);
    setPendingCalibration(null);
    gateCheckedFor.current = null;
    setActiveView('DASHBOARD');
    void resolveStage(subjectId);
  };

  // Calibration gate: no subject may enter learning without self-assessment +
  // diagnostic verification. Uncalibrated subjects route to the onboarding flow;
  // interrupted diagnostics resume where they left off.
  // For new uploads (forceOnboarding=true), always trigger onboarding regardless of calibration status.
  const openSubject = async (sub: Subject, targetView: 'DASHBOARD' | 'ATLAS' | 'PATH' | 'SOURCES' = 'ATLAS', forceOnboarding = false) => {
    setSelectedSubject(sub);
    gateCheckedFor.current = null;
    void ApiClient.setActiveSubject(learnerId, sub.id).catch(() => undefined);

    // For new uploads, force onboarding regardless of calibration status
    if (forceOnboarding) {
      setPendingCalibration(sub);
      setStage('CALIBRATION');
      return;
    }

    const next = await resolveStage(sub.id);
    if (next === 'ERROR') return; // explicit error + retry, never silently continue
    if (next === 'CALIBRATION') return;
    setActiveView(targetView);
  };

  // Handle Final Assessment Completion
  const handleFinalAssessmentComplete = (updatedMasteries: Record<string, number>) => {
    refreshSubjectData();
    const conceptNames = Object.keys(updatedMasteries).map((c) => c.replace(/_/g, ' ').toUpperCase()).join(', ');
    setKnowledgeChangedNotification(`FINAL ASSESSMENT EVALUATED // Masteries calibrated across: ${conceptNames.substring(0, 80)}...`);
    setTimeout(() => setKnowledgeChangedNotification(null), 6000);
  };

  // Trace Downstream Impact Algorithm
  const handleTraceImpact = (conceptId: string) => {
    if (!graphData) return;
    setIsTracingImpact(true);
    const dependents = graphData.concepts
      .filter((c) => c.prerequisites.includes(conceptId))
      .map((c) => c.concept_id);

    setImpactedConceptIds([conceptId, ...dependents]);
    setTimeout(() => {
      setIsTracingImpact(false);
    }, 4000);
  };

  // Handle "Knowledge Changed" Event
  const handleKnowledgeChanged = (updatedMasteries: Record<string, number>, conceptId: string) => {
    refreshSubjectData();
    const formattedConcept = conceptId.replace(/_/g, ' ').toUpperCase();
    const masteryVal = Math.round((updatedMasteries[conceptId] || 0.5) * 100);
    setKnowledgeChangedNotification(`KNOWLEDGE ATLAS CALIBRATED // ${formattedConcept} mastery calibrated to ${masteryVal}%.`);
    setTimeout(() => {
      setKnowledgeChangedNotification(null);
    }, 5000);
  };

  // Show a brief loading state while resolving server-authoritative state
  if (stage === 'BOOT') {
    return (
      <div className="min-h-screen universe-canvas flex items-center justify-center">
        <div className="text-center space-y-4 animate-pulse">
          <Orbit className="w-10 h-10 text-cyan-400 mx-auto animate-spin" />
          <p className="text-sm font-mono text-universe-slate">Restoring learning state...</p>
        </div>
      </div>
    );
  }

  // ERROR is a first-class state with a retry. It is deliberately NOT rendered
  // as the ingestion screen: "the backend did not answer" and "you have no
  // material yet" are different facts, and conflating them is what turned the
  // upload page into the generic fallback.
  if (stage === 'ERROR') {
    return (
      <div className="min-h-screen universe-canvas flex items-center justify-center px-6">
        <div className="max-w-lg text-center space-y-5">
          <div className="flex items-center justify-center gap-3">
            <AlertTriangle className="w-7 h-7 text-amber-400" />
            <h2 className="text-lg font-display font-bold text-universe-text">
              Could not load your learning state
            </h2>
          </div>
          <p className="text-sm text-universe-slate leading-relaxed">
            {bootError ?? 'The learning backend did not respond.'}
          </p>
          <p className="text-xs text-universe-slate/80 leading-relaxed">
            Nothing has been lost &mdash; your progress, sources and any in-progress verification are
            stored on the server. Retry to reconnect.
          </p>
          <button
            onClick={() => setBootAttempt((n) => n + 1)}
            className="inline-flex items-center gap-2 py-2.5 px-5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs hover:bg-cyan-300 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (stage === 'SOURCE_SELECTION' || stage === 'CALIBRATION') {
    return (
      <OnboardingWorkflow
        subjects={subjects}
        onCompleteOnboarding={handleCompleteOnboarding}
        resumeInitSession={resumeInitSession}
        initialSubject={resumeInitSession ? undefined : (pendingCalibration ?? (selectedSubject ?? undefined))}
        // SOURCE_SELECTION must never show the ingestion screen by accident:
        // the mode makes the distinction explicit so the calibration stages
        // (strength rating / verification) cannot render the upload panel.
        mode={stage === 'SOURCE_SELECTION' ? 'SOURCE_SELECTION' : 'CALIBRATION'}
        onSubjectsChanged={() => {
          setBootAttempt((n) => n + 1);
        }}
      />
    );
  }

  return (
    <div className="min-h-screen universe-canvas text-universe-text flex flex-col font-sans transition-colors duration-300 relative selection:bg-cyan-500/30 selection:text-cyan-200">
      
      {/* Top Futuristic Navigation Command Bar */}
      <TopNavbar
        subjects={subjects}
        selectedSubject={selectedSubject}
        onSelectSubject={(s) => openSubject(s, activeView)}
        activeView={activeView}
        onNavigate={setActiveView}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
      />

      {/* Main Workspace Universe Viewport */}
      <main className="flex-1 max-w-[1600px] w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        
        {/* Signature "Knowledge Changed" Cosmic Signal */}
        {knowledgeChangedNotification && (
          <div className="p-4 rounded-2xl flex items-center justify-between gap-3 animate-fade-in"
               style={{
                 background: 'linear-gradient(90deg, color-mix(in srgb, var(--accent-emerald) 50%, var(--panel-space)) 0%, color-mix(in srgb, var(--accent-cyan) 30%, var(--panel-space)) 50%, var(--panel-space) 100%)',
                 border: '1px solid var(--accent-emerald)',
                 boxShadow: '0 0 32px -4px color-mix(in srgb, var(--accent-emerald) 20%, transparent)'
               }}>
            <div className="flex items-center gap-3">
              <Zap className="w-5 h-5 animate-bounce" style={{ color: 'var(--accent-emerald)' }} />
              <span className="text-xs font-mono font-bold tracking-wider" style={{ color: 'var(--accent-emerald)' }}>
                {knowledgeChangedNotification}
              </span>
            </div>
            <span className="text-[10px] font-mono uppercase" style={{ color: 'color-mix(in srgb, var(--accent-emerald) 70%, transparent)' }}>
              BKT Updated
            </span>
          </div>
        )}

        {/* View 1: DASHBOARD (Knowledge Command Center) */}
        {activeView === 'DASHBOARD' && selectedSubject && (
          <Dashboard
            currentSubject={selectedSubject}
            progress={progress}
            gaps={gaps}
            nextTarget={nextTarget}
            onNavigateToAtlas={() => setActiveView('ATLAS')}
            onNavigateToPath={() => setActiveView('PATH')}
            onNavigateToSession={(cId) => {
              const c = graphData?.concepts.find((item) => item.concept_id === cId);
              if (c) setActiveStudyConcept(c);
            }}
            onNavigateToSources={() => setActiveView('SOURCES')}
            onStartFinalAssessment={() => setIsFinalAssessmentOpen(true)}
          />
        )}

        {/* View 2: LEARNING ATLAS (Constellation Map) */}
        {activeView === 'ATLAS' && graphData && (
          <div className="space-y-4 animate-fade-in">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Orbit className="w-5 h-5 text-cyan-400" />
                <h2 className="text-lg font-display font-bold text-white tracking-tight">
                  Knowledge Atlas Topology
                </h2>
              </div>

              <button
                onClick={() => setShowAccessibleAtlas(!showAccessibleAtlas)}
                className="text-xs font-mono text-cyan-400 hover:text-cyan-300 underline transition-colors"
              >
                {showAccessibleAtlas ? 'Show Interactive Neural Map' : 'Show Accessible Data Table'}
              </button>
            </div>

            {showAccessibleAtlas ? (
              <AccessibleAtlasView
                graphData={graphData}
                onSelectConcept={(c) => setSelectedConcept(c)}
              />
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
                <div className="lg:col-span-3">
                  <LearningAtlas
                    graphData={graphData}
                    activeTargetId={nextTarget?.concept_id}
                    selectedConceptId={selectedConcept?.concept_id}
                    onSelectConcept={(c) => setSelectedConcept(c)}
                    isXRayMode={isXRayMode}
                    onToggleXRay={() => setIsXRayMode(!isXRayMode)}
                    impactedConceptIds={impactedConceptIds}
                  />
                </div>

                <div className="space-y-4">
                  {selectedConcept ? (
                    <XRayInspector
                      concept={selectedConcept}
                      downstreamCount={
                        graphData.concepts.filter((c) => c.prerequisites.includes(selectedConcept.concept_id)).length
                      }
                      onTraceImpact={handleTraceImpact}
                      isTracing={isTracingImpact}
                    />
                  ) : (
                    <div className="universe-panel rounded-2xl p-6 text-center space-y-2">
                      <Sparkles className="w-6 h-6 text-cyan-400/60 mx-auto" />
                      <h4 className="text-xs font-display font-bold text-white">X-Ray Telemetry Standby</h4>
                      <p className="text-[11px] text-universe-slate font-sans leading-relaxed">
                        Select any conceptual node in the Knowledge Atlas to open real-time prerequisite tracing and downstream impact telemetry.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* View 3: LEARNING PATH TIMELINE (Expedition Vector) */}
        {activeView === 'PATH' && (
          <LearningPathTimeline
            nodes={pathNodes}
            activeTarget={nextTarget}
            onSelectConcept={(cId) => {
              let c = graphData?.concepts.find((item) => item.concept_id === cId);
              if (!c) {
                const node = pathNodes.find((n) => n.concept_id === cId);
                if (node) {
                  c = {
                    concept_id: node.concept_id,
                    name: node.concept_name || node.name || node.concept_id.replace(/_/g, ' '),
                    description: `Personalized learning milestone for ${node.concept_name || node.name}`,
                    definition: `Target concept: ${node.concept_name || node.name}`,
                    subject_id: selectedSubject?.id || '',
                    prerequisites: node.prerequisites || [],
                    mastery: node.mastery ?? node.estimated_mastery ?? 0.15,
                    status: (node.status as any) || 'AVAILABLE',
                    x: 0,
                    y: 0,
                  };
                }
              }
              if (c) setActiveStudyConcept(c);
            }}
          />
        )}

        {/* View 4: SOURCE LIBRARY (Grounded Ingestion Deck) */}
        {activeView === 'SOURCES' && (
          <SourceLibrary
            sources={sources}
            onReloadSources={reloadSubjectsAndSources}
            onSelectSubject={async (subjectId, isNewUpload = false) => {
              try {
                const subs = await ApiClient.getSubjects();
                setSubjects(subs);
                const sub = subs.find((s) => s.id === subjectId);
                if (sub) {
                  // For new uploads, force onboarding regardless of calibration status
                  // For existing materials, open directly in Atlas
                  await openSubject(sub, isNewUpload ? 'DASHBOARD' : 'ATLAS', isNewUpload);
                }
              } catch (err) {
                console.error('Failed to switch subject', err);
              }
            }}
          />
        )}
      </main>

      {/* Slide-Over Intelligence Drawer: Concept Inspector */}
      {selectedConcept && (
        <ConceptInspector
          concept={selectedConcept}
          onClose={() => setSelectedConcept(null)}
          onStartLearning={(cId) => {
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) {
              setSessionInitialTab('EXPLANATION');
              setActiveStudyConcept(c);
            }
            setSelectedConcept(null);
          }}
          onStartPractice={(cId) => {
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) {
              setSessionInitialTab('PRACTICE');
              setActiveStudyConcept(c);
            }
            setSelectedConcept(null);
          }}
          onAskTutor={(cId) => {
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) {
              setTutorConcept(c);
              setIsTutorOpen(true);
            }
          }}
          onTraceImpact={handleTraceImpact}
        />
      )}

      {/* Grounded AI Pedagogical Tutor Sidebar */}
      {isTutorOpen && selectedSubject && (
        <ContextualTutor
          concept={tutorConcept}
          learnerId={learnerId}
          subjectId={selectedSubject.id}
          onClose={() => setIsTutorOpen(false)}
        />
      )}

      {/* Focused Learning Studio Modal */}
      {activeStudyConcept && selectedSubject && (
        <LearningSession
          concept={activeStudyConcept}
          subject={selectedSubject}
          allConceptIds={graphData?.concepts.map((c) => c.concept_id) || [activeStudyConcept.concept_id]}
          learnerId={learnerId}
          initialTab={sessionInitialTab}
          onAskTutor={(cId) => {
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) {
              setTutorConcept(c);
              setIsTutorOpen(true);
            }
          }}
          onKnowledgeChanged={handleKnowledgeChanged}
          onCloseSession={() => setActiveStudyConcept(null)}
        />
      )}

      {/* Final Assessment Modal */}
      {isFinalAssessmentOpen && selectedSubject && (
        <FinalAssessment
          subject={selectedSubject}
          learnerId={learnerId}
          activeAssessmentId={activeAssessmentId}
          onComplete={handleFinalAssessmentComplete}
          onClose={() => {
            setIsFinalAssessmentOpen(false);
            setActiveAssessmentId(null);
          }}
        />
      )}

      {/* Global Cmd+K Command Palette Spotlight */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        concepts={graphData?.concepts || []}
        sources={sources}
        onSelectConcept={(c) => setSelectedConcept(c)}
        onNavigateToAtlas={() => setActiveView('ATLAS')}
        onNavigateToSources={() => setActiveView('SOURCES')}
        onAskTutor={(cId) => {
          const c = graphData?.concepts.find((item) => item.concept_id === cId);
          if (c) {
            setTutorConcept(c);
            setIsTutorOpen(true);
          }
        }}
      />
    </div>
  );
}
