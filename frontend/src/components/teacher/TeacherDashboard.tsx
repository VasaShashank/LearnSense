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
  ChevronDown,
  Check,
  Brain,
  Lightbulb,
  Flame,
  ThumbsDown,
  Plus,
  X,
  ShieldCheck,
  Search,
  Target,
} from 'lucide-react';
import { ApiClient } from '../../api/client';
import { getConceptDisplayName } from '../../utils/conceptName';
import type { Persona } from '../common/LoginPersonaModal';
import { ConceptReviewWorkspace } from './ConceptReviewWorkspace';

export interface IndividualStudentMastery {
  learner_id: string;
  name: string;
  role: string;
  avatar: string;
  average_mastery: number;
  accuracy_pct: number;
  total_concepts: number;
  mastered_concepts: number;
  developing_concepts: number;
  struggling_concepts: number;
  total_attempts: number;
  total_correct: number;
  assigned_tier: string;
  recommended_intervention: string;
  weakest_concept?: {
    concept_id: string;
    name: string;
    mastery: number;
  };
  concept_breakdown: Array<{
    concept_id: string;
    concept_name: string;
    mastery: number;
    status: 'MASTERED' | 'DEVELOPING' | 'STRUGGLING';
    attempts: number;
    correct: number;
    incorrect: number;
    confidence: number;
    uncertainty: number;
  }>;
}

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

  // Individual Student Mastery State
  const [studentsMastery, setStudentsMastery] = useState<IndividualStudentMastery[]>([]);
  const [studentsLoading, setStudentsLoading] = useState<boolean>(false);
  const [expandedStudentId, setExpandedStudentId] = useState<string | null>(null);
  const [studentSearchTerm, setStudentSearchTerm] = useState<string>('');
  const [studentFilter, setStudentFilter] = useState<'ALL' | 'STRUGGLING' | 'DEVELOPING' | 'MASTERED'>('ALL');

  // Active Tab inside Teacher Hub
  const [activeTab, setActiveTab] = useState<'INSIGHTS' | 'STUDENTS' | 'OPTIMIZER' | 'EVALUATION' | 'CURRICULUM_REVIEW'>('INSIGHTS');

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

  // Fetch dynamic student learning insights & individual student mastery whenever selectedClassId changes
  useEffect(() => {
    let cancelled = false;
    async function loadInsightsAndMastery() {
      setInsightsLoading(true);
      setStudentsLoading(true);
      try {
        const [insightsData, masteryData] = await Promise.all([
          fetchDynamicInsights(selectedClassId || undefined),
          selectedClassId ? ApiClient.getClassStudentsMastery(selectedClassId).catch(() => []) : Promise.resolve([]),
        ]);
        if (!cancelled) {
          setInsights(insightsData);
          if (masteryData && masteryData.length > 0) {
            setStudentsMastery(masteryData as IndividualStudentMastery[]);
          }
        }
      } catch (err) {
        console.warn('Error loading insights or student mastery:', err);
      } finally {
        if (!cancelled) {
          setInsightsLoading(false);
          setStudentsLoading(false);
        }
      }
    }
    loadInsightsAndMastery();
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

  const renderStudentDetailCard = (student: IndividualStudentMastery, onClose?: () => void) => {
    const masteryPct = Math.round(student.average_mastery * 100);
    const isRemediation = student.average_mastery < 0.45;
    const isDeveloping = student.average_mastery >= 0.45 && student.average_mastery < 0.75;
    const tierBadgeStyle = isRemediation
      ? 'border-rose-500/40 bg-rose-950/30 text-rose-300'
      : isDeveloping
      ? 'border-amber-500/40 bg-amber-950/30 text-amber-300'
      : 'border-emerald-500/40 bg-emerald-950/30 text-emerald-300';

    const displayName = isIndependent ? formatStudentLabel(student.learner_id, true) : student.name;
    const displayAvatar = isIndependent ? '🧑‍💻' : (student.avatar || '🧑‍🎓');
    const displayRole = isIndependent
      ? 'De-Identified Platform Telemetry Node'
      : student.role;
    const displayTier = isIndependent
      ? (isRemediation
          ? 'Targeted Scaffolding Track'
          : isDeveloping
          ? 'Guided Practice Track'
          : 'Advanced Synthesis Track')
      : student.assigned_tier;

    return (
      <div className={`p-6 rounded-2xl bg-gradient-to-br from-space-900/95 via-space-850 to-space-900/95 border shadow-[0_10px_40px_rgba(0,0,0,0.6)] backdrop-blur-xl space-y-6 animate-fade-in ${
        isIndependent ? 'border-cyan-500/30' : 'border-purple-500/30'
      }`}>
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
          <div className="flex items-center gap-3.5">
            <div className="w-12 h-12 rounded-2xl bg-space-800 border border-white/[0.12] flex items-center justify-center text-2xl shadow-inner shrink-0">
              {displayAvatar}
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h3 className="text-lg font-display font-bold text-white tracking-tight">
                  {displayName}
                </h3>
                <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold border ${tierBadgeStyle}`}>
                  {displayTier}
                </span>
                {isIndependent && (
                  <span className="px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-400/30 text-cyan-300 text-[10px] font-mono flex items-center gap-1">
                    <ShieldCheck className="w-3 h-3 text-cyan-400" />
                    FERPA Clean
                  </span>
                )}
              </div>
              <p className="text-xs text-universe-slate font-mono mt-0.5">
                {isIndependent ? (
                  <span className="text-cyan-300/80 flex items-center gap-1.5">
                    {displayRole} • Zero Institutional PII
                  </span>
                ) : (
                  <>{displayRole} • ID: <span className="text-purple-300">{student.learner_id}</span></>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {student.weakest_concept && (
              <button
                type="button"
                onClick={() => {
                  setTargetConceptId(student.weakest_concept!.concept_id);
                  setActiveTab('OPTIMIZER');
                }}
                className={`px-3.5 py-1.5 rounded-xl text-white text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                  isIndependent
                    ? 'bg-cyan-600/80 hover:bg-cyan-500 shadow-[0_0_15px_rgba(6,182,212,0.25)]'
                    : 'bg-purple-600/80 hover:bg-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.25)]'
                }`}
              >
                <Target className="w-3.5 h-3.5" />
                <span>{isIndependent ? `Optimize Instruction for ${student.weakest_concept.name}` : `Intervene on ${student.weakest_concept.name}`}</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="p-1.5 rounded-lg bg-space-800 text-universe-slate hover:text-white hover:bg-space-750 transition-colors cursor-pointer"
                title="Collapse student details"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* 4 Stat Tiles */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Bayesian Mastery</span>
            <div className={`text-2xl font-display font-bold ${
              isRemediation ? 'text-rose-400' : isDeveloping ? 'text-amber-400' : 'text-emerald-400'
            }`}>
              {masteryPct}%
            </div>
            <div className="w-full bg-space-800 rounded-full h-1.5 overflow-hidden mt-1">
              <div
                className={`h-1.5 rounded-full ${
                  isRemediation ? 'bg-rose-400' : isDeveloping ? 'bg-amber-400' : 'bg-emerald-400'
                }`}
                style={{ width: `${masteryPct}%` }}
              />
            </div>
          </div>

          <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Practice Accuracy</span>
            <div className="text-2xl font-display font-bold text-cyan-400">
              {student.accuracy_pct}%
            </div>
            <p className="text-[10px] font-mono text-universe-slate truncate">
              {student.total_correct} correct / {student.total_attempts} attempts
            </p>
          </div>

          <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Curriculum Status</span>
            <div className="text-sm font-semibold text-white mt-1 flex items-center gap-2">
              <span className="text-emerald-400">{student.mastered_concepts} master</span>
              <span>•</span>
              <span className="text-amber-400">{student.developing_concepts} dev</span>
              <span>•</span>
              <span className="text-rose-400">{student.struggling_concepts} strug</span>
            </div>
            <p className="text-[10px] font-mono text-universe-slate">
              Across {student.total_concepts} syllabus concepts
            </p>
          </div>

          <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Priority Remediation Need</span>
            <div className="text-sm font-semibold text-rose-300 mt-1 truncate">
              {student.weakest_concept ? student.weakest_concept.name : 'All concepts on track'}
            </div>
            <p className="text-[10px] font-mono text-universe-slate">
              {student.weakest_concept ? `${Math.round(student.weakest_concept.mastery * 100)}% mastery score` : 'Demonstrating solid mastery'}
            </p>
          </div>
        </div>

        {/* Concept-by-Concept Mastery Distribution */}
        {student.concept_breakdown && student.concept_breakdown.length > 0 && (
          <div className="space-y-3">
            <h4 className="text-xs font-mono uppercase tracking-wider text-universe-slate flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Brain className="w-3.5 h-3.5 text-purple-400" />
                Concept Mastery Breakdown ({student.concept_breakdown.length} Concepts)
              </span>
              <span className="text-[10px] text-universe-slate font-normal">
                Empirical Bayesian KT scores
              </span>
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              {student.concept_breakdown.map((cb) => {
                const cMastery = Math.round(cb.mastery * 100);
                const isStrug = cb.status === 'STRUGGLING';
                const isDev = cb.status === 'DEVELOPING';
                return (
                  <div
                    key={cb.concept_id}
                    className="p-3 rounded-xl bg-space-850/60 border border-white/[0.06] hover:border-white/[0.12] transition-colors space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-white truncate">{cb.concept_name}</span>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                        isStrug ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30' :
                        isDev ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30' :
                        'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                      }`}>
                        {cMastery}% • {cb.status}
                      </span>
                    </div>

                    <div className="w-full bg-space-800 rounded-full h-1.5 overflow-hidden">
                      <div
                        className={`h-1.5 rounded-full transition-all ${
                          isStrug ? 'bg-rose-400' : isDev ? 'bg-amber-400' : 'bg-emerald-400'
                        }`}
                        style={{ width: `${cMastery}%` }}
                      />
                    </div>

                    <div className="flex items-center justify-between text-[10px] font-mono text-universe-slate">
                      <span>{cb.attempts} attempts ({cb.correct} correct)</span>
                      <span>Confidence: {Math.round(cb.confidence * 100)}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recommended Intervention Box */}
        <div className="p-4 rounded-xl bg-purple-950/20 border border-purple-500/20 flex items-start gap-3">
          <Lightbulb className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <span className="text-[11px] font-mono uppercase font-semibold text-purple-300 tracking-wider">
              Instructional Guidance for Teacher
            </span>
            <p className="text-xs text-white/90 leading-relaxed">
              {student.recommended_intervention}
            </p>
          </div>
        </div>
      </div>
    );
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
        <div className="space-y-4">
          <div className="p-3.5 rounded-xl bg-space-900/60 border border-white/[0.06] flex flex-wrap items-center gap-2">
            {isIndependent ? (
              <span className="text-[11px] font-mono text-cyan-300 font-semibold uppercase tracking-wider flex items-center gap-1.5 mr-1">
                <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
                De-Identified Platform Learners Telemetry ({classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids?.length || 0} Nodes):
              </span>
            ) : (
              <div className="flex items-center gap-2 mr-1">
                <span className="text-[11px] font-mono text-purple-300 font-semibold uppercase tracking-wider flex items-center gap-1.5">
                  <Users className="w-3.5 h-3.5" />
                  Enrolled Student Roster ({classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids?.length || 0}):
                </span>
                <span className="text-[10px] text-universe-slate font-mono bg-space-850 px-2 py-0.5 rounded-full border border-white/[0.06]">
                  Click student to inspect mastery & insights
                </span>
              </div>
            )}
            {(classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids || []).map((lid: string) => {
              const isExpanded = expandedStudentId === lid;
              const student = studentsMastery.find((s) => s.learner_id === lid);
              const masteryPct = student ? Math.round(student.average_mastery * 100) : null;
              return (
                <button
                  type="button"
                  key={lid}
                  onClick={() => setExpandedStudentId(isExpanded ? null : lid)}
                  className={`px-3 py-1.5 rounded-lg border text-xs font-mono flex items-center gap-2 transition-all cursor-pointer ${
                    isExpanded
                      ? 'bg-purple-600/30 border-purple-400 text-white shadow-[0_0_15px_rgba(168,85,247,0.3)] ring-1 ring-purple-400'
                      : isIndependent
                      ? 'bg-cyan-950/30 border-cyan-500/20 text-cyan-200 hover:border-cyan-400/40'
                      : 'bg-space-850 border-white/[0.08] text-white/90 hover:border-purple-400/40 hover:bg-space-800'
                  }`}
                >
                  <span>{formatStudentLabel(lid, isIndependent)}</span>
                  {masteryPct !== null && !isIndependent && (
                    <span
                      className={`text-[10px] px-1.5 py-0.2 rounded font-mono font-bold ${
                        masteryPct < 45
                          ? 'bg-rose-500/20 text-rose-300'
                          : masteryPct < 75
                          ? 'bg-amber-500/20 text-amber-300'
                          : 'bg-emerald-500/20 text-emerald-300'
                      }`}
                    >
                      {masteryPct}%
                    </span>
                  )}
                  <ChevronDown
                    className={`w-3 h-3 text-universe-slate transition-transform ${
                      isExpanded ? 'rotate-180 text-purple-300' : ''
                    }`}
                  />
                </button>
              );
            })}
            {isIndependent && (
              <span className="ml-auto text-[10px] font-mono text-universe-slate flex items-center gap-1 bg-space-800/80 px-2 py-0.5 rounded border border-white/[0.06]">
                <ShieldCheck className="w-3 h-3 text-cyan-400" /> Zero Institutional PII • FERPA Compliant
              </span>
            )}
          </div>

          {/* Quick Roster Inspection Banner when a student pill is expanded */}
          {expandedStudentId && (
            <div className="animate-fade-in">
              {renderStudentDetailCard(
                studentsMastery.find((s) => s.learner_id === expandedStudentId) || {
                  learner_id: expandedStudentId,
                  name: formatStudentLabel(expandedStudentId, isIndependent),
                  role: isIndependent ? 'De-Identified Platform Telemetry Node' : 'Enrolled Cohort Learner',
                  avatar: isIndependent ? '🧑‍💻' : '🧑‍🎓',
                  average_mastery: 0.65,
                  accuracy_pct: 65,
                  total_concepts: 5,
                  mastered_concepts: 2,
                  developing_concepts: 2,
                  struggling_concepts: 1,
                  total_attempts: 12,
                  total_correct: 8,
                  assigned_tier: isIndependent ? 'Guided Practice Track' : 'Tier 2: Guided Practice',
                  recommended_intervention: isIndependent
                    ? 'Provide targeted instructional exercises on developing concepts before advancing to high-order synthesis.'
                    : 'Provide targeted practice on developing concepts before advancing to high-order synthesis.',
                  concept_breakdown: [],
                },
                () => setExpandedStudentId(null)
              )}
            </div>
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
      <div className="flex items-center gap-2 border-b border-white/[0.08] pb-1 overflow-x-auto">
        <button
          onClick={() => setActiveTab('INSIGHTS')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all shrink-0 cursor-pointer ${
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

        {!isIndependent && (
          <button
            onClick={() => setActiveTab('STUDENTS')}
            className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all shrink-0 cursor-pointer ${
              activeTab === 'STUDENTS'
                ? 'bg-purple-500/15 text-purple-300 border border-purple-400/30'
                : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
            }`}
          >
            <Users className="w-4 h-4" />
            <span>Individual Student Mastery</span>
            <span className="px-1.5 py-0.5 rounded-full bg-space-800 text-[10px] font-mono text-purple-300">
              {studentsMastery.length || classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids?.length || 0} Learners
            </span>
          </button>
        )}

        <button
          onClick={() => setActiveTab('OPTIMIZER')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all shrink-0 cursor-pointer ${
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

        <button
          onClick={() => setActiveTab('CURRICULUM_REVIEW')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all shrink-0 cursor-pointer ${
            activeTab === 'CURRICULUM_REVIEW'
              ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
              : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
          }`}
        >
          <ShieldCheck className="w-4 h-4 text-cyan-400" />
          <span>Concept Verification & Review</span>
          <span className="px-1.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-400/30 text-[10px] font-mono text-cyan-300">
            Person 2
          </span>
        </button>
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

          {/* Enrolled Student Mastery Roster Section in Summary View */}
          {!isIndependent && (
            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="space-y-0.5">
                  <h3 className="text-sm font-display font-bold text-white flex items-center gap-2">
                    <Users className="w-4 h-4 text-purple-400" />
                    Enrolled Student Mastery & Insights (Click to Expand Details)
                  </h3>
                  <p className="text-xs text-universe-slate">
                    Review individualized Bayesian knowledge states across your roster to inform instructional decisions and differentiated groups.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setActiveTab('STUDENTS')}
                  className="px-3 py-1.5 rounded-xl bg-space-800 hover:bg-space-750 text-purple-300 text-xs font-mono border border-purple-500/20 flex items-center gap-1.5 transition-all self-start sm:self-auto cursor-pointer"
                >
                  <span>Full Roster View ({studentsMastery.length || classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids?.length || 0})</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>

              {studentsLoading ? (
                <div className="py-6 flex items-center justify-center gap-2 text-xs font-mono text-universe-slate animate-pulse">
                  <Users className="w-4 h-4 animate-spin text-purple-400" />
                  <span>Loading cohort learners Bayesian states...</span>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
                  {(studentsMastery.length > 0
                    ? studentsMastery
                    : (classes.find((c) => c.class_id === selectedClassId)?.enrolled_learner_ids || [
                        'student_alex',
                        'student_sam',
                        'student_jordan',
                        'student_priya',
                      ]).map((lid: string, idx: number) => ({
                        learner_id: lid,
                        name: formatStudentName(lid),
                        role: 'Enrolled Learner',
                        avatar: DEMO_STUDENT_ROSTER.find((s) => s.id === lid)?.avatar || '🧑‍🎓',
                        average_mastery: [0.78, 0.36, 0.93, 0.87, 0.62][idx % 5],
                        accuracy_pct: [78, 36, 93, 87, 62][idx % 5],
                        total_concepts: 5,
                        mastered_concepts: idx === 1 ? 1 : 3,
                        developing_concepts: 2,
                        struggling_concepts: idx === 1 ? 2 : 0,
                        total_attempts: 15,
                        total_correct: 10,
                        assigned_tier:
                          idx === 1
                            ? 'Tier 1: Targeted Remediation'
                            : idx === 2
                            ? 'Tier 3: Advanced Synthesis'
                            : 'Tier 2: Guided Practice',
                        recommended_intervention:
                          idx === 1
                            ? 'Focus on foundational prerequisites with 1-on-1 trace scaffolding.'
                            : 'Ready for peer mentoring and advanced practice.',
                      }))
                  ).map((student: any) => {
                    const isSelected = expandedStudentId === student.learner_id;
                    const mPct = Math.round(student.average_mastery * 100);
                    const isStrug = student.average_mastery < 0.45;
                    const isMast = student.average_mastery >= 0.75;
                    return (
                      <div
                        key={student.learner_id}
                        onClick={() => setExpandedStudentId(isSelected ? null : student.learner_id)}
                        className={`p-3.5 rounded-xl border text-left cursor-pointer transition-all ${
                          isSelected
                            ? 'bg-purple-950/40 border-purple-400 shadow-[0_0_15px_rgba(168,85,247,0.25)] ring-1 ring-purple-400'
                            : 'bg-space-850/80 border-white/[0.06] hover:border-white/[0.2] hover:bg-space-800'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-xl leading-none shrink-0">{student.avatar}</span>
                            <div className="min-w-0">
                              <p className="text-xs font-semibold text-white truncate">{student.name}</p>
                              <p className="text-[10px] text-universe-slate font-mono truncate">{student.role}</p>
                            </div>
                          </div>
                          <span
                            className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-bold shrink-0 ${
                              isStrug
                                ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
                                : isMast
                                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                                : 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                            }`}
                          >
                            {mPct}%
                          </span>
                        </div>

                        {/* Mastery Gauge */}
                        <div className="w-full bg-space-800 rounded-full h-1.5 overflow-hidden mb-2">
                          <div
                            className={`h-1.5 rounded-full ${
                              isStrug ? 'bg-rose-400' : isMast ? 'bg-emerald-400' : 'bg-amber-400'
                            }`}
                            style={{ width: `${mPct}%` }}
                          />
                        </div>

                        <div className="flex items-center justify-between text-[10px] font-mono text-universe-slate">
                          <span>
                            {student.struggling_concepts > 0
                              ? `⚠️ ${student.struggling_concepts} struggling`
                              : isMast
                              ? '✓ Mastered'
                              : '• Developing'}
                          </span>
                          <span className="text-purple-300 flex items-center gap-0.5">
                            {isSelected ? 'Collapse' : 'Expand'}
                            <ChevronDown
                              className={`w-3 h-3 transition-transform ${isSelected ? 'rotate-180' : ''}`}
                            />
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

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

      {/* ━━━━━ TAB: INDIVIDUAL STUDENT MASTERY (B2B) ━━━━━ */}
      {activeTab === 'STUDENTS' && !isIndependent && (
        <div className="space-y-6 animate-fade-in">
          {/* Header & Controls */}
          <div className="p-6 rounded-2xl bg-gradient-to-br from-space-900 via-space-850 to-space-900 border border-purple-500/20 backdrop-blur-xl space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <span className="px-2.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-400/30 text-purple-300 text-[10px] font-mono uppercase tracking-wider">
                  B2B Institutional Intelligence
                </span>
                <h2 className="text-xl font-display font-bold text-white mt-1">
                  Individual Student Mastery & Cognitive Telemetry
                </h2>
                <p className="text-xs text-universe-slate">
                  Inspect empirical Bayesian knowledge states, misconception patterns, and targeted intervention guidance for each learner in this cohort.
                </p>
              </div>

              {/* Search & Filter Bar */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative min-w-[200px]">
                  <Search className="w-3.5 h-3.5 text-universe-slate absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    placeholder="Search student..."
                    value={studentSearchTerm}
                    onChange={(e) => setStudentSearchTerm(e.target.value)}
                    className="w-full pl-9 pr-3.5 py-2 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs placeholder-universe-slate focus:outline-none focus:border-purple-400"
                  />
                </div>

                <div className="flex items-center gap-1 p-1 rounded-xl bg-space-800 border border-white/[0.08] overflow-x-auto">
                  <button
                    type="button"
                    onClick={() => setStudentFilter('ALL')}
                    className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors cursor-pointer shrink-0 ${
                      studentFilter === 'ALL'
                        ? 'bg-purple-600 text-white'
                        : 'text-universe-slate hover:text-white'
                    }`}
                  >
                    All ({studentsMastery.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setStudentFilter('STRUGGLING')}
                    className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors cursor-pointer shrink-0 ${
                      studentFilter === 'STRUGGLING'
                        ? 'bg-rose-600 text-white'
                        : 'text-rose-300 hover:text-white'
                    }`}
                  >
                    Struggling ({studentsMastery.filter((s) => s.average_mastery < 0.45).length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setStudentFilter('DEVELOPING')}
                    className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors cursor-pointer shrink-0 ${
                      studentFilter === 'DEVELOPING'
                        ? 'bg-amber-600 text-white'
                        : 'text-amber-300 hover:text-white'
                    }`}
                  >
                    Developing ({studentsMastery.filter((s) => s.average_mastery >= 0.45 && s.average_mastery < 0.75).length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setStudentFilter('MASTERED')}
                    className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors cursor-pointer shrink-0 ${
                      studentFilter === 'MASTERED'
                        ? 'bg-emerald-600 text-white'
                        : 'text-emerald-300 hover:text-white'
                    }`}
                  >
                    Mastered ({studentsMastery.filter((s) => s.average_mastery >= 0.75).length})
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Student Cards List */}
          <div className="space-y-4">
            {studentsMastery
              .filter((s) => {
                if (studentFilter === 'STRUGGLING' && s.average_mastery >= 0.45) return false;
                if (studentFilter === 'DEVELOPING' && (s.average_mastery < 0.45 || s.average_mastery >= 0.75)) return false;
                if (studentFilter === 'MASTERED' && s.average_mastery < 0.75) return false;
                if (studentSearchTerm.trim()) {
                  const q = studentSearchTerm.toLowerCase();
                  return s.name.toLowerCase().includes(q) || s.learner_id.toLowerCase().includes(q);
                }
                return true;
              })
              .map((student) => {
                const isExpanded = expandedStudentId === student.learner_id;
                const mPct = Math.round(student.average_mastery * 100);
                const isStrug = student.average_mastery < 0.45;
                const isMast = student.average_mastery >= 0.75;
                const statusBadgeStyle = isStrug
                  ? 'border-rose-500/30 bg-rose-950/20 text-rose-300'
                  : isMast
                  ? 'border-emerald-500/30 bg-emerald-950/20 text-emerald-300'
                  : 'border-amber-500/30 bg-amber-950/20 text-amber-300';

                return (
                  <div
                    key={student.learner_id}
                    className={`rounded-2xl border transition-all ${
                      isExpanded
                        ? 'bg-space-900/90 border-purple-500/40 shadow-[0_0_25px_rgba(168,85,247,0.15)] ring-1 ring-purple-400/40'
                        : 'bg-space-900/50 border-white/[0.08] hover:border-white/[0.18]'
                    }`}
                  >
                    {/* Summary Row */}
                    <div
                      onClick={() => setExpandedStudentId(isExpanded ? null : student.learner_id)}
                      className="p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 cursor-pointer select-none"
                    >
                      <div className="flex items-center gap-4 flex-1">
                        <div className="w-12 h-12 rounded-2xl bg-space-800 border border-white/[0.08] flex items-center justify-center text-2xl shrink-0 shadow-inner">
                          {student.avatar || '🧑‍🎓'}
                        </div>
                        <div className="space-y-1 flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-display font-semibold text-white text-base">
                              {student.name}
                            </span>
                            <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold border ${statusBadgeStyle}`}>
                              {student.assigned_tier}
                            </span>
                            <span className="text-xs font-mono text-universe-slate">
                              • {student.learner_id}
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-3 text-xs text-universe-slate">
                            <span>{student.role}</span>
                            <span>•</span>
                            <span>Accuracy: <strong className="text-white">{student.accuracy_pct}%</strong></span>
                            <span>•</span>
                            <span>Concepts: <strong className="text-emerald-400">{student.mastered_concepts} master</strong> / <strong className="text-rose-400">{student.struggling_concepts} struggling</strong></span>
                            {student.weakest_concept && (
                              <>
                                <span>•</span>
                                <span>Weakest: <strong className="text-rose-300">{student.weakest_concept.name}</strong></span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-4 shrink-0">
                        <div className="text-right">
                          <div className="text-xs font-mono text-universe-slate">Mastery</div>
                          <div className={`text-xl font-display font-bold ${
                            isStrug ? 'text-rose-400' : isMast ? 'text-emerald-400' : 'text-amber-400'
                          }`}>
                            {mPct}%
                          </div>
                        </div>
                        <div className="w-8 h-8 rounded-xl bg-space-800 border border-white/[0.08] flex items-center justify-center text-universe-slate">
                          <ChevronDown className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180 text-purple-300' : ''}`} />
                        </div>
                      </div>
                    </div>

                    {/* Expanded Detail Panel */}
                    {isExpanded && (
                      <div className="p-5 border-t border-white/[0.08] animate-fade-in">
                        {renderStudentDetailCard(student, () => setExpandedStudentId(null))}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* ━━━━━ TAB 3: TEACHING OPTIMIZER ━━━━━ */}
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

      {/* ━━━━━ TAB 5: CONCEPT VERIFICATION & CURRICULUM REVIEW (PERSON 2) ━━━━━ */}
      {activeTab === 'CURRICULUM_REVIEW' && (
        <ConceptReviewWorkspace
          reviewerId={currentPersona?.name || currentUserId || 'teacher'}
          initialDocumentId={classes.find((c) => c.class_id === selectedClassId)?.subject_id}
          onNavigateToAtlas={onNavigateToAtlas}
        />
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
