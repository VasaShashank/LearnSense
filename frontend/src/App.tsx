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
import { ContextualTutor } from './components/tutor/ContextualTutor';
import { SourceLibrary } from './components/sources/SourceLibrary';
import { CommandPalette } from './components/palette/CommandPalette';
import { OnboardingWorkflow } from './components/onboarding/OnboardingWorkflow';
import { Zap, Sparkles, Orbit } from 'lucide-react';

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [learnerId] = useState<string>('student_alex');
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);
  const [isOnboarded, setIsOnboarded] = useState<boolean>(false);

  const [activeView, setActiveView] = useState<'DASHBOARD' | 'ATLAS' | 'PATH' | 'SOURCES'>('DASHBOARD');
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

  // Signature "Knowledge Changed" Notification State
  const [knowledgeChangedNotification, setKnowledgeChangedNotification] = useState<string | null>(null);

  // 1. Initial Load Subjects & Sources
  const reloadSubjectsAndSources = useCallback(async () => {
    try {
      const subs = await ApiClient.getSubjects();
      setSubjects(subs);
      if (subs.length > 0 && !selectedSubject) {
        setSelectedSubject(subs[0]);
      }
      const srcs = await ApiClient.getSources();
      setSources(srcs);
    } catch (err) {
      console.error('Failed to load initial data', err);
    }
  }, [selectedSubject]);

  useEffect(() => {
    reloadSubjectsAndSources();
  }, [reloadSubjectsAndSources]);

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
    if (isOnboarded && selectedSubject) {
      refreshSubjectData();
    }
  }, [isOnboarded, selectedSubject, refreshSubjectData]);

  // Handle Onboarding Completion
  const handleCompleteOnboarding = (subjectId: string) => {
    const sub = subjects.find((s) => s.id === subjectId) || subjects[0];
    setSelectedSubject(sub);
    setIsOnboarded(true);
    setActiveView('DASHBOARD');
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

  if (!isOnboarded) {
    return (
      <OnboardingWorkflow
        subjects={subjects}
        onCompleteOnboarding={handleCompleteOnboarding}
      />
    );
  }

  return (
    <div className={`min-h-screen ${theme} universe-canvas text-universe-text flex flex-col font-sans transition-colors duration-300 relative selection:bg-cyan-500/30 selection:text-cyan-200`}>
      
      {/* Top Futuristic Navigation Command Bar */}
      <TopNavbar
        subjects={subjects}
        selectedSubject={selectedSubject}
        onSelectSubject={(s) => setSelectedSubject(s)}
        activeView={activeView}
        onNavigate={setActiveView}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      />

      {/* Main Workspace Universe Viewport */}
      <main className="flex-1 max-w-[1600px] w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        
        {/* Signature "Knowledge Changed" Cosmic Signal */}
        {knowledgeChangedNotification && (
          <div className="p-4 rounded-2xl bg-gradient-to-r from-emerald-950/80 via-cyan-950/60 to-space-900 border border-emerald-500/50 shadow-[0_0_32px_rgba(16,185,129,0.2)] flex items-center justify-between gap-3 animate-fade-in">
            <div className="flex items-center gap-3">
              <Zap className="w-5 h-5 text-emerald-400 shrink-0 animate-bounce" />
              <span className="text-xs font-mono font-bold text-emerald-200 tracking-wider">
                {knowledgeChangedNotification}
              </span>
            </div>
            <span className="text-[10px] font-mono text-emerald-400/70 uppercase">
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
            onSelectSubject={async (subjectId) => {
              try {
                const subs = await ApiClient.getSubjects();
                setSubjects(subs);
                const sub = subs.find((s) => s.id === subjectId);
                if (sub) {
                  setSelectedSubject(sub);
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
