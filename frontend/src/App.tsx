import { useState, useEffect, useCallback } from 'react';
import type { Subject, KnowledgeGraphData, LearnerProgress, KnowledgeGap, LearningPathNode, LearningTarget, ConceptNode, SourceDocument } from './api/client';
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
import { Zap, Sparkles, Orbit, BookOpen } from 'lucide-react';


export default function App() {
  const [learnerId] = useState<string>('student_alex');
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);
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

  // Calibration / Onboarding Flow State (optional, user-initiated or explicit)
  const [isCalibrationOpen, setIsCalibrationOpen] = useState<boolean>(false);
  const [pendingCalibration, setPendingCalibration] = useState<Subject | null>(null);
  const [resumeInitSession, setResumeInitSession] = useState<{ session_id: string; subject_id: string } | null>(null);

  // Signature "Knowledge Changed" Notification State
  const [knowledgeChangedNotification, setKnowledgeChangedNotification] = useState<string | null>(null);

  // 1. Initial Load: Start with Home Page immediately, fetch subjects, sources, and resumed learner state in background
  const reloadSubjectsAndSources = useCallback(async () => {
    try {
      const [subs, srcs, resumeData] = await Promise.all([
        ApiClient.getSubjects(),
        ApiClient.getSources(),
        ApiClient.resumeLearner(learnerId).catch(() => null),
      ]);
      setSubjects(subs);
      setSources(srcs);

      let targetSub: Subject | null = null;
      if (resumeData && resumeData.subject_id) {
        targetSub = subs.find((s) => s.id === resumeData.subject_id) || null;
      }
      if (!targetSub && subs.length > 0) {
        targetSub = subs[0];
      }

      if (targetSub) {
        setSelectedSubject((prev) => prev ?? targetSub);
      }
    } catch (err) {
      console.error('Failed to load initial data', err);
    }
  }, [learnerId]);

  useEffect(() => {
    reloadSubjectsAndSources();
  }, [reloadSubjectsAndSources]);

  // 2. Load Subject Data when subject changes or knowledge updates
  const refreshSubjectData = useCallback(async () => {
    if (!selectedSubject) return;
    try {
      const [graph, prog, pathGapRes] = await Promise.all([
        ApiClient.getSubjectGraph(selectedSubject.id, learnerId),
        ApiClient.getLearnerProgress(learnerId, selectedSubject.id),
        ApiClient.getPathAndGaps(learnerId, selectedSubject.id),
      ]);
      setGraphData(graph);
      setProgress(prog);
      setGaps(pathGapRes.gaps);
      setPathNodes(pathGapRes.learning_path.nodes);
      setNextTarget(pathGapRes.next_target);
    } catch (err) {
      console.error('Failed to refresh subject data', err);
    }
  }, [selectedSubject, learnerId]);

  useEffect(() => {
    if (selectedSubject) {
      refreshSubjectData();
    }
  }, [selectedSubject, refreshSubjectData]);

  // Handle Onboarding Completion
  const handleCompleteOnboarding = (subjectId: string) => {
    const sub = subjects.find((s) => s.id === subjectId) ?? subjects[0];
    setSelectedSubject(sub);
    setResumeInitSession(null);
    setPendingCalibration(null);
    setIsCalibrationOpen(false);
    setActiveView('DASHBOARD');
  };

  const openSubject = (sub: Subject, targetView: 'DASHBOARD' | 'ATLAS' | 'PATH' | 'SOURCES' = 'DASHBOARD') => {
    setSelectedSubject(sub);
    void ApiClient.setActiveSubject(learnerId, sub.id).catch(() => undefined);
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

  // Optional Full-screen Onboarding / Calibration if explicitly requested
  if (isCalibrationOpen) {
    return (
      <div className="min-h-screen universe-canvas text-universe-text flex flex-col font-sans transition-colors duration-300">
        <header className="sticky top-0 z-40 w-full border-b border-white/[0.07] bg-space-950/80 backdrop-blur-2xl px-5 lg:px-8 py-3">
          <div className="max-w-[1600px] mx-auto flex items-center justify-between">
            <button
              onClick={() => setIsCalibrationOpen(false)}
              className="px-4 py-2 rounded-xl bg-space-800 hover:bg-space-750 text-xs font-mono text-cyan-400 border border-cyan-500/20 flex items-center gap-2 transition-all cursor-pointer"
            >
              ← Back to Home / Dashboard
            </button>
            <span className="text-xs font-mono text-universe-slate uppercase tracking-wider">
              Diagnostic &amp; Calibration Mode
            </span>
          </div>
        </header>
        <main className="flex-1">
          <OnboardingWorkflow
            subjects={subjects}
            onCompleteOnboarding={handleCompleteOnboarding}
            resumeInitSession={resumeInitSession}
            initialSubject={pendingCalibration ?? (selectedSubject ?? undefined)}
            mode="CALIBRATION"
            forceSurvey={true}
            onSubjectsChanged={reloadSubjectsAndSources}
          />
        </main>
      </div>
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
        {activeView === 'DASHBOARD' && (
          selectedSubject ? (
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
          ) : (
            <div className="universe-panel rounded-3xl p-10 text-center space-y-5 max-w-xl mx-auto my-12 animate-fade-in border border-white/[0.08]">
              <div className="w-12 h-12 rounded-2xl bg-cyan-400/10 border border-cyan-400/30 flex items-center justify-center mx-auto text-cyan-400">
                <Sparkles className="w-6 h-6 animate-pulse" />
              </div>
              <h2 className="text-xl font-display font-bold text-white">Welcome to LearnSense Taproot</h2>
              <p className="text-sm text-universe-slate leading-relaxed font-sans">
                {subjects.length === 0
                  ? 'Your knowledge engine is ready. Upload textbook chapters or course materials in Sources to generate your interactive Knowledge Atlas.'
                  : 'Preparing your active subject dashboard...'}
              </p>
              <div className="pt-2 flex items-center justify-center gap-3">
                <button
                  onClick={() => setActiveView('SOURCES')}
                  className="px-6 py-2.5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs hover:bg-cyan-300 transition-all inline-flex items-center gap-2 cursor-pointer"
                >
                  <BookOpen className="w-4 h-4" />
                  <span>Open Sources &amp; Upload</span>
                </button>
              </div>
            </div>
          )
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
                const sub = subs.find((s) => s.id === subjectId) || {
                  id: subjectId,
                  title: subjectId.replace(/_/g, ' ').toUpperCase(),
                  concept_count: 0,
                  page_count: 1,
                  has_ekr: true,
                };
                setSelectedSubject(sub);
                void ApiClient.setActiveSubject(learnerId, sub.id).catch(() => undefined);
                if (isNewUpload) {
                  // After uploading, immediately launch the initial survey quiz & diagnostic assessment
                  setPendingCalibration(sub);
                  setIsCalibrationOpen(true);
                } else {
                  setActiveView('ATLAS');
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
