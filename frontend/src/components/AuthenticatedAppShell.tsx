import { useState, useEffect, useCallback, useMemo } from 'react';
import type {
  Subject,
  KnowledgeGraphData,
  LearnerProgress,
  KnowledgeGap,
  LearningPathNode,
  LearningTarget,
  ConceptNode,
  TopicTerritory,
  SourceDocument,
} from '../api/client';
import { ApiClient } from '../api/client';
import { TopNavbar, type AppView } from './navigation/TopNavbar';
import { Dashboard } from './dashboard/Dashboard';
import { TeacherDashboard } from './teacher/TeacherDashboard';
import { InstitutionalPortal } from './institution/InstitutionalPortal';
import { PeerMarketplace } from './marketplace/PeerMarketplace';
import { LearningAtlas } from './atlas/LearningAtlas';
import { AccessibleAtlasView } from './atlas/AccessibleAtlasView';
import { XRayInspector } from './atlas/XRayInspector';
import { ConceptInspector } from './inspector/ConceptInspector';
import { LearningPathTimeline } from './path/LearningPathTimeline';
import { LearningSession } from './session/LearningSession';
import { FinalAssessment } from './session/FinalAssessment';
import { ContextualTutor } from './tutor/ContextualTutor';
import { SourceLibrary } from './sources/SourceLibrary';
import { OnboardingWorkflow } from './onboarding/OnboardingWorkflow';
import { CommandPalette } from './palette/CommandPalette';
import { ClassKnowledgeView } from './institution/ClassKnowledgeView';
import { CurriculumDashboard } from './curriculum/CurriculumDashboard';
import type { Persona } from './common/LoginPersonaModal';
import { Zap, Sparkles, Orbit, BookOpen, X, Map, LogOut } from 'lucide-react';
import { registerConceptNameMap } from '../utils/conceptName';

export type LearnerResumeResponse = Awaited<ReturnType<typeof ApiClient.resumeLearner>>;
export type UserProfile = Awaited<ReturnType<typeof ApiClient.getCurrentUser>>;

export interface AcademicPersonaPreset {
  id: string;
  name: string;
  role: 'LEARNER' | 'TEACHER' | 'ADMIN';
  subrole: 'STUDENT' | 'INSTITUTIONAL_TEACHER' | 'INDEPENDENT_TEACHER' | 'ADMIN';
  title: string;
  avatar: string;
  org_name: string;
  email: string;
  description: string;
}

export const PRESET_ACADEMIC_ROLES: AcademicPersonaPreset[] = [
  {
    id: 'student_alex',
    name: 'Alex Rivera',
    role: 'LEARNER',
    subrole: 'STUDENT',
    title: 'Undergraduate Scholar',
    avatar: '👨‍🎓',
    org_name: 'Apex Institute of Science & Technology',
    email: 'alex.rivera@apex.edu',
    description: 'Student: Adaptive concept mastery, interactive quizzes, AI tutor, and learning paths.',
  },
  {
    id: 'prof_vance',
    name: 'Prof. Eleanor Vance',
    role: 'TEACHER',
    subrole: 'INSTITUTIONAL_TEACHER',
    title: 'Lead Instructor, Systems & DAA',
    avatar: '👩‍🏫',
    org_name: 'Apex Institute of Science & Technology',
    email: 'e.vance@apex.edu',
    description: 'Faculty Teacher: Class mastery heatmaps, student diagnostics, and pedagogical optimizer.',
  },
  {
    id: 'teacher_independent',
    name: 'Dr. Sarah Lin',
    role: 'TEACHER',
    subrole: 'INDEPENDENT_TEACHER',
    title: 'Independent Visiting Educator',
    avatar: '🧑‍🏫',
    org_name: 'Open Academic Community (Non-B2B)',
    email: 'sarah.lin@open-ed.org',
    description: 'Visiting Educator: Anonymized student telemetry and open-community curriculum design.',
  },
  {
    id: 'admin_sterling',
    name: 'Dr. Marcus Sterling',
    role: 'ADMIN',
    subrole: 'ADMIN',
    title: 'Dean of Academic Systems',
    avatar: '🏛️',
    org_name: 'Apex Institute of Science & Technology',
    email: 'm.sterling@apex.edu',
    description: 'Campus Admin: Department portal, student/teacher rosters, and Class Knowledge KT tracer.',
  },
];

