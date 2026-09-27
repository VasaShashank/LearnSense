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
import { Zap } from 'lucide-react';

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
    setKnowledgeChangedNotification(`Knowledge Atlas updated! Concept ${conceptId.replace(/_/g, ' ')} mastery is now ${Math.round((updatedMasteries[conceptId] || 0.5) * 100)}%.`);
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
    <div className={`min-h-screen ${theme} bg-slate-950 text-slate-100 flex flex-col font-sans transition-colors duration-300`}>
      {/* Top Navbar */}
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

      {/* Main Workspace Body */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {/* Signature "Knowledge Changed" Notification Banner */}
        {knowledgeChangedNotification && (
          <div className="p-4 rounded-2xl bg-gradient-to-r from-emerald-950 via-cyan-950 to-slate-900 border border-emerald-400/60 shadow-glow-emerald animate-pulse-glow flex items-center gap-3">
            <Zap className="w-5 h-5 text-emerald-400 fill-current animate-bounce" />
            <span className="text-xs font-mono font-bold text-emerald-200">
              {knowledgeChangedNotification}
            </span>
          </div>
        )}

        {/* View 1: DASHBOARD */}
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

        {/* View 2: LEARNING ATLAS MAP */}
        {activeView === 'ATLAS' && graphData && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-white tracking-tight">Interactive Learning Atlas</h2>
              <button
                onClick={() => setShowAccessibleAtlas(!showAccessibleAtlas)}
                className="text-xs font-mono text-cyan-400 hover:underline"
              >
                {showAccessibleAtlas ? 'Show Visual Map' : 'Show Accessible View'}
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
                    <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 text-center text-xs text-slate-400 font-mono">
                      Click any concept node on the Learning Atlas to open deep X-Ray inspection.
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* View 3: LEARNING PATH TIMELINE */}
        {activeView === 'PATH' && (
          <LearningPathTimeline
            nodes={pathNodes}
            activeTarget={nextTarget}
            onSelectConcept={(cId) => {
              const c = graphData?.concepts.find((item) => item.concept_id === cId);
              if (c) setActiveStudyConcept(c);
            }}
          />
        )}

        {/* View 4: SOURCE LIBRARY */}
        {activeView === 'SOURCES' && (
          <SourceLibrary
            sources={sources}
            onReloadSources={reloadSubjectsAndSources}
          />
        )}
      </main>

      {/* Slide-Over Drawers & Workspaces */}
      {selectedConcept && (
        <ConceptInspector
          concept={selectedConcept}
          onClose={() => setSelectedConcept(null)}
          onStartLearning={(cId) => {
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) setActiveStudyConcept(c);
            setSelectedConcept(null);
          }}
          onStartPractice={(cId) => {
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) setActiveStudyConcept(c);
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

      {/* Contextual AI Tutor Sidebar */}
      {isTutorOpen && selectedSubject && (
        <ContextualTutor
          concept={tutorConcept}
          learnerId={learnerId}
          subjectId={selectedSubject.id}
          onClose={() => setIsTutorOpen(false)}
        />
      )}

      {/* Focused Learning Session Modal */}
      {activeStudyConcept && selectedSubject && graphData && (
        <LearningSession
          concept={activeStudyConcept}
          subject={selectedSubject}
          allConceptIds={graphData.concepts.map((c) => c.concept_id)}
          learnerId={learnerId}
          onAskTutor={(cId) => {
            const c = graphData.concepts.find((item) => item.concept_id === cId);
            if (c) {
              setTutorConcept(c);
              setIsTutorOpen(true);
            }
          }}
          onKnowledgeChanged={handleKnowledgeChanged}
          onCloseSession={() => setActiveStudyConcept(null)}
        />
      )}

      {/* Global Cmd+K Command Palette */}
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
