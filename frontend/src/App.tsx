import { useState, useEffect, useCallback, useMemo } from 'react';
import type { Subject, KnowledgeGraphData, LearnerProgress, KnowledgeGap, LearningPathNode, LearningTarget, ConceptNode, TopicTerritory, SourceDocument } from './api/client';
import { ApiClient } from './api/client';
import { TopNavbar, type AppView } from './components/navigation/TopNavbar';
import { Dashboard } from './components/dashboard/Dashboard';
import { TeacherDashboard } from './components/teacher/TeacherDashboard';
import { InstitutionalPortal } from './components/institution/InstitutionalPortal';
import { PeerMarketplace } from './components/marketplace/PeerMarketplace';
import { LoginPersonaModal, PRESET_PERSONAS, type Persona } from './components/common/LoginPersonaModal';
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
import { getConceptDisplayName, registerConceptNameMap } from './utils/conceptName';


export default function App() {
  const [currentPersona, setCurrentPersona] = useState<Persona>(PRESET_PERSONAS[0]);
  const [isLoginModalOpen, setIsLoginModalOpen] = useState<boolean>(false);
  const learnerId = currentPersona.id;
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);

  // Default home view per role
  const getHomeView = (role: string): AppView => {
    if (role === 'TEACHER') return 'TEACHER';
    if (role === 'ADMIN') return 'INSTITUTION';
    return 'DASHBOARD';
  };

  const [activeView, setActiveView] = useState<AppView>(getHomeView(currentPersona.role));

  // Resume / Rehydration State
  const [graphData, setGraphData] = useState<KnowledgeGraphData | null>(null);
  const [progress, setProgress] = useState<LearnerProgress | null>(null);
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [pathNodes, setPathNodes] = useState<LearningPathNode[]>([]);
  const [nextTarget, setNextTarget] = useState<LearningTarget | null>(null);
  const [sources, setSources] = useState<SourceDocument[]>([]);

  // Interactivity States
  const [selectedConcept, setSelectedConcept] = useState<ConceptNode | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<TopicTerritory | null>(null);
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

  // Calibration / Onboarding Flow State
  const [isCalibrationOpen, setIsCalibrationOpen] = useState<boolean>(false);
  const [pendingCalibration, setPendingCalibration] = useState<Subject | null>(null);
  const [resumeInitSession, setResumeInitSession] = useState<{ session_id: string; subject_id: string } | null>(null);

  // "Knowledge Changed" Notification
  const [knowledgeChangedNotification, setKnowledgeChangedNotification] = useState<string | null>(null);

  // Comprehensive concept & topic name mapping for human-readable labels across the app
  const conceptMap = useMemo(() => {
    const map: Record<string, string> = {};
    (graphData?.concepts || []).forEach((c) => {
      if (c.concept_id) map[c.concept_id] = c.name || c.concept_id;
    });
    (graphData?.topics || []).forEach((t) => {
      if (t.id) map[t.id] = t.name || t.id;
    });
    (pathNodes || []).forEach((n) => {
      if (n.concept_id) map[n.concept_id] = n.concept_name || n.name || map[n.concept_id] || n.concept_id;
    });
    registerConceptNameMap(map);
    return map;
  }, [graphData, pathNodes]);

  // 1. Initial Load
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

  // 2. Load Subject Data
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

  const openSubject = (sub: Subject, targetView: AppView = 'DASHBOARD') => {
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

  // Trace Downstream Impact (Transitive DAG traversal for Subheadings and Concepts)
  const handleTraceImpact = useCallback((nodeId: string) => {
    if (!graphData) return;
    setIsTracingImpact(true);

    const isTopic = (graphData.topics || []).some((t) => t.id === nodeId);
    const impacted = new Set<string>([nodeId]);
    const queue = [nodeId];

    if (isTopic) {
      // Build adjacency list for topics from topic_relationships and topic.dependents
      const adj: Record<string, string[]> = {};
      (graphData.topics || []).forEach((t) => {
        adj[t.id] = [...(t.dependents || [])];
      });
      (graphData.topic_relationships || []).forEach((r) => {
        if (!adj[r.source]) adj[r.source] = [];
        if (!adj[r.source].includes(r.target)) adj[r.source].push(r.target);
      });

      while (queue.length > 0) {
        const curr = queue.shift()!;
        const neighbors = adj[curr] || [];
        for (const n of neighbors) {
          if (!impacted.has(n)) {
            impacted.add(n);
            queue.push(n);
          }
        }
      }
    } else {
      // Build adjacency list for concepts from relationships and concept.dependents
      const adj: Record<string, string[]> = {};
      (graphData.concepts || []).forEach((c) => {
        adj[c.concept_id] = [...(c.dependents || [])];
      });
      (graphData.relationships || []).forEach((r) => {
        if (!adj[r.source]) adj[r.source] = [];
        if (!adj[r.source].includes(r.target)) adj[r.source].push(r.target);
      });

      while (queue.length > 0) {
        const curr = queue.shift()!;
        const neighbors = adj[curr] || [];
        for (const n of neighbors) {
          if (!impacted.has(n)) {
            impacted.add(n);
            queue.push(n);
          }
        }
      }
    }

    setImpactedConceptIds(Array.from(impacted));
    setTimeout(() => {
      setIsTracingImpact(false);
    }, 6000);
  }, [graphData]);

  // Handle "Knowledge Changed" Event
  const handleKnowledgeChanged = useCallback((updatedMasteries: Record<string, number>, conceptId: string) => {
    refreshSubjectData();
    const formattedConcept = conceptId.replace(/_/g, ' ').toUpperCase();
    const masteryVal = Math.round((updatedMasteries[conceptId] || 0.5) * 100);
    setKnowledgeChangedNotification(`KNOWLEDGE ATLAS CALIBRATED // ${formattedConcept} mastery calibrated to ${masteryVal}%.`);
    setTimeout(() => {
      setKnowledgeChangedNotification(null);
    }, 5000);
  }, [refreshSubjectData]);

  // ──────────────────────────────────────────────
  // Role guard: validate active view on role change
  // ──────────────────────────────────────────────
  const allowedViews: Record<string, AppView[]> = {
    LEARNER: ['DASHBOARD', 'ATLAS', 'PATH', 'SOURCES', 'MARKETPLACE'],
    TEACHER: ['TEACHER', 'ATLAS', 'SOURCES'],
    ADMIN: ['INSTITUTION', 'CLASS_KT', 'TEACHER', 'ATLAS', 'SOURCES'],
  };

  const isViewAllowed = (view: AppView, role: string): boolean => {
    return (allowedViews[role] || []).includes(view);
  };

  const handleNavigate = (view: AppView) => {
    if (isViewAllowed(view, currentPersona.role)) {
      setActiveView(view);
    } else {
      setActiveView(getHomeView(currentPersona.role));
    }
  };

  // Optional Full-screen Onboarding / Calibration
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
      
      {/* Top Navigation — role-specific */}
      <TopNavbar
        subjects={subjects}
        selectedSubject={selectedSubject}
        onSelectSubject={(s) => openSubject(s, activeView)}
        activeView={activeView}
        onNavigate={handleNavigate}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        currentPersona={currentPersona}
        onOpenLoginModal={() => setIsLoginModalOpen(true)}
      />

      {/* Main Workspace */}
      <main className="flex-1 max-w-[1600px] w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        
        {/* "Knowledge Changed" Notification */}
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

        {/* ════════════════════════════════════════════════
            STUDENT VIEWS (LEARNER role only)
            ════════════════════════════════════════════════ */}

        {/* Student Dashboard */}
        {activeView === 'DASHBOARD' && currentPersona.role === 'LEARNER' && (
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

        {/* Student Learning Path */}
        {activeView === 'PATH' && currentPersona.role === 'LEARNER' && (
          <LearningPathTimeline
            nodes={pathNodes}
            activeTarget={nextTarget}
            conceptMap={conceptMap}
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

        {/* Student Peer Marketplace */}
        {activeView === 'MARKETPLACE' && currentPersona.role === 'LEARNER' && (
          <PeerMarketplace
            learnerId={learnerId}
            subjects={subjects}
            selectedSubject={selectedSubject}
          />
        )}

        {/* ════════════════════════════════════════════════
            SHARED VIEWS (all roles can access)
            ════════════════════════════════════════════════ */}

        {/* Knowledge Atlas — shared across all roles */}
        {activeView === 'ATLAS' && graphData && (
          <div className="space-y-4 animate-fade-in">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Orbit className="w-5 h-5 text-cyan-400" />
                <h2 className="text-lg font-display font-bold text-white tracking-tight">
                  Knowledge Atlas Topology
                </h2>
                {currentPersona.role !== 'LEARNER' && (
                  <span className="px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-400/30 text-purple-300 text-[10px] font-mono">
                    {currentPersona.role === 'TEACHER' ? 'Instructor View' : 'Admin View'}
                  </span>
                )}
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
                conceptMap={conceptMap}
                onSelectConcept={(c) => setSelectedConcept(c)}
              />
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
                <div className="lg:col-span-3">
                  <LearningAtlas
                    graphData={graphData}
                    activeTargetId={nextTarget?.concept_id}
                    nextTarget={nextTarget}
                    learnerId={learnerId}
                    selectedTopicId={selectedTopic?.id}
                    selectedConceptId={selectedConcept?.concept_id}
                    onSelectTopic={(t) => {
                      setSelectedTopic(t);
                      setSelectedConcept(null);
                    }}
                    onSelectConcept={(c) => {
                      setSelectedConcept(c);
                    }}
                    onStartLearning={(cId) => {
                      if (currentPersona.role !== 'LEARNER') return;
                      const c = graphData?.concepts.find((item) => item.concept_id === cId);
                      if (c) {
                        setSessionInitialTab('EXPLANATION');
                        setActiveStudyConcept(c);
                      }
                      setSelectedConcept(null);
                      setSelectedTopic(null);
                    }}
                    onStartPractice={(cId) => {
                      if (currentPersona.role !== 'LEARNER') return;
                      const c = graphData?.concepts.find((item) => item.concept_id === cId);
                      if (c) {
                        setSessionInitialTab('PRACTICE');
                        setActiveStudyConcept(c);
                      }
                      setSelectedConcept(null);
                      setSelectedTopic(null);
                    }}
                    isXRayMode={isXRayMode}
                    onToggleXRay={() => setIsXRayMode(!isXRayMode)}
                    impactedConceptIds={impactedConceptIds}
                    onTraceImpact={handleTraceImpact}
                  />
                </div>

                <div className="space-y-4">
                  {selectedConcept ? (
                    <XRayInspector
                      concept={selectedConcept}
                      downstreamCount={
                        (selectedConcept.dependents && selectedConcept.dependents.length > 0)
                          ? selectedConcept.dependents.length
                          : graphData.concepts.filter((c) => c.prerequisites.includes(selectedConcept.concept_id)).length
                      }
                      onTraceImpact={handleTraceImpact}
                      isTracing={isTracingImpact}
                    />
                  ) : selectedTopic ? (
                    <XRayInspector
                      topic={selectedTopic}
                      downstreamCount={selectedTopic.dependents?.length || 0}
                      onTraceImpact={handleTraceImpact}
                      isTracing={isTracingImpact}
                      onOpenLearningPlan={() => {
                        // Topic is already selected and opened
                      }}
                    />
                  ) : (
                    <div className="universe-panel rounded-2xl p-6 text-center space-y-2">
                      <Sparkles className="w-6 h-6 text-cyan-400/60 mx-auto" />
                      <h4 className="text-xs font-display font-bold text-white">X-Ray Telemetry Standby</h4>
                      <p className="text-[11px] text-universe-slate font-sans leading-relaxed">
                        Select any subheading or conceptual node in the Knowledge Atlas to open real-time prerequisite tracing and downstream impact telemetry.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Source Library — shared across all roles */}
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
                if (isNewUpload && currentPersona.role === 'LEARNER') {
                  // Only learners go through calibration after upload
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

        {/* ════════════════════════════════════════════════
            TEACHER VIEWS (TEACHER + ADMIN roles)
            ════════════════════════════════════════════════ */}

        {/* Teaching Optimizer & Student Insights */}
        {activeView === 'TEACHER' && (currentPersona.role === 'TEACHER' || currentPersona.role === 'ADMIN') && (
          <TeacherDashboard
            currentUserId={currentPersona.id}
            currentPersona={currentPersona}
            onNavigateToAtlas={() => setActiveView('ATLAS')}
          />
        )}

        {/* ════════════════════════════════════════════════
            B2B ADMIN VIEWS (ADMIN role only)
            ════════════════════════════════════════════════ */}

        {/* Institution Management Portal */}
        {activeView === 'INSTITUTION' && currentPersona.role === 'ADMIN' && (
          <InstitutionalPortal
            currentUserId={currentPersona.id}
          />
        )}

        {/* Class Knowledge State — B2B Admin drill-down into student KT per class */}
        {activeView === 'CLASS_KT' && currentPersona.role === 'ADMIN' && (
          <ClassKnowledgeView currentUserId={currentPersona.id} />
        )}
      </main>

      {/* ═══════════ Overlays & Modals (student-only where appropriate) ═══════════ */}

      {/* Concept & Subheading Learning Plan Inspector Drawer */}
      {(selectedConcept || selectedTopic) && (
        <ConceptInspector
          concept={selectedConcept}
          topic={selectedTopic}
          conceptMap={conceptMap}
          onClose={() => {
            setSelectedConcept(null);
            setSelectedTopic(null);
          }}
          onSelectConcept={(c) => setSelectedConcept(c)}
          onBackToTopic={() => setSelectedConcept(null)}
          onStartLearning={(cId) => {
            if (currentPersona.role !== 'LEARNER') return; // Only students can start learning
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) {
              setSessionInitialTab('EXPLANATION');
              setActiveStudyConcept(c);
            }
            setSelectedConcept(null);
            setSelectedTopic(null);
          }}
          onStartPractice={(cId) => {
            if (currentPersona.role !== 'LEARNER') return;
            const c = graphData?.concepts.find((item) => item.concept_id === cId);
            if (c) {
              setSessionInitialTab('PRACTICE');
              setActiveStudyConcept(c);
            }
            setSelectedConcept(null);
            setSelectedTopic(null);
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

      {/* AI Tutor — available to all roles for concept exploration */}
      {isTutorOpen && selectedSubject && (
        <ContextualTutor
          concept={tutorConcept}
          learnerId={learnerId}
          subjectId={selectedSubject.id}
          onClose={() => setIsTutorOpen(false)}
        />
      )}

      {/* Learning Session — Student only */}
      {activeStudyConcept && selectedSubject && currentPersona.role === 'LEARNER' && (
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

      {/* Final Assessment — Student only */}
      {isFinalAssessmentOpen && selectedSubject && currentPersona.role === 'LEARNER' && (
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

      {/* Command Palette */}
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

      {/* Login / Persona Switcher */}
      <LoginPersonaModal
        isOpen={isLoginModalOpen}
        onClose={() => setIsLoginModalOpen(false)}
        currentPersona={currentPersona}
        onSelectPersona={(persona) => {
          setCurrentPersona(persona);
          setActiveView(getHomeView(persona.role));
        }}
      />
    </div>
  );
}


/**
 * ClassKnowledgeView — B2B Admin feature.
 * Shows aggregate student KT per institutional class.
 * Extracted from the old TeacherDashboard's "OVERVIEW" tab.
 */
function ClassKnowledgeView({ currentUserId: _currentUserId }: { currentUserId: string }) {
  const [classes, setClasses] = useState<any[]>([]);
  const [selectedClassId, setSelectedClassId] = useState<string>('');
  const [knowledgeState, setKnowledgeState] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const clsList = await ApiClient.listClasses();
        setClasses(clsList);
        if (clsList.length > 0) setSelectedClassId(clsList[0].class_id);
      } catch (err: any) {
        setErrorMsg(err.message || 'Failed to load classes');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const fetchClassState = useCallback(async (classId: string) => {
    if (!classId) return;
    try {
      setLoading(true);
      setErrorMsg(null);
      const data = await ApiClient.getClassKnowledgeState(classId);
      setKnowledgeState(data);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to load class knowledge state');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedClassId) fetchClassState(selectedClassId);
  }, [selectedClassId, fetchClassState]);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl bg-gradient-to-r from-space-900/90 via-blue-950/30 to-space-900/90 border border-blue-500/20 backdrop-blur-xl shadow-[0_4px_30px_rgba(0,0,0,0.5)]">
        <div className="space-y-1">
          <span className="px-2.5 py-0.5 rounded-full bg-blue-500/10 border border-blue-400/30 text-blue-300 text-[11px] font-mono font-semibold uppercase tracking-wider">
            Class-Level Knowledge Tracing
          </span>
          <h1 className="text-2xl font-display font-bold text-white">
            Student Knowledge State by Class
          </h1>
          <p className="text-sm text-universe-slate max-w-2xl">
            Aggregate Bayesian mastery distributions, prerequisite bottlenecks, and misconception patterns across enrolled students in each class.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={selectedClassId}
            onChange={(e) => setSelectedClassId(e.target.value)}
            className="px-3.5 py-2 rounded-xl bg-space-800 border border-white/[0.12] text-white text-xs font-medium focus:outline-none focus:border-blue-400 cursor-pointer min-w-[220px]"
          >
            {classes.map((cls) => (
              <option key={cls.class_id} value={cls.class_id} className="bg-space-900">
                {cls.class_name} ({cls.enrolled_learner_ids?.length || 0} students)
              </option>
            ))}
          </select>

          <button
            onClick={() => fetchClassState(selectedClassId)}
            className="p-2.5 rounded-xl bg-space-800 hover:bg-space-750 border border-white/[0.08] text-universe-slate hover:text-blue-400 transition-colors"
          >
            <svg className={`w-4 h-4 ${loading ? 'animate-spin text-blue-400' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M3 22v-6h6" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
            </svg>
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/40 text-rose-300 text-xs flex items-center justify-between">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="hover:underline text-xs">Dismiss</button>
        </div>
      )}

      {knowledgeState && (
        <>
          {/* Quick Stats */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-2">Class Readiness</div>
              <div className="text-3xl font-display font-bold text-white">
                {(knowledgeState.overall_class_readiness * 100).toFixed(0)}%
              </div>
              <div className="mt-3 w-full bg-space-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-gradient-to-r from-cyan-500 to-blue-500 h-1.5 rounded-full"
                  style={{ width: `${Math.min(100, knowledgeState.overall_class_readiness * 100)}%` }}
                />
              </div>
            </div>

            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-2">Enrolled</div>
              <div className="text-3xl font-display font-bold text-white">{knowledgeState.total_enrolled}</div>
              <p className="text-[11px] text-universe-slate mt-1">Active: <span className="text-purple-300 font-mono">{knowledgeState.active_learners}</span></p>
            </div>

            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-2">Prerequisite Bottlenecks</div>
              <div className="text-3xl font-display font-bold text-amber-400">{knowledgeState.prerequisite_gap_clusters?.length || 0}</div>
            </div>

            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-2">Misconceptions</div>
              <div className="text-3xl font-display font-bold text-rose-400">{knowledgeState.misconception_clusters?.length || 0}</div>
            </div>
          </div>

          {/* Concept Mastery Distributions */}
          <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-5">
            <h3 className="text-base font-display font-semibold text-white">Concept Mastery Distributions</h3>
            <div className="flex items-center gap-4 text-[11px] font-mono text-universe-slate">
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-rose-500/80" /> Low (&lt;40%)</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-amber-500/80" /> Mid (40-70%)</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500/80" /> High (&gt;70%)</span>
            </div>

            <div className="space-y-3">
              {Object.entries(knowledgeState.concept_distributions || {}).map(([cid, dist]: [string, any]) => {
                const lowPct = (dist.low_mastery_pct || 0) * 100;
                const midPct = (dist.mid_mastery_pct || 0) * 100;
                const highPct = (dist.high_mastery_pct || 0) * 100;
                const meanM = (dist.mean_mastery || 0) * 100;
                const isFriction = lowPct >= 40;

                return (
                  <div key={cid} className={`p-4 rounded-xl border transition-all ${
                    isFriction ? 'bg-rose-950/20 border-rose-500/30' : 'bg-space-850/60 border-white/[0.06]'
                  }`}>
                    <div className="flex items-center justify-between gap-2 mb-2.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-display font-semibold text-white">
                          {getConceptDisplayName(dist?.canonical_name || dist?.concept_name || cid)}
                        </span>
                        {isFriction && (
                          <span className="px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-300 text-[10px] font-mono font-semibold">
                            ⚠️ Friction
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-universe-slate">
                        Mean: <strong className="text-white font-mono">{meanM.toFixed(1)}%</strong>
                      </span>
                    </div>
                    <div className="w-full h-3 bg-space-800 rounded-full flex overflow-hidden">
                      {lowPct > 0 && <div style={{ width: `${lowPct}%` }} className="bg-rose-500/80 h-full" />}
                      {midPct > 0 && <div style={{ width: `${midPct}%` }} className="bg-amber-500/80 h-full" />}
                      {highPct > 0 && <div style={{ width: `${highPct}%` }} className="bg-emerald-500/80 h-full" />}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
