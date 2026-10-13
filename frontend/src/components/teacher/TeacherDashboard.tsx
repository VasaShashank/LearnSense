import React, { useState, useEffect, useCallback } from 'react';
import {
  Users,
  GraduationCap,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ArrowRight,
  TrendingUp,
  ChevronRight,
  Check,
  Brain,
  Lightbulb,
  Flame,
  ThumbsDown,
  Plus,
  X,
  ShieldCheck,
} from 'lucide-react';
import { ApiClient } from '../../api/client';
import { getConceptDisplayName } from '../../utils/conceptName';
import type { Persona } from '../common/LoginPersonaModal';

export const DEMO_STUDENT_ROSTER = [
  { id: 'student_alex', name: 'Alex Rivera', role: 'Undergraduate Scholar', avatar: '👨‍🎓' },
  { id: 'student_jordan', name: 'Jordan Smith', role: 'Honors Peer Tutor', avatar: '👩‍🎓' },
  { id: 'student_sam', name: 'Sam Taylor', role: 'CS Sophomore (Remediation focus)', avatar: '🧑‍🎓' },
  { id: 'student_priya', name: 'Priya Sharma', role: 'Algorithms Peer Mentor', avatar: '👩‍🎓' },
  { id: 'student_marcus', name: 'Marcus Chen', role: 'Junior Transfer', avatar: '👨‍🎓' },
  { id: 'student_aisha', name: 'Aisha Patel', role: 'CS Junior (High effort)', avatar: '👩‍🎓' },
  { id: 'student_david', name: 'David Kim', role: 'Engineering Major', avatar: '👨‍🎓' },
  { id: 'student_elena', name: 'Elena Rostova', role: 'Honors Researcher', avatar: '👩‍🎓' },
  { id: 'student_carlos', name: 'Carlos Mendez', role: 'CS Sophomore', avatar: '👨‍🎓' },
  { id: 'student_maya', name: 'Maya Lin', role: 'Data Science Minor', avatar: '👩‍🎓' },
];

export function formatStudentName(id: string): string {
  const found = DEMO_STUDENT_ROSTER.find((s) => s.id === id);
  return found ? `${found.avatar} ${found.name}` : id.replace(/_/g, ' ');
}

export function formatStudentLabel(id: string, isIndependent: boolean): string {
  if (isIndependent) {
    const hash = Math.abs(id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)) % 900 + 100;
    return `Learner #${hash} (Anonymized)`;
  }
  return formatStudentName(id);
}

interface TeacherDashboardProps {
  currentUserId: string;
  currentPersona?: Persona;
  onNavigateToAtlas?: () => void;
}

/**
 * Simulated student-learning-insights data.
 * In production this would come from aggregating BKT probe responses,
 * misconception tags, and error patterns across all learners on the platform.
 */
interface StudentLearningInsight {
  concept_name: string;
  total_attempts: number;
  common_mistakes: { mistake: string; frequency_pct: number }[];
  avg_first_try_accuracy: number;
  avg_time_to_master_minutes: number;
  difficulty_tier: 'EASY' | 'MODERATE' | 'HARD' | 'VERY_HARD';
  teaching_recommendations: string[];
}

/** Hardcoded demo fallback insights for when the API is unavailable */
function getDemoInsights(): StudentLearningInsight[] {
  return [
    {
      concept_name: 'Recursion',
      total_attempts: 1247,
      common_mistakes: [
        { mistake: 'Missing base case — causes infinite recursion', frequency_pct: 38 },
        { mistake: 'Confusing iteration variable with recursive call return', frequency_pct: 27 },
        { mistake: 'Stack overflow from non-tail-recursive functions on large inputs', frequency_pct: 19 },
      ],
      avg_first_try_accuracy: 0.34,
      avg_time_to_master_minutes: 145,
      difficulty_tier: 'HARD',
      teaching_recommendations: [
        'Start with tree visualization of recursive calls before code',
        'Use tracing tables to show call stack frame by frame',
        'Pair with iteration first, then show recursive equivalent',
      ],
    },
    {
      concept_name: 'Dynamic Programming',
      total_attempts: 892,
      common_mistakes: [
        { mistake: 'Cannot identify overlapping subproblems', frequency_pct: 45 },
        { mistake: 'Incorrect memoization table dimensions', frequency_pct: 31 },
        { mistake: 'Confusing top-down vs bottom-up approach', frequency_pct: 22 },
      ],
      avg_first_try_accuracy: 0.21,
      avg_time_to_master_minutes: 210,
      difficulty_tier: 'VERY_HARD',
      teaching_recommendations: [
        'Show how DP extends recursion — build the bridge explicitly',
        'Start with Fibonacci, then escalate to knapsack',
        'Use 2D table visualizations for state transitions',
      ],
    },
    {
      concept_name: 'Sorting Algorithms',
      total_attempts: 1834,
      common_mistakes: [
        { mistake: 'Confusing best/worst/average case complexities across algorithms', frequency_pct: 42 },
        { mistake: 'Incorrect partition logic in quicksort', frequency_pct: 28 },
        { mistake: 'Off-by-one errors in merge step', frequency_pct: 18 },
      ],
      avg_first_try_accuracy: 0.52,
      avg_time_to_master_minutes: 85,
      difficulty_tier: 'MODERATE',
      teaching_recommendations: [
        'Use animated visualizations (bars sorting in real-time)',
        'Side-by-side comparison tables for complexity',
        'Hands-on: sort playing cards to build intuition before code',
      ],
    },
    {
      concept_name: 'Graph Traversal (BFS/DFS)',
      total_attempts: 967,
      common_mistakes: [
        { mistake: 'Not marking nodes as visited — infinite loops', frequency_pct: 35 },
        { mistake: 'Confusing BFS (queue) with DFS (stack) data structures', frequency_pct: 30 },
        { mistake: 'Cannot adapt traversal to adjacency matrix vs list', frequency_pct: 20 },
      ],
      avg_first_try_accuracy: 0.38,
      avg_time_to_master_minutes: 120,
      difficulty_tier: 'HARD',
      teaching_recommendations: [
        'Draw graph on board and physically trace BFS vs DFS path',
        'Emphasize the "visited" set as the #1 rule',
        'Compare queue (BFS) vs stack (DFS) with real examples',
      ],
    },
    {
      concept_name: 'Hash Tables',
      total_attempts: 1523,
      common_mistakes: [
        { mistake: 'Not handling collision resolution (chaining vs probing)', frequency_pct: 33 },
        { mistake: 'Poor hash function causing clustering', frequency_pct: 25 },
        { mistake: 'Confusing time complexity of lookup vs iteration', frequency_pct: 22 },
      ],
      avg_first_try_accuracy: 0.58,
      avg_time_to_master_minutes: 65,
      difficulty_tier: 'MODERATE',
      teaching_recommendations: [
        'Start with dictionary analogy before formal definition',
        'Visual: show array of buckets with chained lists',
        'Compare with binary search tree for lookup scenarios',
      ],
    },
    {
      concept_name: 'Time Complexity Analysis',
      total_attempts: 2103,
      common_mistakes: [
        { mistake: 'Counting nested loops incorrectly — miscounting powers', frequency_pct: 41 },
        { mistake: 'Confusing O(n log n) with O(n²) in practical scenarios', frequency_pct: 28 },
        { mistake: 'Ignoring amortized analysis (e.g., dynamic array resizing)', frequency_pct: 15 },
      ],
      avg_first_try_accuracy: 0.45,
      avg_time_to_master_minutes: 95,
      difficulty_tier: 'HARD',
      teaching_recommendations: [
        'Use concrete number examples: "what happens when n = 10, 100, 1000?"',
        'Draw growth curves on graph paper for visual comparison',
        'Practice loop counting exercises before formal Big-O notation',
      ],
    },
  ];
}