export interface AuthenticatedAppShellProps {
  learnerId: string;
  userEmail: string;
  initialResume?: LearnerResumeResponse | null;
  onSignOut: () => void | Promise<void>;
}

export function AuthenticatedAppShell({
  learnerId,
  userEmail,
  initialResume,
  onSignOut,
}: AuthenticatedAppShellProps) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [activePersonaOverride, setActivePersonaOverride] = useState<AcademicPersonaPreset | null>(null);
  const [isUpdatingDbRole, setIsUpdatingDbRole] = useState(false);
  const [roleUpdateFeedback, setRoleUpdateFeedback] = useState<string | null>(null);
  const [isAccountModalOpen, setIsAccountModalOpen] = useState(false);
  const [displayNameInput, setDisplayNameInput] = useState('');
  const [isSavingName, setIsSavingName] = useState(false);
  const [inviteTokenInput, setInviteTokenInput] = useState('');
  const [inviteFeedback, setInviteFeedback] = useState<string | null>(null);
  const [isCalibrationOpen, setIsCalibrationOpen] = useState<boolean>(false);
  const [pendingCalibration, setPendingCalibration] = useState<Subject | null>(null);

  // Apply initial role preference if chosen during registration or sign-in
  useEffect(() => {
    const pendingRole = localStorage.getItem('learnsense_initial_role');
    if (pendingRole) {
      localStorage.removeItem('learnsense_initial_role');
      const orgName = pendingRole === 'LEARNER' ? 'Individual Scholar' : 'Apex Institute of Science & Technology';
      ApiClient.updateRole(pendingRole, orgName)
        .then(() => ApiClient.getCurrentUser())
        .then((me) => {
          if (me) {
            setProfile(me);
            if (pendingRole === 'TEACHER') setActiveView('TEACHER');
            else if (pendingRole === 'ADMIN') setActiveView('INSTITUTION');
            else setActiveView('DASHBOARD');
          }
        })
        .catch((err) => console.warn('Could not set initial role', err));
    }
  }, []);

  // Fetch current user profile & memberships
  useEffect(() => {
    let active = true;
    ApiClient.getCurrentUser()
      .then((me) => {
        if (!active || !me) return;
        setProfile(me);
        setDisplayNameInput(me.display_name || '');
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // Compute dynamic Persona object from authentic platform identity or active persona override
  const currentPersona: Persona = useMemo(() => {
    if (activePersonaOverride) {
      return {
        id: activePersonaOverride.id,
        name: activePersonaOverride.name,
        role: activePersonaOverride.role,
        title: activePersonaOverride.title,
        avatar: activePersonaOverride.avatar,
        org_name: activePersonaOverride.org_name,
        email: activePersonaOverride.email,
      };
    }
    const primary = profile?.memberships?.[0];
    const role = (primary?.role as any) || 'LEARNER';
    const roleFormatted = role === 'ADMIN' ? 'ADMIN' : role === 'TEACHER' ? 'TEACHER' : 'LEARNER';
    return {
      id: learnerId,
      name: profile?.display_name || userEmail.split('@')[0],
      role: roleFormatted,
      title: roleFormatted === 'ADMIN' ? 'Campus Administrator' : roleFormatted === 'TEACHER' ? 'Faculty Instructor' : 'Undergraduate Scholar',
      avatar: roleFormatted === 'ADMIN' ? '🏛️' : roleFormatted === 'TEACHER' ? '👩‍🏫' : '👨‍🎓',
      org_name: primary?.org_name || 'Individual Scholar',
      email: userEmail,
    };
  }, [activePersonaOverride, learnerId, profile, userEmail]);

  // Default home view per role
  const getHomeView = useCallback((role: string): AppView => {
    if (role === 'TEACHER') return 'TEACHER';
    if (role === 'ADMIN') return 'INSTITUTION';
    return 'DASHBOARD';
  }, []);

  const [activeView, setActiveView] = useState<AppView>(getHomeView(currentPersona.role));

  // Sync active view when persona role resolves from backend
  useEffect(() => {
    setActiveView((prev) => {
      if (currentPersona.role === 'TEACHER' && prev === 'DASHBOARD') return 'TEACHER';
      if (currentPersona.role === 'ADMIN' && prev === 'DASHBOARD') return 'INSTITUTION';
      return prev;
    });
  }, [currentPersona.role]);

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);

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

  // "Knowledge Changed" Notification
  const [knowledgeChangedNotification, setKnowledgeChangedNotification] = useState<string | null>(null);

  // Comprehensive concept & topic name mapping
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

  // Initial Load of Subjects and Sources
  const reloadSubjectsAndSources = useCallback(async () => {
    try {
      const [subs, srcs, resumeData] = await Promise.all([
        ApiClient.getSubjects(),
        ApiClient.getSources(),
        initialResume ? Promise.resolve(initialResume) : ApiClient.resumeLearner(learnerId).catch(() => null),
      ]);
      setSubjects(subs);
      setSources(srcs);

      let targetSub: Subject | null = null;
      if (resumeData && resumeData.subject_id) {
        targetSub = subs.find((s: Subject) => s.id === resumeData.subject_id) || null;
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
  }, [learnerId, initialResume]);

  useEffect(() => {
    reloadSubjectsAndSources();
  }, [reloadSubjectsAndSources]);

  // Load Subject Graph and Progress
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

  // Handle Final Assessment Completion
  const handleFinalAssessmentComplete = (updatedMasteries: Record<string, number>) => {
    refreshSubjectData();
    const conceptNames = Object.keys(updatedMasteries).map((c) => c.replace(/_/g, ' ').toUpperCase()).join(', ');
    setKnowledgeChangedNotification(`FINAL ASSESSMENT EVALUATED // Masteries calibrated across: ${conceptNames.substring(0, 80)}...`);
    setTimeout(() => setKnowledgeChangedNotification(null), 6000);
  };

  // Trace Downstream Impact
  const handleTraceImpact = useCallback((nodeId: string) => {
    if (!graphData) return;
    setIsTracingImpact(true);

    const isTopic = (graphData.topics || []).some((t) => t.id === nodeId);
    const impacted = new Set<string>([nodeId]);
    const queue = [nodeId];

    if (isTopic) {
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

  // Role guard
  const allowedViews: Record<string, AppView[]> = {
    LEARNER: ['DASHBOARD', 'ATLAS', 'PATH', 'SOURCES', 'MARKETPLACE'],
    TEACHER: ['TEACHER', 'CURRICULUM', 'ATLAS', 'SOURCES'],
    ADMIN: ['INSTITUTION', 'CLASS_KT', 'TEACHER', 'CURRICULUM', 'ATLAS', 'SOURCES'],
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

  // Profile update handler
  const handleSaveDisplayName = async () => {
    if (!displayNameInput.trim()) return;
    setIsSavingName(true);
    try {
      const updated = await ApiClient.updateProfile({ display_name: displayNameInput.trim() });
      setProfile((prev) => (prev ? { ...prev, display_name: updated.display_name ?? prev.display_name } : null));
    } catch (err) {
      console.error('Failed to update name', err);
    } finally {
      setIsSavingName(false);
    }
  };

  // Switch between academic personas
  const handleSwitchPersona = (preset: AcademicPersonaPreset | null) => {
    setActivePersonaOverride(preset);
    if (preset) {
      if (preset.role === 'TEACHER') {
        setActiveView('TEACHER');
      } else if (preset.role === 'ADMIN') {
        setActiveView('INSTITUTION');
      } else {
        setActiveView('DASHBOARD');
      }
    } else {
      const primary = profile?.memberships?.[0];
      const role = primary?.role || 'LEARNER';
      if (role === 'TEACHER') setActiveView('TEACHER');
      else if (role === 'ADMIN') setActiveView('INSTITUTION');
      else setActiveView('DASHBOARD');
    }
  };

  // Update real user role in live PostgreSQL database or switch preview workspace
  const handleUpdateDatabaseRole = async (targetRole: 'LEARNER' | 'TEACHER' | 'ADMIN') => {
    setIsUpdatingDbRole(true);
    setRoleUpdateFeedback(null);
    try {
      const orgName = targetRole === 'LEARNER' ? 'Individual Scholar' : 'Apex Institute of Science & Technology';
      await ApiClient.updateRole(targetRole, orgName);
      const updated = await ApiClient.getCurrentUser();
      if (updated) {
        setProfile(updated);
      }
      setActivePersonaOverride(null);
      if (targetRole === 'TEACHER') setActiveView('TEACHER');
      else if (targetRole === 'ADMIN') setActiveView('INSTITUTION');
      else setActiveView('DASHBOARD');
      setRoleUpdateFeedback(`Account role updated to ${targetRole}!`);
    } catch (err: any) {
      // If the backend prevents privilege self-escalation (403 for students without an institutional appointment),
      // switch to the designated academic persona preview mode so the workspace shifts seamlessly.
      const fallbackPersona = PRESET_ACADEMIC_ROLES.find((p) => p.role === targetRole);
      if (fallbackPersona) {
        setActivePersonaOverride(fallbackPersona);
        if (targetRole === 'TEACHER') setActiveView('TEACHER');
        else if (targetRole === 'ADMIN') setActiveView('INSTITUTION');
        else setActiveView('DASHBOARD');
        setRoleUpdateFeedback(`Switched to ${fallbackPersona.title} (${fallbackPersona.name}) preview workspace.`);
      } else {
        if (targetRole === 'LEARNER') {
          setActivePersonaOverride(null);
          setActiveView('DASHBOARD');
        }
        setRoleUpdateFeedback(err?.message || 'Failed to update database role.');
      }
    } finally {
      setIsUpdatingDbRole(false);
    }
  };

  // Accept invitation handler
  const handleAcceptInvite = async () => {
    if (!inviteTokenInput.trim()) return;
    setInviteFeedback(null);
    try {
      await ApiClient.acceptInvitation(inviteTokenInput.trim());
      setInviteFeedback('Invitation accepted successfully! Reloading profile...');
      setInviteTokenInput('');
      const me = await ApiClient.getCurrentUser();
      if (me) setProfile(me);
    } catch (err: any) {
      setInviteFeedback(err.message || 'Failed to accept invitation.');
    }
  };

  // Full-screen Starting Diagnostic & Calibration Mode
  if (isCalibrationOpen) {
    return (
      <div className="min-h-screen universe-canvas text-universe-text flex flex-col font-sans transition-colors duration-300">
        <header className="sticky top-0 z-40 w-full border-b border-white/[0.07] bg-space-950/80 backdrop-blur-2xl px-5 lg:px-8 py-3">
          <div className="max-w-[1600px] mx-auto flex items-center justify-between">
            <button
              onClick={() => {
                setIsCalibrationOpen(false);
                setPendingCalibration(null);
                setActiveView('DASHBOARD');
              }}
              className="px-4 py-2 rounded-xl bg-space-800 hover:bg-space-750 text-xs font-mono text-cyan-400 border border-cyan-500/20 flex items-center gap-2 transition-all cursor-pointer"
            >
              ← Back to Dashboard
            </button>
            <span className="text-xs font-mono text-universe-slate uppercase tracking-wider">
              Starting Diagnostic &amp; Knowledge Calibration
            </span>
          </div>
        </header>
        <main className="flex-1">
          <OnboardingWorkflow
            subjects={subjects}
            learnerId={currentPersona.id || learnerId}
            onCompleteOnboarding={(subId) => {
              const sub = subjects.find((s) => s.id === subId) ?? (pendingCalibration ?? selectedSubject);
              if (sub) setSelectedSubject(sub);
              setPendingCalibration(null);
              setIsCalibrationOpen(false);
              refreshSubjectData();
              setKnowledgeChangedNotification('DIAGNOSTIC TEST COMPLETE // Knowledge tracing calibrated. Adaptive curriculum personalized!');
              setTimeout(() => setKnowledgeChangedNotification(null), 8000);
              setActiveView('DASHBOARD');
            }}
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
    <div className="min-h-screen universe-canvas text-universe-text flex flex-col font-sans transition-colors duration-300">
      {/* Top Navigation */}
      <TopNavbar
        subjects={subjects}
        selectedSubject={selectedSubject}
        onSelectSubject={(sub) => {
          setSelectedSubject(sub);
          void ApiClient.setActiveSubject(learnerId, sub.id).catch(() => undefined);
        }}
        activeView={activeView}
        onNavigate={handleNavigate}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        currentPersona={currentPersona}
        onOpenLoginModal={() => setIsAccountModalOpen(true)}
        onSignOut={onSignOut}
        onSwitchRole={handleUpdateDatabaseRole}
      />

      {/* Main Content Viewport */}
      <main className="flex-1 max-w-[1600px] w-full mx-auto px-5 lg:px-8 py-6">
        {/* Knowledge Changed Notification Banner */}
        {knowledgeChangedNotification && (
          <div
            className="mb-6 p-4 rounded-2xl flex items-center justify-between gap-4 animate-fade-in"
            style={{
              backgroundColor: 'color-mix(in srgb, var(--accent-emerald) 8%, var(--space-900))',
              border: '1px solid var(--accent-emerald)',
              boxShadow: '0 0 32px -4px color-mix(in srgb, var(--accent-emerald) 20%, transparent)',
            }}
          >
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

        {/* 1. Student Dashboard */}
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
              onStartDiagnostic={() => {
                setPendingCalibration(selectedSubject);
                setIsCalibrationOpen(true);
              }}
            />
          ) : (
            <div className="universe-panel rounded-3xl p-10 text-center space-y-5 max-w-xl mx-auto my-12 animate-fade-in border border-white/[0.08]">
              <div className="w-12 h-12 rounded-2xl bg-cyan-400/10 border border-cyan-400/30 flex items-center justify-center mx-auto text-cyan-400">
                <Sparkles className="w-6 h-6 animate-pulse" />
              </div>
              <h2 className="text-xl font-display font-bold text-white">Welcome to LearnSense</h2>
              <p className="text-sm text-universe-slate leading-relaxed font-sans">
                {subjects.length === 0
                  ? 'Your knowledge engine is ready. Upload textbook materials in Sources to generate your interactive Knowledge Atlas.'
                  : 'Loading active subject curriculum...'}
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

        {/* 2. Student Learning Path */}
        {activeView === 'PATH' && currentPersona.role === 'LEARNER' && (
          !selectedSubject || pathNodes.length === 0 ? (
            <div className="universe-panel rounded-3xl p-10 text-center space-y-5 max-w-xl mx-auto my-12 animate-fade-in border border-white/[0.08]">
              <div className="w-12 h-12 rounded-2xl bg-cyan-400/10 border border-cyan-400/30 flex items-center justify-center mx-auto text-cyan-400">
                <Map className="w-6 h-6 animate-pulse" />
              </div>
              <h2 className="text-xl font-display font-bold text-white">No Learning Path Generated Yet</h2>
              <p className="text-sm text-universe-slate leading-relaxed font-sans">
                {!selectedSubject
                  ? 'Ingest textbook chapters or select a course in Sources to construct your personalized prerequisite learning sequence.'
                  : `Generating adaptive prerequisite learning vector for ${selectedSubject.title}...`}
              </p>
              <div className="pt-2 flex items-center justify-center gap-3">
                <button
                  onClick={() => setActiveView('SOURCES')}
                  className="px-6 py-2.5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs hover:bg-cyan-300 transition-all inline-flex items-center gap-2 cursor-pointer shadow-[0_0_20px_rgba(0,240,255,0.2)]"
                >
                  <BookOpen className="w-4 h-4" />
                  <span>Open Sources &amp; Ingest Material</span>
                </button>
              </div>
            </div>
          ) : (
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
                      description: `Personalized milestone for ${node.concept_name || node.name}`,
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
          )
        )}

        {/* 3. Student Peer Marketplace */}
        {activeView === 'MARKETPLACE' && currentPersona.role === 'LEARNER' && (
          <PeerMarketplace
            learnerId={learnerId}
            subjects={subjects}
            selectedSubject={selectedSubject}
          />
        )}

        {/* 4. Knowledge Atlas (Shared across all roles) */}
        {activeView === 'ATLAS' && (
          !selectedSubject ? (
            <div className="universe-panel rounded-3xl p-10 text-center space-y-5 max-w-xl mx-auto my-12 animate-fade-in border border-white/[0.08]">
              <div className="w-12 h-12 rounded-2xl bg-cyan-400/10 border border-cyan-400/30 flex items-center justify-center mx-auto text-cyan-400">
                <Orbit className="w-6 h-6 animate-pulse" />
              </div>
              <h2 className="text-xl font-display font-bold text-white">No Subject Selected</h2>
              <p className="text-sm text-universe-slate leading-relaxed font-sans">
                {subjects.length === 0
                  ? 'Your knowledge engine is ready. Ingest textbook chapters or course materials in Sources to generate your interactive Knowledge Atlas.'
                  : 'Select a subject from the selector above or open Sources to explore existing material.'}
              </p>
              <div className="pt-2 flex items-center justify-center gap-3">
                {subjects.length > 0 && (
                  <button
                    onClick={() => setSelectedSubject(subjects[0])}
                    className="px-6 py-2.5 rounded-xl bg-cyan-400 text-space-950 font-display font-bold text-xs hover:bg-cyan-300 transition-all inline-flex items-center gap-2 cursor-pointer shadow-[0_0_20px_rgba(0,240,255,0.2)]"
                  >
                    <Orbit className="w-4 h-4" />
                    <span>Load {subjects[0].title}</span>
                  </button>
                )}
                <button
                  onClick={() => setActiveView('SOURCES')}
                  className="px-6 py-2.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.12] border border-white/[0.1] text-white font-display font-bold text-xs transition-all inline-flex items-center gap-2 cursor-pointer"
                >
                  <BookOpen className="w-4 h-4" />
                  <span>Open Sources &amp; Ingest PDF</span>
                </button>
              </div>
            </div>
          ) : !graphData ? (
            <div className="universe-panel rounded-3xl p-10 text-center space-y-5 max-w-md mx-auto my-12 animate-fade-in border border-white/[0.08]">
              <div className="w-12 h-12 rounded-2xl bg-cyan-400/10 border border-cyan-400/30 flex items-center justify-center mx-auto text-cyan-400">
                <Orbit className="w-6 h-6 animate-spin" />
              </div>
              <h3 className="text-lg font-display font-bold text-white">Initializing Knowledge Atlas</h3>
              <p className="text-xs text-universe-slate font-sans">
                Rendering neural topology for <span className="text-cyan-300 font-medium">{selectedSubject.title}</span>...
              </p>
            </div>
          ) : (
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
                        onOpenLearningPlan={() => {}}
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
          )
        )}

        {/* 5. Source Library (Shared across all roles) */}
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

        {/* 6. Teacher Dashboard (TEACHER + ADMIN roles) */}
        {activeView === 'TEACHER' && (currentPersona.role === 'TEACHER' || currentPersona.role === 'ADMIN') && (
          <TeacherDashboard
            currentUserId={currentPersona.id}
            currentPersona={currentPersona}
            onNavigateToAtlas={() => setActiveView('ATLAS')}
            onNavigateToCurriculum={() => setActiveView('CURRICULUM')}
          />
        )}

        {/* Curriculum Review & Governance Dashboard (TEACHER + ADMIN roles) */}
        {activeView === 'CURRICULUM' && (currentPersona.role === 'TEACHER' || currentPersona.role === 'ADMIN') && (
          <CurriculumDashboard
            currentPersona={currentPersona}
            onNavigateToAtlas={() => setActiveView('ATLAS')}
          />
        )}

        {/* 7. Institutional Portal (ADMIN role only) */}
        {activeView === 'INSTITUTION' && currentPersona.role === 'ADMIN' && (
          <InstitutionalPortal currentUserId={currentPersona.id} />
        )}

        {/* 8. Class Knowledge View (ADMIN role only) */}
        {activeView === 'CLASS_KT' && currentPersona.role === 'ADMIN' && (
          <ClassKnowledgeView currentUserId={currentPersona.id} />
        )}
      </main>

      {/* ═══════════ Overlays & Drawers ═══════════ */}

      {/* Concept & Subheading Inspector Drawer */}
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

      {/* AI Contextual Tutor */}
      {isTutorOpen && selectedSubject && (
        <ContextualTutor
          concept={tutorConcept}
          learnerId={learnerId}
          subjectId={selectedSubject.id}
          onClose={() => setIsTutorOpen(false)}
        />
      )}

      {/* Interactive Learning Session */}
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

      {/* Final Assessment */}
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

      {/* Account Profile, Role & Persona Switcher Modal */}
      {isAccountModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-fade-in">
          <div className="w-full max-w-xl max-h-[90vh] overflow-y-auto rounded-3xl bg-space-900 border border-white/[0.12] p-6 shadow-2xl space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
              <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-2xl bg-cyan-500/10 border border-cyan-400/30 flex items-center justify-center text-2xl shadow-inner">
                  {currentPersona.avatar}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-display font-bold text-white text-base">{currentPersona.name}</h3>
                    <span className="font-mono text-[10px] font-bold px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-400/30 uppercase">
                      {currentPersona.role}
                    </span>
                  </div>
                  <p className="text-xs text-universe-slate font-mono">{currentPersona.email}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsAccountModalOpen(false)}
                className="p-1.5 rounded-xl text-universe-slate hover:text-white hover:bg-space-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Active Override Banner if applicable */}
            {activePersonaOverride && (
              <div className="flex items-center justify-between p-3 rounded-2xl bg-cyan-500/10 border border-cyan-400/30 text-xs">
                <div className="text-cyan-200">
                  <span className="font-semibold text-white">Simulation Active:</span> Viewing workspace as {activePersonaOverride.name} ({activePersonaOverride.title})
                </div>
                <button
                  type="button"
                  onClick={() => handleSwitchPersona(null)}
                  className="px-2.5 py-1 rounded-lg bg-cyan-500 text-space-950 font-bold text-[11px] hover:bg-cyan-400 transition-all shrink-0 ml-2"
                >
                  Reset to My Account
                </button>
              </div>
            )}

            {/* 1. Academic Persona Switcher */}
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-universe-slate uppercase tracking-wider">
                  Select Academic Role / Demo Persona
                </label>
                <span className="text-[10px] font-mono text-cyan-400">1-click workspace switch</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {PRESET_ACADEMIC_ROLES.map((preset) => {
                  const isCurrent = activePersonaOverride?.id === preset.id || (!activePersonaOverride && currentPersona.id === preset.id);
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => handleSwitchPersona(preset)}
                      className={`p-3 rounded-2xl border text-left flex flex-col gap-1 transition-all ${
                        isCurrent
                          ? 'border-cyan-400 bg-cyan-500/15 text-white ring-1 ring-cyan-400/50 shadow-md'
                          : 'border-white/[0.08] bg-space-950/60 text-universe-slate hover:border-white/20 hover:text-white hover:bg-space-850'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xl">{preset.avatar}</span>
                          <div>
                            <div className="text-xs font-bold text-white leading-tight">{preset.name}</div>
                            <div className="text-[10px] text-cyan-300 font-mono">{preset.role}</div>
                          </div>
                        </div>
                        {isCurrent && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-cyan-400 text-space-950 font-bold">
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-universe-slate line-clamp-2 mt-1 leading-normal">
                        {preset.description}
                      </p>
                    </button>
                  );
                })}
              </div>
              {activePersonaOverride && (
                <button
                  type="button"
                  onClick={() => handleSwitchPersona(null)}
                  className="w-full py-2 rounded-xl border border-white/[0.1] bg-space-950/80 hover:bg-space-800 text-xs text-white font-medium transition-all"
                >
                  👤 Switch back to My Authenticated Identity ({userEmail})
                </button>
              )}
            </div>

            {/* 2. Live Database Role Promotion */}
            <div className="p-4 rounded-2xl bg-space-950/70 border border-white/[0.08] space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-semibold text-white">Live PostgreSQL Account Role</h4>
                  <p className="text-[11px] text-universe-slate">
                    Promote your authenticated Supabase identity in the remote database:
                  </p>
                </div>
                <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-400/30 uppercase">
                  {profile?.memberships?.[0]?.role || 'LEARNER'}
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={isUpdatingDbRole}
                  onClick={() => handleUpdateDatabaseRole('LEARNER')}
                  className="flex-1 min-w-[120px] py-2 px-3 rounded-xl border border-white/[0.1] bg-space-850 hover:border-cyan-400/40 text-xs font-medium text-white disabled:opacity-50 flex items-center justify-center gap-1.5 transition-all"
                >
                  <span>👨‍🎓</span> Student
                </button>
                <button
                  type="button"
                  disabled={isUpdatingDbRole}
                  onClick={() => handleUpdateDatabaseRole('TEACHER')}
                  className="flex-1 min-w-[120px] py-2 px-3 rounded-xl border border-white/[0.1] bg-space-850 hover:border-purple-400/40 text-xs font-medium text-white disabled:opacity-50 flex items-center justify-center gap-1.5 transition-all"
                >
                  <span>👩‍🏫</span> Teacher
                </button>
                <button
                  type="button"
                  disabled={isUpdatingDbRole}
                  onClick={() => handleUpdateDatabaseRole('ADMIN')}
                  className="flex-1 min-w-[120px] py-2 px-3 rounded-xl border border-white/[0.1] bg-space-850 hover:border-blue-400/40 text-xs font-medium text-white disabled:opacity-50 flex items-center justify-center gap-1.5 transition-all"
                >
                  <span>🏛️</span> Administrator
                </button>
              </div>

              {roleUpdateFeedback && (
                <p className="text-xs text-cyan-300 font-mono mt-1">{roleUpdateFeedback}</p>
              )}
            </div>

            {/* 3. Display Name Edit */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-universe-slate uppercase tracking-wider">Display Name</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={displayNameInput}
                  onChange={(e) => setDisplayNameInput(e.target.value)}
                  placeholder="Your display name"
                  className="flex-1 rounded-xl border border-white/[0.12] bg-space-800 px-3.5 py-2 text-sm text-white focus:outline-none focus:border-cyan-400"
                />
                <button
                  type="button"
                  onClick={handleSaveDisplayName}
                  disabled={isSavingName}
                  className="rounded-xl bg-cyan-500 px-4 py-2 text-xs font-bold text-space-950 hover:bg-cyan-400 disabled:opacity-60 transition-colors"
                >
                  {isSavingName ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>

            {/* 4. Canonical Learner Identity */}
            <div className="rounded-2xl bg-space-950/60 border border-white/[0.08] p-4 text-xs space-y-1">
              <div className="text-universe-slate font-medium">Server Canonical Learner ID</div>
              <div className="font-mono text-cyan-300 break-all">{learnerId}</div>
              <div className="text-[11px] text-universe-slate pt-1">
                Database Role: <span className="font-bold text-white uppercase">{profile?.memberships?.[0]?.role || 'LEARNER'}</span> | Organization: <span className="text-white">{profile?.memberships?.[0]?.org_name || 'Individual Scholar'}</span>
              </div>
            </div>

            {/* 5. Organization Memberships & Token */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-universe-slate uppercase tracking-wider">Organization Memberships</label>
              {profile?.memberships && profile.memberships.length > 0 ? (
                <div className="space-y-2">
                  {profile.memberships.map((m: any) => (
                    <div key={m.membership_id} className="flex items-center justify-between rounded-xl bg-space-800 border border-white/[0.06] p-3 text-xs">
                      <div>
                        <div className="font-semibold text-white">{m.org_name}</div>
                        <div className="text-[11px] text-universe-slate">ID: {m.org_id}</div>
                      </div>
                      <span className="font-mono font-bold px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-400/20">
                        {m.role}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-universe-slate">No institutional memberships. Operating as an individual learner.</p>
              )}
            </div>

            {/* Accept Invitation Token */}
            <div className="pt-3 border-t border-white/[0.08] space-y-2">
              <label className="text-xs font-semibold text-universe-slate">Join an Organization</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={inviteTokenInput}
                  onChange={(e) => setInviteTokenInput(e.target.value)}
                  placeholder="Paste invitation token..."
                  className="flex-1 rounded-xl border border-white/[0.12] bg-space-800 px-3.5 py-2 text-xs text-white focus:outline-none focus:border-cyan-400"
                />
                <button
                  type="button"
                  onClick={handleAcceptInvite}
                  className="rounded-xl border border-cyan-400/30 bg-cyan-500/10 hover:bg-cyan-500/20 px-4 py-2 text-xs font-semibold text-cyan-300 transition-colors"
                >
                  Accept
                </button>
              </div>
              {inviteFeedback && (
                <p className="text-xs text-cyan-300 mt-1">{inviteFeedback}</p>
              )}
            </div>

            {/* Sign Out Button in Modal */}
            <div className="pt-3 border-t border-white/[0.08] flex justify-between items-center">
              <span className="text-xs text-universe-slate font-mono">End your active session</span>
              <button
                type="button"
                onClick={() => {
                  setIsAccountModalOpen(false);
                  void onSignOut();
                }}
                className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-950/30 px-4 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/20 hover:border-red-400/50 transition-colors cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5 text-red-400" />
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