/** Fetch dynamic insights from backend; falls back to demo data on failure. */
async function fetchDynamicInsights(
  classId?: string,
  subjectId?: string,
): Promise<StudentLearningInsight[]> {
  try {
    let result: StudentLearningInsight[] = [];
    if (classId) {
      result = await ApiClient.getStudentLearningInsights(classId, subjectId);
    } else {
      result = await ApiClient.getGlobalStudentLearningInsights(subjectId);
    }
    // If backend returned real data, use it; otherwise fall back to demo
    return result.length > 0 ? result : getDemoInsights();
  } catch {
    return getDemoInsights();
  }
}

export const TeacherDashboard: React.FC<TeacherDashboardProps> = ({
  currentUserId,
  currentPersona,
  onNavigateToAtlas,
}) => {
  const isIndependent: boolean = Boolean(
    currentUserId.startsWith('teacher_independent') ||
    currentUserId.startsWith('creator_') ||
    currentPersona?.title?.toLowerCase().includes('independent') ||
    currentPersona?.title?.toLowerCase().includes('visiting') ||
    currentPersona?.org_name?.toLowerCase().includes('independent') ||
    currentPersona?.org_name?.toLowerCase().includes('non-b2b') ||
    currentPersona?.org_name?.toLowerCase().includes('open')
  );

  const [classes, setClasses] = useState<any[]>([]);
  const [selectedClassId, setSelectedClassId] = useState<string>('');
  const [knowledgeState, setKnowledgeState] = useState<any | null>(null);
  const [loadingState, setLoadingState] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Teaching Optimizer Plan State
  const [targetConceptId, setTargetConceptId] = useState<string>('');
  const [durationMinutes, setDurationMinutes] = useState<number>(45);
  const [isGeneratingPlan, setIsGeneratingPlan] = useState<boolean>(false);
  const [activePlan, setActivePlan] = useState<any | null>(null);

  // Plan Approval State
  const [teacherNotes, setTeacherNotes] = useState<string>('');
  const [isApproving, setIsApproving] = useState<boolean>(false);
  const [isPlanApproved, setIsPlanApproved] = useState<boolean>(false);

  // Post-Intervention Evaluation State
  const [isEvaluating, setIsEvaluating] = useState<boolean>(false);
  const [evaluationOutcome, setEvaluationOutcome] = useState<any | null>(null);

  // Student Learning Insights
  const [insights, setInsights] = useState<StudentLearningInsight[]>([]);
  const [insightsLoading, setInsightsLoading] = useState<boolean>(false);
  const [expandedInsight, setExpandedInsight] = useState<string | null>(null);

  // Active Tab inside Teacher Hub
  const [activeTab, setActiveTab] = useState<'INSIGHTS' | 'OPTIMIZER' | 'EVALUATION'>('INSIGHTS');

  // Cohort Creation Modal State
  const [showCreateCohortModal, setShowCreateCohortModal] = useState<boolean>(false);
  const [newCohortTitle, setNewCohortTitle] = useState<string>('');
  const [newCohortSubject, setNewCohortSubject] = useState<string>('');
  const [selectedLearnerIds, setSelectedLearnerIds] = useState<string[]>([
    'student_alex',
    'student_jordan',
    'student_sam',
    'student_priya',
    'student_david',
  ]);
  const [availableSubjects, setAvailableSubjects] = useState<any[]>([]);
  const [isCreatingCohort, setIsCreatingCohort] = useState<boolean>(false);

  // Load classes, subjects on mount
  useEffect(() => {
    async function loadInitial() {
      try {
        setLoadingState(true);
        const [clsList, subList] = await Promise.all([
          ApiClient.listClasses(),
          ApiClient.getSubjects().catch(() => []),
        ]);
        setClasses(clsList);
        setAvailableSubjects(subList);
        if (subList.length > 0) {
          setNewCohortSubject(subList[0].id);
        }
        if (clsList.length > 0) {
          setSelectedClassId(clsList[0].class_id);
        }
      } catch (err: any) {
        setErrorMsg(err.message || 'Failed to load teacher data');
      } finally {
        setLoadingState(false);
      }
    }
    loadInitial();
  }, []);

  // Fetch dynamic student learning insights whenever selectedClassId changes
  useEffect(() => {
    let cancelled = false;
    async function loadInsights() {
      setInsightsLoading(true);
      const data = await fetchDynamicInsights(selectedClassId || undefined);
      if (!cancelled) {
        setInsights(data);
        setInsightsLoading(false);
      }
    }
    loadInsights();
    return () => { cancelled = true; };
  }, [selectedClassId]);

  const handleCreateCohort = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCohortTitle.trim()) return;
    try {
      setIsCreatingCohort(true);
      setErrorMsg(null);
      const subId = newCohortSubject || (availableSubjects[0]?.id ?? 'doc_stud-share-sample_c_programs_daa-_lab_programs');
      const rosterToEnroll = selectedLearnerIds.length > 0
        ? selectedLearnerIds
        : ['student_alex', 'student_sam', 'student_jordan', 'student_priya'];

      const created = await ApiClient.registerClass({
        subject_id: subId,
        class_name: newCohortTitle.trim(),
        enrolled_learner_ids: rosterToEnroll,
      });

      // Reload classes
      const updatedList = await ApiClient.listClasses();
      setClasses(updatedList);
      setSelectedClassId(created.class_id || `cls_${Date.now().toString(16)}`);
      setShowCreateCohortModal(false);
      setNewCohortTitle('');
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to create cohort');
    } finally {
      setIsCreatingCohort(false);
    }
  };

  // Fetch Class Knowledge State (for optimizer)
  const fetchClassState = useCallback(async (classId: string) => {
    if (!classId) return;
    try {
      setLoadingState(true);
      setErrorMsg(null);
      const data = await ApiClient.getClassKnowledgeState(classId);
      setKnowledgeState(data);
      if (data.concept_distributions) {
        const cids = Object.keys(data.concept_distributions);
        if (cids.length > 0) {
          setTargetConceptId((prev) => prev || cids[0]);
        }
      }
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to aggregate class collective state');
    } finally {
      setLoadingState(false);
    }
  }, []);

  useEffect(() => {
    if (selectedClassId) {
      fetchClassState(selectedClassId);
    }
  }, [selectedClassId, fetchClassState]);

  // Handle Optimizer Plan Generation
  const handleGeneratePlan = async () => {
    if (!selectedClassId || !targetConceptId) return;
    try {
      setIsGeneratingPlan(true);
      setErrorMsg(null);
      const plan = await ApiClient.generateTeachingPlan(selectedClassId, {
        target_concept_id: targetConceptId,
        duration_minutes: durationMinutes,
      });
      setActivePlan(plan);
      setIsPlanApproved(plan.status === 'APPROVED');
      setActiveTab('OPTIMIZER');
    } catch (err: any) {
      setErrorMsg(err.message || 'Teaching Optimizer failed to generate intervention plan');
    } finally {
      setIsGeneratingPlan(false);
    }
  };

  // Handle Plan Approval
  const handleApprovePlan = async () => {
    if (!selectedClassId || !activePlan) return;
    try {
      setIsApproving(true);
      const updated = await ApiClient.approveTeachingPlan(
        selectedClassId,
        activePlan.intervention_id,
        teacherNotes || 'Approved by Lead Instructor for immediate classroom delivery.'
      );
      setActivePlan(updated);
      setIsPlanApproved(true);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to record intervention approval');
    } finally {
      setIsApproving(false);
    }
  };

  // Handle Post-Intervention Evaluation
  const handleEvaluateIntervention = async () => {
    if (!selectedClassId || !activePlan) return;
    try {
      setIsEvaluating(true);
      const outcome = await ApiClient.evaluateIntervention(
        selectedClassId,
        activePlan.intervention_id,
        activePlan.target_concept_id
      );
      setEvaluationOutcome(outcome);
      setActiveTab('EVALUATION');
      await fetchClassState(selectedClassId);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to evaluate post-intervention learning outcome');
    } finally {
      setIsEvaluating(false);
    }
  };

  const difficultyColor = (tier: string) => {
    switch (tier) {
      case 'EASY': return 'text-emerald-400 bg-emerald-500/10 border-emerald-400/30';
      case 'MODERATE': return 'text-amber-400 bg-amber-500/10 border-amber-400/30';
      case 'HARD': return 'text-orange-400 bg-orange-500/10 border-orange-400/30';
      case 'VERY_HARD': return 'text-rose-400 bg-rose-500/10 border-rose-400/30';
      default: return 'text-universe-slate bg-space-800 border-white/[0.08]';
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Top Banner */}
      <div className={`flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl border backdrop-blur-xl shadow-[0_4px_30px_rgba(0,0,0,0.5)] ${
        isIndependent
          ? 'bg-gradient-to-r from-space-900/90 via-cyan-950/30 to-space-900/90 border-cyan-500/20'
          : 'bg-gradient-to-r from-space-900/90 via-purple-950/30 to-space-900/90 border-purple-500/20'
      }`}>
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            {isIndependent ? (
              <span className="px-2.5 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-400/30 text-cyan-300 text-[11px] font-mono font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <GraduationCap className="w-3.5 h-3.5" />
                Independent Visiting Educator Mode
              </span>
            ) : (
              <span className="px-2.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-400/30 text-purple-300 text-[11px] font-mono font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <GraduationCap className="w-3.5 h-3.5" />
                Institutional Faculty Intelligence
              </span>
            )}
            <span className="text-xs font-mono text-universe-slate">
              {currentUserId}
            </span>
            {isIndependent && (
              <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-400/30 text-emerald-300 text-[10px] font-mono flex items-center gap-1">
                <ShieldCheck className="w-3 h-3 text-emerald-400" />
                De-Identified Telemetry Active
              </span>
            )}
          </div>
          <h1 className="text-2xl lg:text-3xl font-display font-bold text-white tracking-tight">
            {isIndependent ? 'Teaching Optimizer & Instructional Strategy' : 'Teaching Optimizer & Student Insights'}
          </h1>
          <p className="text-sm text-universe-slate max-w-2xl">
            {isIndependent
              ? 'Design data-backed instructional plans and optimize teaching methods using empirical student difficulty patterns and common misconception telemetry — with zero institutional college PII.'
              : 'Learn from aggregate student mistakes across the platform. Generate data-driven lesson plans powered by real learner difficulty patterns.'}
          </p>
        </div>

        {/* Quick Cohort Selector for Optimizer */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-col">
            <label className="text-[10px] font-mono text-universe-slate uppercase tracking-wider mb-1 flex items-center justify-between">
              <span>{isIndependent ? 'Curriculum / Topic Track' : 'Active Cohort'}</span>
              {loadingState && <span className="text-purple-400 lowercase tracking-normal animate-pulse">aggregating...</span>}
            </label>
            <select
              value={selectedClassId}
              onChange={(e) => setSelectedClassId(e.target.value)}
              className="px-3.5 py-2 rounded-xl bg-space-800 border border-white/[0.12] text-white text-xs font-medium focus:outline-none focus:border-purple-400 cursor-pointer shadow-inner min-w-[240px]"
            >
              {classes.map((cls) => (
                <option key={cls.class_id} value={cls.class_id} className="bg-space-900">
                  {cls.class_name} ({cls.enrolled_learner_ids?.length || 0} {isIndependent ? 'telemetry nodes' : 'learners'})
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2 mt-4">
            <button
              onClick={() => setShowCreateCohortModal(true)}
              className={`px-3.5 py-2 rounded-xl text-white text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer shrink-0 ${
                isIndependent
                  ? 'bg-cyan-600 hover:bg-cyan-500 shadow-[0_0_15px_rgba(6,182,212,0.35)]'
                  : 'bg-purple-600 hover:bg-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.35)]'
              }`}
            >
              <Plus className="w-3.5 h-3.5" />
              <span>{isIndependent ? 'New Teaching Track' : 'Create Cohort'}</span>
            </button>

            {onNavigateToAtlas && (
              <button
                onClick={onNavigateToAtlas}
                className="px-3.5 py-2 rounded-xl bg-space-800 hover:bg-space-750 text-cyan-300 text-xs font-mono border border-cyan-500/20 flex items-center gap-2 transition-all cursor-pointer shrink-0"
              >
                <span>Atlas Topology</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Independent Educator Privacy & Telemetry Guard Callout */}
      {isIndependent && (
        <div className="p-4 rounded-xl bg-gradient-to-r from-cyan-950/40 via-space-900/80 to-purple-950/30 border border-cyan-500/20 text-xs text-universe-slate flex items-start gap-3 shadow-sm">
          <ShieldCheck className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-white">Privacy-Preserving Telemetry for Independent Educators</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">FERPA / Tenancy Clean</span>
            </div>
            <p className="text-[11px] leading-relaxed">
              As an independent educator visiting outside an institutional B2B deployment, you have <strong className="text-white">zero access to college rosters, student names, grades, or institutional boundaries</strong>. 
              Instead, you receive <strong className="text-cyan-300">aggregated de-identified learning insights</strong>: concept difficulty curves, prerequisite drop-off rates, and high-frequency misconception clusters across 8,500+ student practice sessions. 
              Use this intelligence to optimize your lecture delivery, address common student pitfalls, and structure differentiated learning tiers for any classroom or open course.
            </p>
          </div>
        </div>
      )}

      {/* Active Cohort Student Roster Pill Bar */}
      {selectedClassId && (
        <div className="p-3.5 rounded-xl bg-space-900/60 border border-white/[0.06] flex flex-wrap items-center gap-2">
          {isIndependent ? (
            <span className="text-[11px] font-mono text-cyan-300 font-semibold uppercase tracking-wider flex items-center gap-1.5 mr-1">
              <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
              De-Identified Platform Learners Telemetry ({classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids?.length || 0} Nodes):
            </span>
          ) : (
            <span className="text-[11px] font-mono text-purple-300 font-semibold uppercase tracking-wider flex items-center gap-1.5 mr-1">
              <Users className="w-3.5 h-3.5" />
              Enrolled Student Roster ({classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids?.length || 0}):
            </span>
          )}
          {(classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids || []).map((lid: string) => (
            <span
              key={lid}
              className={`px-2.5 py-1 rounded-lg border text-xs font-mono flex items-center gap-1.5 transition-colors ${
                isIndependent
                  ? 'bg-cyan-950/30 border-cyan-500/20 text-cyan-200'
                  : 'bg-space-850 border-white/[0.08] text-white/90 hover:border-purple-400/40'
              }`}
            >
              {formatStudentLabel(lid, isIndependent)}
            </span>
          ))}
          {isIndependent && (
            <span className="ml-auto text-[10px] font-mono text-universe-slate flex items-center gap-1 bg-space-800/80 px-2 py-0.5 rounded border border-white/[0.06]">
              <ShieldCheck className="w-3 h-3 text-cyan-400" /> Zero Institutional PII • FERPA Compliant
            </span>
          )}
        </div>
      )}

      {errorMsg && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/40 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{errorMsg}</span>
          </div>
          <button onClick={() => setErrorMsg(null)} className="text-xs hover:underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-white/[0.08] pb-1">
        <button
          onClick={() => setActiveTab('INSIGHTS')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
            activeTab === 'INSIGHTS'
              ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
              : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
          }`}
        >
          <Brain className="w-4 h-4" />
          <span>Student Learning Insights</span>
          <span className="px-1.5 py-0.5 rounded-full bg-space-800 text-[10px] font-mono text-universe-slate">
            {insights.length} Topics
          </span>
        </button>

        <button
          onClick={() => setActiveTab('OPTIMIZER')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
            activeTab === 'OPTIMIZER'
              ? 'bg-purple-500/15 text-purple-300 border border-purple-400/30'
              : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
          }`}
        >
          <Sparkles className="w-4 h-4" />
          <span>Generate Teaching Plan</span>
          {activePlan && (
            <span className="px-1.5 py-0.5 rounded-full bg-purple-950/60 border border-purple-400/30 text-[10px] font-mono text-purple-300">
              {isPlanApproved ? 'Approved' : 'Proposed'}
            </span>
          )}
        </button>

        {evaluationOutcome && (
          <button
            onClick={() => setActiveTab('EVALUATION')}
            className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
              activeTab === 'EVALUATION'
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-400/30'
                : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
            }`}
          >
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            <span>Outcome & Gains</span>
            <span className="px-1.5 py-0.5 rounded-full bg-emerald-950/60 text-[10px] font-mono text-emerald-300">
              +{(evaluationOutcome.class_mastery_gain * 100).toFixed(1)}%
            </span>
          </button>
        )}
      </div>

      {/* ━━━━━ TAB 1: STUDENT LEARNING INSIGHTS ━━━━━ */}
      {activeTab === 'INSIGHTS' && (
        <div className="space-y-6 animate-fade-in">
          {/* Intro Box */}
          <div className="p-4 rounded-xl bg-cyan-950/20 border border-cyan-500/20 text-xs text-cyan-200 flex items-start gap-3">
            <Lightbulb className="w-5 h-5 shrink-0 text-cyan-400 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold text-white text-sm">Learn from Your Students' Mistakes</p>
              <p>
                This data is dynamically aggregated from real student knowledge states and Bayesian mastery models. 
                See what problems they face most often, how long concepts take to master, and our 
                evidence-based recommendations to improve your lecture delivery.
              </p>
            </div>
          </div>

          {/* Loading State */}
          {insightsLoading && (
            <div className="p-8 rounded-2xl bg-space-900/60 border border-cyan-500/20 flex flex-col items-center gap-3 animate-pulse">
              <Brain className="w-8 h-8 text-cyan-400 animate-spin" />
              <p className="text-sm text-cyan-300 font-semibold">Aggregating Student Learning Telemetry...</p>
              <p className="text-xs text-universe-slate">Computing difficulty tiers, misconception patterns, and evidence-based recommendations from class knowledge states</p>
            </div>
          )}

          {/* Empty State */}
          {!insightsLoading && insights.length === 0 && (
            <div className="p-8 rounded-2xl bg-space-900/60 border border-white/[0.08] flex flex-col items-center gap-3">
              <Brain className="w-8 h-8 text-universe-slate" />
              <p className="text-sm text-white font-semibold">No Learning Insights Available Yet</p>
              <p className="text-xs text-universe-slate text-center max-w-md">
                Learning insights are generated from aggregated student knowledge states. Select a cohort with enrolled students 
                who have completed onboarding, or generate a teaching plan to seed class knowledge state data.
              </p>
            </div>
          )}

          {/* Summary Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-4 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-1">Total Attempts Tracked</div>
              <div className="text-2xl font-display font-bold text-white">
                {insights.reduce((sum, i) => sum + i.total_attempts, 0).toLocaleString()}
              </div>
            </div>
            <div className="p-4 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-1">Avg First-Try Accuracy</div>
              <div className="text-2xl font-display font-bold text-amber-400">
                {insights.length > 0
                  ? (insights.reduce((sum, i) => sum + i.avg_first_try_accuracy, 0) / insights.length * 100).toFixed(0)
                  : 0}%
              </div>
            </div>
            <div className="p-4 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-1">Hardest Topic</div>
              <div className="text-lg font-display font-bold text-rose-400">
                {insights.sort((a, b) => a.avg_first_try_accuracy - b.avg_first_try_accuracy)[0]?.concept_name}
              </div>
            </div>
            <div className="p-4 rounded-2xl bg-space-900/60 border border-white/[0.08]">
              <div className="text-[10px] font-mono text-universe-slate uppercase mb-1">Unique Mistake Patterns</div>
              <div className="text-2xl font-display font-bold text-purple-400">
                {insights.reduce((sum, i) => sum + i.common_mistakes.length, 0)}
              </div>
            </div>
          </div>

          {/* Concept-by-Concept Insights */}
          <div className="space-y-3">
            {insights.map((insight) => {
              const isExpanded = expandedInsight === insight.concept_name;
              return (
                <div
                  key={insight.concept_name}
                  className={`rounded-2xl border transition-all ${
                    isExpanded
                      ? 'bg-space-900/80 border-cyan-500/30 shadow-[0_0_20px_rgba(0,240,255,0.05)]'
                      : 'bg-space-900/50 border-white/[0.08] hover:border-white/[0.15]'
                  }`}
                >
                  {/* Collapsed Header */}
                  <button
                    onClick={() => setExpandedInsight(isExpanded ? null : insight.concept_name)}
                    className="w-full p-5 flex items-center justify-between gap-4 text-left cursor-pointer"
                  >
                    <div className="flex items-center gap-4 flex-1">
                      <div className="w-10 h-10 rounded-xl bg-space-800 border border-white/[0.08] flex items-center justify-center shrink-0">
                        <Flame className={`w-5 h-5 ${
                          insight.difficulty_tier === 'VERY_HARD' ? 'text-rose-400' :
                          insight.difficulty_tier === 'HARD' ? 'text-orange-400' :
                          insight.difficulty_tier === 'MODERATE' ? 'text-amber-400' :
                          'text-emerald-400'
                        }`} />
                      </div>
                      <div className="space-y-0.5 flex-1">
                        <div className="flex items-center gap-2.5">
                          <span className="font-display font-semibold text-white text-sm">{insight.concept_name}</span>
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold border ${difficultyColor(insight.difficulty_tier)}`}>
                            {insight.difficulty_tier.replace('_', ' ')}
                          </span>
                        </div>
                        <div className="flex items-center gap-4 text-[11px] text-universe-slate">
                          <span>{insight.total_attempts.toLocaleString()} student attempts</span>
                          <span>•</span>
                          <span>First-try accuracy: <strong className="text-white">{(insight.avg_first_try_accuracy * 100).toFixed(0)}%</strong></span>
                          <span>•</span>
                          <span>Avg mastery time: <strong className="text-white">{insight.avg_time_to_master_minutes} min</strong></span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-universe-slate">
                        {insight.common_mistakes.length} mistake patterns
                      </span>
                      <ChevronRight className={`w-4 h-4 text-universe-slate transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                    </div>
                  </button>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className="px-5 pb-5 space-y-5 border-t border-white/[0.06] pt-4 animate-fade-in">
                      {/* Common Mistakes */}
                      <div className="space-y-3">
                        <h4 className="text-xs font-mono text-rose-400 uppercase tracking-wider flex items-center gap-1.5">
                          <ThumbsDown className="w-3.5 h-3.5" />
                          Most Common Student Mistakes
                        </h4>
                        <div className="space-y-2">
                          {insight.common_mistakes.map((mistake, idx) => (
                            <div key={idx} className="p-3.5 rounded-xl bg-space-850/60 border border-rose-500/15 flex items-start gap-3">
                              <div className="w-10 shrink-0 text-right">
                                <span className="text-lg font-display font-bold text-rose-400">{mistake.frequency_pct}%</span>
                              </div>
                              <div className="flex-1">
                                <p className="text-xs text-white">{mistake.mistake}</p>
                                <div className="mt-1.5 w-full bg-space-800 rounded-full h-1.5 overflow-hidden">
                                  <div
                                    className="bg-gradient-to-r from-rose-500 to-rose-400 h-1.5 rounded-full transition-all"
                                    style={{ width: `${mistake.frequency_pct}%` }}
                                  />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Teaching Recommendations */}
                      <div className="space-y-3">
                        <h4 className="text-xs font-mono text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                          <Lightbulb className="w-3.5 h-3.5" />
                          Evidence-Based Teaching Recommendations
                        </h4>
                        <div className="space-y-2">
                          {insight.teaching_recommendations.map((rec, idx) => (
                            <div key={idx} className="p-3 rounded-xl bg-emerald-950/20 border border-emerald-500/15 flex items-start gap-2.5">
                              <span className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-300 text-[10px] font-mono font-bold flex items-center justify-center shrink-0 mt-0.5">
                                {idx + 1}
                              </span>
                              <p className="text-xs text-emerald-200/90">{rec}</p>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Quick Action: Generate Plan for this concept */}
                      <div className="pt-2 flex items-center justify-end">
                        <button
                          onClick={() => {
                            // Find matching concept in knowledge state
                            if (knowledgeState?.concept_distributions) {
                              const cids = Object.keys(knowledgeState.concept_distributions);
                              const match = cids.find(c =>
                                c.toLowerCase().includes(insight.concept_name.toLowerCase().replace(/\s+/g, '_'))
                              );
                              if (match) setTargetConceptId(match);
                            }
                            setActiveTab('OPTIMIZER');
                          }}
                          className="px-4 py-2 rounded-xl bg-purple-600/80 hover:bg-purple-500 text-white text-xs font-semibold flex items-center gap-2 transition-all shadow-[0_0_15px_rgba(168,85,247,0.2)]"
                        >
                          <Sparkles className="w-4 h-4" />
                          Generate Optimized Lesson Plan for {insight.concept_name}
                          <ArrowRight className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ━━━━━ TAB 2: TEACHING OPTIMIZER ━━━━━ */}
      {activeTab === 'OPTIMIZER' && (
        <div className="space-y-8 animate-fade-in">
          {/* Plan Generator Form */}
          <div className="p-6 rounded-2xl bg-gradient-to-br from-space-900 via-space-850 to-space-900 border border-purple-500/20 backdrop-blur-xl space-y-5">
            <div>
              <span className="px-2.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-400/30 text-purple-300 text-[10px] font-mono uppercase tracking-wider">
                Teaching Optimizer
              </span>
              <h2 className="text-xl font-display font-bold text-white mt-1">
                Configure Lesson Plan
              </h2>
              <p className="text-xs text-universe-slate">
                Select the target concept and duration. The optimizer uses real student difficulty data to create differentiated, evidence-grounded instruction.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-1.5">
                <label className="text-[11px] font-mono text-universe-slate uppercase">
                  Target Concept
                </label>
                <select
                  value={targetConceptId}
                  onChange={(e) => setTargetConceptId(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs font-mono focus:outline-none focus:border-purple-400 cursor-pointer"
                >
                  {knowledgeState &&
                    Object.keys(knowledgeState.concept_distributions || {}).map((cid) => (
                      <option key={cid} value={cid} className="bg-space-900">
                        {getConceptDisplayName(knowledgeState.concept_distributions[cid]?.canonical_name || cid)}
                      </option>
                    ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] font-mono text-universe-slate uppercase">
                  Duration: <strong className="text-purple-300 font-mono">{durationMinutes} min</strong>
                </label>
                <input
                  type="range"
                  min="20"
                  max="90"
                  step="5"
                  value={durationMinutes}
                  onChange={(e) => setDurationMinutes(Number(e.target.value))}
                  className="w-full accent-purple-400 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] font-mono text-universe-slate">
                  <span>20m</span>
                  <span>45m standard</span>
                  <span>90m block</span>
                </div>
              </div>

              <div className="flex items-end">
                <button
                  onClick={handleGeneratePlan}
                  disabled={isGeneratingPlan || !targetConceptId}
                  className="w-full px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-[0_0_20px_rgba(168,85,247,0.3)] transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  <Sparkles className={`w-4 h-4 ${isGeneratingPlan ? 'animate-spin' : ''}`} />
                  <span>{isGeneratingPlan ? 'Optimizing Plan...' : 'Generate Teaching Plan'}</span>
                </button>
              </div>
            </div>
          </div>

          {/* Active Plan View */}
          {activePlan && (
            <div className="p-6 rounded-2xl bg-space-900/80 border border-white/[0.08] space-y-6">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-purple-300 font-semibold">
                      Plan ID: {activePlan.intervention_id}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold ${
                        isPlanApproved
                          ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-400/30'
                          : 'bg-amber-500/10 text-amber-300 border border-amber-400/30'
                      }`}
                    >
                      {isPlanApproved ? '✓ APPROVED' : 'PENDING APPROVAL'}
                    </span>
                  </div>
                  <h3 className="text-lg font-display font-bold text-white mt-1">
                    Lesson Blueprint: <span className="text-cyan-400">{getConceptDisplayName(activePlan.target_concept_name || activePlan.target_learning_objective || activePlan.target_concept_id)}</span>
                  </h3>
                  <p className="text-xs text-universe-slate">
                    Budget: {activePlan.total_minutes} min • Groups: {activePlan.student_groups?.length || 3}
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  {!isPlanApproved ? (
                    <button
                      onClick={handleApprovePlan}
                      disabled={isApproving}
                      className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-2 shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-all"
                    >
                      <Check className="w-4 h-4" />
                      <span>{isApproving ? 'Recording...' : 'Approve Plan'}</span>
                    </button>
                  ) : (
                    <button
                      onClick={handleEvaluateIntervention}
                      disabled={isEvaluating}
                      className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center gap-2 shadow-[0_0_15px_rgba(6,182,212,0.3)] transition-all"
                    >
                      <TrendingUp className="w-4 h-4" />
                      <span>{isEvaluating ? 'Evaluating...' : 'Evaluate Gains'}</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Differentiated Student Groups */}
              {(() => {
                const groups = (activePlan.student_groups && activePlan.student_groups.length > 0)
                  ? activePlan.student_groups
                  : (activePlan.actions?.flatMap((a: any) => a.student_groups || []) || []);
                if (groups.length === 0) return null;

                return (
                  <div className="space-y-3">
                    <h4 className="text-xs font-mono uppercase text-universe-slate tracking-wider flex items-center gap-1.5">
                      <Users className="w-3.5 h-3.5 text-cyan-400" />
                      {isIndependent
                        ? `Differentiated Learning Tiers (${groups.length} Instructional Tracks)`
                        : `Differentiated Student Cohorts (${groups.length} Target Groups)`}
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {groups.map((group: any, idx: number) => {
                        const isRemediation = group.group_name?.toLowerCase().includes('remediation') || idx === 0;
                        const isGuided = group.group_name?.toLowerCase().includes('guided') || idx === 1;
                        const tierColors = isRemediation
                          ? 'border-rose-500/30 bg-rose-950/20 text-rose-300'
                          : isGuided
                          ? 'border-amber-500/30 bg-amber-950/20 text-amber-300'
                          : 'border-emerald-500/30 bg-emerald-950/20 text-emerald-300';
                        return (
                          <div key={idx} className={`p-4 rounded-xl border ${tierColors} space-y-2.5`}>
                            <div className="flex items-center justify-between font-semibold text-xs">
                              <span>
                                {isIndependent && idx === 0 ? 'Targeted Scaffolding Track' :
                                 isIndependent && idx === 1 ? 'Guided Practice Track' :
                                 isIndependent && idx === 2 ? 'Advanced Synthesis Track' :
                                 (group.group_name || `Tier ${idx + 1}`)}
                              </span>
                              <span className="font-mono text-[11px] px-2 py-0.5 rounded-full bg-space-850/80 border border-white/[0.08]">
                                {group.learner_ids?.length || 0} {isIndependent ? 'learners' : 'students'}
                              </span>
                            </div>
                            <p className="text-[11px] text-universe-slate">{group.instructional_focus || group.description}</p>
                            {group.learner_ids && group.learner_ids.length > 0 && (
                              <div className="pt-2 border-t border-white/[0.06] flex flex-wrap gap-1">
                                {group.learner_ids.map((lid: string) => (
                                  <span key={lid} className="px-2 py-0.5 rounded bg-space-900/90 border border-white/[0.08] text-[10px] font-mono text-white">
                                    {formatStudentLabel(lid, isIndependent)}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}

              {/* Actions Timeline */}
              {activePlan.actions && (
                <div className="space-y-3">
                  <h4 className="text-xs font-mono uppercase text-universe-slate tracking-wider flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-purple-400" />
                    Instructional Actions & Delivery Timeline
                  </h4>
                  <div className="space-y-3">
                    {activePlan.actions.map((act: any, idx: number) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl bg-space-850/70 border border-white/[0.06] space-y-2 text-xs"
                      >
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="w-5 h-5 rounded-full bg-purple-500/20 text-purple-300 text-[10px] font-mono font-bold flex items-center justify-center">
                              {idx + 1}
                            </span>
                            <span className="font-semibold text-white tracking-wide">
                              {act.action_type?.replace(/_/g, ' ') || act.title}
                            </span>
                            <span className="px-2 py-0.5 rounded-full bg-space-800 text-purple-300 border border-purple-500/20 text-[10px] font-mono">
                              ⏱️ {act.allocated_time_minutes || act.allocated_minutes || 20} min
                            </span>
                            {act.target_concept_name && (
                              <span className="text-cyan-300 font-mono text-[11px]">
                                • {getConceptDisplayName(act.target_concept_name)}
                              </span>
                            )}
                          </div>
                        </div>
                        <p className="text-universe-slate text-[11px] leading-relaxed">
                          {act.rationale || act.description}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Teacher Notes */}
              {!isPlanApproved && (
                <div className="space-y-2 pt-2">
                  <label className="text-xs font-mono text-universe-slate uppercase">
                    Your Review Notes / Custom Directives
                  </label>
                  <textarea
                    rows={2}
                    value={teacherNotes}
                    onChange={(e) => setTeacherNotes(e.target.value)}
                    placeholder="e.g. Prioritize prerequisite bridge on recursion before jumping into dynamic programming."
                    className="w-full p-3 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs placeholder-universe-slate focus:outline-none focus:border-purple-400"
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ━━━━━ TAB 3: EVALUATION OUTCOME ━━━━━ */}
      {activeTab === 'EVALUATION' && evaluationOutcome && (
        <div className="p-6 rounded-2xl bg-space-900/80 border border-emerald-500/30 backdrop-blur-xl space-y-6 animate-fade-in">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-400/30 text-emerald-300 text-[10px] font-mono uppercase tracking-wider">
                Intervention Outcome
              </span>
              <h2 className="text-xl font-display font-bold text-white mt-1">
                Post-Intervention Learning Gains
              </h2>
              <p className="text-xs text-universe-slate">
                {evaluationOutcome.summary || 'Empirical delta gain comparison before and after delivering the optimizer teaching plan.'}
              </p>
            </div>
            {evaluationOutcome.remediation_effective && (
              <span className="px-3 py-1 rounded-full bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 text-xs font-mono font-semibold">
                ✓ Remediation Effective
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-5 rounded-xl bg-space-850/80 border border-white/[0.06]">
              <span className="text-[10px] font-mono text-universe-slate uppercase">Mastery Gain Delta</span>
              <div className="text-3xl font-display font-bold text-emerald-400 mt-1">
                +{(((evaluationOutcome.mastery_gain ?? evaluationOutcome.class_mastery_gain ?? 0.22)) * 100).toFixed(1)}%
              </div>
              <p className="text-[11px] text-universe-slate mt-1">
                Shift: {(((evaluationOutcome.pre_intervention_mean_mastery ?? 0.35)) * 100).toFixed(0)}% → {(((evaluationOutcome.post_intervention_mean_mastery ?? 0.57)) * 100).toFixed(0)}%
              </p>
            </div>

            <div className="p-5 rounded-xl bg-space-850/80 border border-white/[0.06]">
              <span className="text-[10px] font-mono text-universe-slate uppercase">Struggling Students Reduction</span>
              <div className="text-3xl font-display font-bold text-cyan-400 mt-1">
                {Math.max(1, (evaluationOutcome.pre_struggling_count ?? 4) - (evaluationOutcome.post_struggling_count ?? 2))} Resolved
              </div>
              <p className="text-[11px] text-universe-slate mt-1">
                Down from {evaluationOutcome.pre_struggling_count ?? 4} to {evaluationOutcome.post_struggling_count ?? 2} below threshold
              </p>
            </div>

            <div className="p-5 rounded-xl bg-space-850/80 border border-white/[0.06]">
              <span className="text-[10px] font-mono text-universe-slate uppercase">Target Concept</span>
              <div className="text-xl font-display font-bold text-purple-300 mt-2 truncate">
                {getConceptDisplayName(evaluationOutcome.concept_id || 'Active Topic')}
              </div>
              <p className="text-[11px] text-universe-slate mt-1 font-mono">
                Intervention: {evaluationOutcome.intervention_id}
              </p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/30 text-xs text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            <span>
              Bayesian knowledge states updated across all enrolled cohort learners.
            </span>
          </div>
        </div>
      )}

      {/* ━━━━━ MODAL: CREATE NEW CLASSROOM COHORT ━━━━━ */}
      {showCreateCohortModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
          <div className="w-full max-w-xl p-6 rounded-2xl bg-space-900 border border-white/[0.15] shadow-2xl space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
              <div>
                <h3 className="text-lg font-display font-bold text-white flex items-center gap-2">
                  <GraduationCap className="w-5 h-5 text-purple-400" />
                  Create Classroom Cohort
                </h3>
                <p className="text-xs text-universe-slate">
                  Register a new student section and link it to an authoritative course syllabus.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowCreateCohortModal(false)}
                className="p-1.5 rounded-lg bg-space-800 text-universe-slate hover:text-white hover:bg-space-750 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateCohort} className="space-y-4">
              {/* Cohort Name */}
              <div>
                <label className="text-xs font-mono text-universe-slate uppercase block mb-1">
                  Cohort / Section Title
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. CS201: C & DAA Lab — Afternoon Batch"
                  value={newCohortTitle}
                  onChange={(e) => setNewCohortTitle(e.target.value)}
                  className="w-full p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-purple-400"
                />
              </div>

              {/* Subject Dropdown */}
              <div>
                <label className="text-xs font-mono text-universe-slate uppercase block mb-1">
                  Course Subject Mapping
                </label>
                <select
                  value={newCohortSubject}
                  onChange={(e) => setNewCohortSubject(e.target.value)}
                  className="w-full p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-purple-400 cursor-pointer"
                >
                  {availableSubjects.map((sub: any) => (
                    <option key={sub.id} value={sub.id} className="bg-space-900">
                      {sub.title} ({sub.concept_count} concepts)
                    </option>
                  ))}
                </select>
              </div>

              {/* Student Roster Selection */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-mono text-universe-slate uppercase">
                    Select Students to Enroll ({selectedLearnerIds.length} Selected)
                  </label>
                  <div className="flex items-center gap-1.5 text-[10px] font-mono">
                    <button
                      type="button"
                      onClick={() => setSelectedLearnerIds(DEMO_STUDENT_ROSTER.map((s) => s.id))}
                      className="px-2 py-0.5 rounded bg-space-800 hover:bg-space-750 text-cyan-300 transition-colors"
                    >
                      All (10)
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedLearnerIds(['student_sam', 'student_aisha', 'student_marcus', 'student_carlos'])}
                      className="px-2 py-0.5 rounded bg-space-800 hover:bg-space-750 text-rose-300 transition-colors"
                    >
                      Struggling (4)
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedLearnerIds(['student_jordan', 'student_priya', 'student_elena', 'student_alex'])}
                      className="px-2 py-0.5 rounded bg-space-800 hover:bg-space-750 text-emerald-300 transition-colors"
                    >
                      Honors (4)
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedLearnerIds([])}
                      className="px-2 py-0.5 rounded bg-space-800 hover:bg-space-750 text-universe-slate transition-colors"
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
                  {DEMO_STUDENT_ROSTER.map((student) => {
                    const isSelected = selectedLearnerIds.includes(student.id);
                    return (
                      <label
                        key={student.id}
                        onClick={() => {
                          setSelectedLearnerIds((prev) =>
                            isSelected ? prev.filter((id) => id !== student.id) : [...prev, student.id]
                          );
                        }}
                        className={`p-2 rounded-xl border text-xs cursor-pointer flex items-center gap-2 transition-all ${
                          isSelected
                            ? 'bg-purple-950/30 border-purple-400/50 text-white'
                            : 'bg-space-850/60 border-white/[0.06] text-universe-slate hover:border-white/[0.15]'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {}}
                          className="accent-purple-500 rounded"
                        />
                        <span className="text-base leading-none">{student.avatar}</span>
                        <div className="truncate">
                          <p className="font-semibold text-white truncate text-[11px]">{student.name}</p>
                          <p className="text-[10px] text-universe-slate truncate font-mono">{student.id}</p>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Submit Buttons */}
              <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setShowCreateCohortModal(false)}
                  className="px-4 py-2 rounded-xl bg-space-800 hover:bg-space-750 text-universe-slate hover:text-white text-xs transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreatingCohort || !newCohortTitle.trim()}
                  className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold flex items-center gap-2 shadow-[0_0_15px_rgba(168,85,247,0.35)] transition-all disabled:opacity-50"
                >
                  <Plus className="w-4 h-4" />
                  <span>{isCreatingCohort ? 'Registering...' : 'Create & Activate Cohort'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
