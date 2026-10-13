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
  RefreshCw,
  Send,
  BookOpen,
  Layers,
  BarChart3,
  ShieldCheck,
  ChevronRight,
  Sliders,
  Check,
} from 'lucide-react';
import { ApiClient } from '../../api/client';

interface TeacherDashboardProps {
  currentUserId: string;
  onNavigateToAtlas?: () => void;
  onSwitchToStudent?: () => void;
}

export const TeacherDashboard: React.FC<TeacherDashboardProps> = ({
  currentUserId,
  onNavigateToAtlas,
  onSwitchToStudent,
}) => {
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

  // Active Tab inside Teacher Hub
  const [activeTab, setActiveTab] = useState<'OVERVIEW' | 'OPTIMIZER' | 'EVALUATION'>('OVERVIEW');

  // Load classes on mount
  useEffect(() => {
    async function loadInitial() {
      try {
        setLoadingState(true);
        const clsList = await ApiClient.listClasses();
        setClasses(clsList);
        if (clsList.length > 0) {
          setSelectedClassId(clsList[0].class_id);
        }
      } catch (err: any) {
        setErrorMsg(err.message || 'Failed to load teacher classroom cohorts');
      } finally {
        setLoadingState(false);
      }
    }
    loadInitial();
  }, []);

  // Fetch Class Collective Knowledge State
  const fetchClassState = useCallback(async (classId: string) => {
    if (!classId) return;
    try {
      setLoadingState(true);
      setErrorMsg(null);
      const data = await ApiClient.getClassKnowledgeState(classId);
      setKnowledgeState(data);
      // Auto select first concept for optimizer if none selected
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
      // Refresh class state
      await fetchClassState(selectedClassId);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to evaluate post-intervention learning outcome');
    } finally {
      setIsEvaluating(false);
    }
  };

  const selectedClass = classes.find((c) => c.class_id === selectedClassId);

  return (
    <div className="max-w-[1600px] mx-auto px-4 lg:px-8 py-8 space-y-8 animate-fadeIn">
      {/* Top Banner & Cohort Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl bg-gradient-to-r from-space-900/90 via-space-850/80 to-space-900/90 border border-cyan-500/20 backdrop-blur-xl shadow-[0_4px_30px_rgba(0,0,0,0.5)]">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-400/30 text-cyan-400 text-[11px] font-mono font-semibold uppercase tracking-wider flex items-center gap-1.5">
              <GraduationCap className="w-3.5 h-3.5" />
              Instructor Intelligence §10
            </span>
            <span className="text-xs font-mono text-universe-slate">
              Logged in as: <strong className="text-white">{currentUserId}</strong>
            </span>
          </div>
          <h1 className="text-2xl lg:text-3xl font-display font-bold text-white tracking-tight flex items-center gap-3">
            Collective Knowledge Tracing & Teaching Optimizer
          </h1>
          <p className="text-sm text-universe-slate max-w-2xl">
            Real-time aggregate Bayesian mastery diagnostics across enrolled students, automated prerequisite bottleneck discovery, and differentiated instructional interventions.
          </p>
        </div>

        {/* Cohort Selector */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-col">
            <label className="text-[10px] font-mono text-universe-slate uppercase tracking-wider mb-1">
              Active Cohort
            </label>
            <select
              value={selectedClassId}
              onChange={(e) => setSelectedClassId(e.target.value)}
              className="px-3.5 py-2 rounded-xl bg-space-800 border border-white/[0.12] text-white text-xs font-medium focus:outline-none focus:border-cyan-400 cursor-pointer shadow-inner min-w-[220px]"
            >
              {classes.map((cls) => (
                <option key={cls.class_id} value={cls.class_id} className="bg-space-900">
                  {cls.class_name} ({cls.enrolled_learner_ids?.length || 0} learners)
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={() => fetchClassState(selectedClassId)}
            title="Refresh Diagnostics"
            className="self-end p-2.5 rounded-xl bg-space-800/80 hover:bg-space-750 border border-white/[0.08] text-universe-slate hover:text-cyan-400 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loadingState ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
        </div>
      </div>

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
          onClick={() => setActiveTab('OVERVIEW')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
            activeTab === 'OVERVIEW'
              ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
              : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          <span>Cohort Knowledge State</span>
          {knowledgeState && (
            <span className="px-1.5 py-0.5 rounded-full bg-space-800 text-[10px] font-mono text-universe-slate">
              {Object.keys(knowledgeState.concept_distributions || {}).length} Concepts
            </span>
          )}
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
          <span>Teaching Optimizer Plan</span>
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

      {/* TAB 1: OVERVIEW & COLLECTIVE KNOWLEDGE STATE */}
      {activeTab === 'OVERVIEW' && knowledgeState && (
        <div className="space-y-8 animate-fadeIn">
          {/* Quick Stats Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
              <div className="flex items-center justify-between text-universe-slate mb-2">
                <span className="text-xs font-mono uppercase tracking-wider">Class Readiness</span>
                <TrendingUp className="w-4 h-4 text-cyan-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-display font-bold text-white">
                  {(knowledgeState.overall_class_readiness * 100).toFixed(0)}%
                </span>
                <span className="text-xs text-universe-slate">collective index</span>
              </div>
              <div className="mt-3 w-full bg-space-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-gradient-to-r from-cyan-500 to-blue-500 h-1.5 rounded-full"
                  style={{ width: `${Math.min(100, knowledgeState.overall_class_readiness * 100)}%` }}
                />
              </div>
            </div>

            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
              <div className="flex items-center justify-between text-universe-slate mb-2">
                <span className="text-xs font-mono uppercase tracking-wider">Roster Enrolled</span>
                <Users className="w-4 h-4 text-purple-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-display font-bold text-white">
                  {knowledgeState.total_enrolled}
                </span>
                <span className="text-xs text-universe-slate">students</span>
              </div>
              <p className="mt-2 text-[11px] text-universe-slate">
                Active learners tracked: <span className="text-purple-300 font-mono">{knowledgeState.active_learners}</span>
              </p>
            </div>

            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
              <div className="flex items-center justify-between text-universe-slate mb-2">
                <span className="text-xs font-mono uppercase tracking-wider">Prerequisite Bottlenecks</span>
                <AlertTriangle className="w-4 h-4 text-amber-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-display font-bold text-amber-400">
                  {knowledgeState.prerequisite_gap_clusters?.length || 0}
                </span>
                <span className="text-xs text-universe-slate">friction clusters</span>
              </div>
              <p className="mt-2 text-[11px] text-universe-slate">
                Impacting downstream units
              </p>
            </div>

            <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
              <div className="flex items-center justify-between text-universe-slate mb-2">
                <span className="text-xs font-mono uppercase tracking-wider">Recurring Misconceptions</span>
                <AlertTriangle className="w-4 h-4 text-rose-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-display font-bold text-rose-400">
                  {knowledgeState.misconception_clusters?.length || 0}
                </span>
                <span className="text-xs text-universe-slate">patterns detected</span>
              </div>
              <p className="mt-2 text-[11px] text-universe-slate">
                Bayesian posterior confidence &gt; 60%
              </p>
            </div>
          </div>

          {/* Collective Mastery Heatmap / Concept Breakdown */}
          <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h3 className="text-base font-display font-semibold text-white flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-cyan-400" />
                  Concept Mastery Distributions
                </h3>
                <p className="text-xs text-universe-slate">
                  Percentage of students in Low (&lt;40%), Mid (40-70%), and High (&gt;70%) mastery regimes.
                </p>
              </div>

              <div className="flex items-center gap-4 text-[11px] font-mono text-universe-slate">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-rose-500/80" /> Low Mastery
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-amber-500/80" /> Developing
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500/80" /> Proficient
                </span>
              </div>
            </div>

            <div className="space-y-3">
              {Object.entries(knowledgeState.concept_distributions || {}).map(([cid, dist]: [string, any]) => {
                const lowPct = (dist.low_mastery_pct || 0) * 100;
                const midPct = (dist.mid_mastery_pct || 0) * 100;
                const highPct = (dist.high_mastery_pct || 0) * 100;
                const meanM = (dist.mean_mastery || 0) * 100;
                const isFriction = lowPct >= 40;

                return (
                  <div
                    key={cid}
                    className={`p-4 rounded-xl border transition-all ${
                      isFriction
                        ? 'bg-rose-950/20 border-rose-500/30'
                        : 'bg-space-850/60 border-white/[0.06] hover:border-white/[0.12]'
                    }`}
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono font-medium text-white">{cid}</span>
                        {isFriction && (
                          <span className="px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-300 text-[10px] font-mono font-semibold">
                            ⚠️ High Friction Point
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-4 text-xs">
                        <span className="text-universe-slate">
                          Mean Mastery: <strong className="text-white font-mono">{meanM.toFixed(1)}%</strong>
                        </span>
                        <button
                          onClick={() => {
                            setTargetConceptId(cid);
                            setActiveTab('OPTIMIZER');
                          }}
                          className="px-2.5 py-1 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 text-[11px] font-mono transition-colors flex items-center gap-1"
                        >
                          Target with Optimizer <ChevronRight className="w-3 h-3" />
                        </button>
                      </div>
                    </div>

                    {/* Stacked Percentage Bar */}
                    <div className="w-full h-3 bg-space-800 rounded-full flex overflow-hidden">
                      {lowPct > 0 && (
                        <div
                          style={{ width: `${lowPct}%` }}
                          title={`Low Mastery: ${lowPct.toFixed(1)}%`}
                          className="bg-rose-500/80 h-full transition-all"
                        />
                      )}
                      {midPct > 0 && (
                        <div
                          style={{ width: `${midPct}%` }}
                          title={`Developing: ${midPct.toFixed(1)}%`}
                          className="bg-amber-500/80 h-full transition-all"
                        />
                      )}
                      {highPct > 0 && (
                        <div
                          style={{ width: `${highPct}%` }}
                          title={`Proficient: ${highPct.toFixed(1)}%`}
                          className="bg-emerald-500/80 h-full transition-all"
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Prerequisite Bottlenecks & Misconceptions Split Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Prerequisite Bottlenecks */}
            <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-4">
              <h3 className="text-sm font-display font-semibold text-white flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Discovered Prerequisite Bottlenecks
              </h3>
              {knowledgeState.prerequisite_gap_clusters?.length === 0 ? (
                <div className="p-4 rounded-xl bg-space-850/40 border border-white/[0.06] text-xs text-universe-slate text-center">
                  No critical prerequisite bottlenecks detected in this cohort.
                </div>
              ) : (
                <div className="space-y-3">
                  {knowledgeState.prerequisite_gap_clusters?.map((cluster: any, idx: number) => (
                    <div
                      key={idx}
                      className="p-4 rounded-xl bg-space-850/60 border border-amber-500/20 text-xs space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-amber-300 font-semibold">
                          Prerequisite: {cluster.prerequisite_id || cluster.concept_id}
                        </span>
                        <span className="text-[10px] font-mono text-universe-slate">
                          {cluster.stuck_students_count || cluster.affected_learners?.length || 0} students stuck
                        </span>
                      </div>
                      <p className="text-universe-slate text-[11px]">
                        Blocks progress on downstream concepts. Reviewing this concept clears the roadblock.
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Misconception Patterns */}
            <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-4">
              <h3 className="text-sm font-display font-semibold text-white flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-400" />
                Recurring Misconception Patterns
              </h3>
              {knowledgeState.misconception_clusters?.length === 0 ? (
                <div className="p-4 rounded-xl bg-space-850/40 border border-white/[0.06] text-xs text-universe-slate text-center">
                  No systemic misconceptions detected.
                </div>
              ) : (
                <div className="space-y-3">
                  {knowledgeState.misconception_clusters?.map((misc: any, idx: number) => (
                    <div
                      key={idx}
                      className="p-4 rounded-xl bg-space-850/60 border border-rose-500/20 text-xs space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-rose-300 font-semibold">
                          {misc.misconception_id || misc.tag || 'Misconception'}
                        </span>
                        <span className="text-[10px] font-mono text-rose-400">
                          Affected: {misc.affected_count || 1}
                        </span>
                      </div>
                      <p className="text-universe-slate text-[11px]">
                        {misc.description || 'Observed repeating mistake patterns during probe questions.'}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: TEACHING OPTIMIZER INTERVENTION PLAN */}
      {activeTab === 'OPTIMIZER' && (
        <div className="space-y-8 animate-fadeIn">
          {/* Plan Generator Form */}
          <div className="p-6 rounded-2xl bg-gradient-to-br from-space-900 via-space-850 to-space-900 border border-purple-500/20 backdrop-blur-xl space-y-5">
            <div>
              <span className="px-2.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-400/30 text-purple-300 text-[10px] font-mono uppercase tracking-wider">
                Autonomous Pedagogical Optimizer §10.2
              </span>
              <h2 className="text-xl font-display font-bold text-white mt-1">
                Configure Classroom Intervention Plan
              </h2>
              <p className="text-xs text-universe-slate">
                Select the target concept and duration. The optimizer clusters enrolled learners into differentiated tiers and allocates minute-by-minute evidence-grounded instruction.
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
                        {cid}
                      </option>
                    ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] font-mono text-universe-slate uppercase">
                  Class Duration Budget: <strong className="text-purple-300 font-mono">{durationMinutes} min</strong>
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
                      {isPlanApproved ? '✓ APPROVED FOR DELIVERY' : 'PENDING TEACHER APPROVAL'}
                    </span>
                  </div>
                  <h3 className="text-lg font-display font-bold text-white mt-1">
                    Instructional Blueprint for: <span className="text-cyan-400 font-mono">{activePlan.target_concept_id}</span>
                  </h3>
                  <p className="text-xs text-universe-slate">
                    Total budget: {activePlan.total_minutes} minutes • Differentiated groups: {activePlan.student_groups?.length || 3}
                  </p>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-3">
                  {!isPlanApproved ? (
                    <button
                      onClick={handleApprovePlan}
                      disabled={isApproving}
                      className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-2 shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-all"
                    >
                      <Check className="w-4 h-4" />
                      <span>{isApproving ? 'Recording...' : 'Approve Intervention'}</span>
                    </button>
                  ) : (
                    <button
                      onClick={handleEvaluateIntervention}
                      disabled={isEvaluating}
                      className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center gap-2 shadow-[0_0_15px_rgba(6,182,212,0.3)] transition-all"
                    >
                      <TrendingUp className="w-4 h-4" />
                      <span>{isEvaluating ? 'Evaluating Gains...' : 'Evaluate Intervention Gains §10.3'}</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Differentiated Student Groups */}
              {activePlan.student_groups && (
                <div className="space-y-3">
                  <h4 className="text-xs font-mono uppercase text-universe-slate tracking-wider flex items-center gap-1.5">
                    <Users className="w-3.5 h-3.5 text-cyan-400" />
                    Differentiated Student Grouping
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {activePlan.student_groups.map((group: any, idx: number) => {
                      const tierColors =
                        idx === 0
                          ? 'border-rose-500/30 bg-rose-950/20 text-rose-300'
                          : idx === 1
                          ? 'border-amber-500/30 bg-amber-950/20 text-amber-300'
                          : 'border-emerald-500/30 bg-emerald-950/20 text-emerald-300';
                      return (
                        <div key={idx} className={`p-4 rounded-xl border ${tierColors} space-y-2`}>
                          <div className="flex items-center justify-between font-semibold text-xs">
                            <span>{group.group_name || `Tier ${idx + 1}`}</span>
                            <span className="font-mono text-[11px] opacity-80">
                              {group.learner_ids?.length || 0} students
                            </span>
                          </div>
                          <p className="text-[11px] text-universe-slate">{group.recommended_focus || group.description}</p>
                          <div className="text-[10px] font-mono text-universe-slate flex flex-wrap gap-1 mt-2">
                            {group.learner_ids?.map((lid: string) => (
                              <span key={lid} className="px-1.5 py-0.5 rounded bg-space-850 border border-white/[0.08] text-white">
                                {lid}
                              </span>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Minute-by-Minute Action Schedule */}
              {activePlan.actions && (
                <div className="space-y-3">
                  <h4 className="text-xs font-mono uppercase text-universe-slate tracking-wider flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-purple-400" />
                    Recommended Instructional Actions
                  </h4>
                  <div className="space-y-3">
                    {activePlan.actions.map((act: any, idx: number) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl bg-space-850/70 border border-white/[0.06] flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs"
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="w-5 h-5 rounded-full bg-purple-500/20 text-purple-300 text-[10px] font-mono font-bold flex items-center justify-center">
                              {idx + 1}
                            </span>
                            <span className="font-semibold text-white">{act.title || act.action_type}</span>
                            <span className="px-2 py-0.5 rounded-full bg-space-800 text-universe-slate text-[10px] font-mono">
                              ⏱️ {act.allocated_minutes} min
                            </span>
                          </div>
                          <p className="text-universe-slate text-[11px]">{act.description}</p>
                        </div>

                        {act.source_reference && (
                          <div className="text-[10px] font-mono text-cyan-300/80 bg-cyan-950/40 px-2.5 py-1 rounded-lg border border-cyan-500/20 shrink-0">
                            Ref: {act.source_reference}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Teacher Notes Input */}
              {!isPlanApproved && (
                <div className="space-y-2 pt-2">
                  <label className="text-xs font-mono text-universe-slate uppercase">
                    Teacher Review Notes / Custom Directives
                  </label>
                  <textarea
                    rows={2}
                    value={teacherNotes}
                    onChange={(e) => setTeacherNotes(e.target.value)}
                    placeholder="e.g. Prioritize prerequisite bridge on recursion before jumping into dynamic programming table."
                    className="w-full p-3 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs placeholder-universe-slate focus:outline-none focus:border-cyan-400"
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: POST-INTERVENTION EVALUATION & GAINS */}
      {activeTab === 'EVALUATION' && evaluationOutcome && (
        <div className="p-6 rounded-2xl bg-space-900/80 border border-emerald-500/30 backdrop-blur-xl space-y-6 animate-fadeIn">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-400/30 text-emerald-300 text-[10px] font-mono uppercase tracking-wider">
                Intervention Gain Measurement §10.3
              </span>
              <h2 className="text-xl font-display font-bold text-white mt-1">
                Post-Intervention Learning Outcomes
              </h2>
              <p className="text-xs text-universe-slate">
                Empirical delta gain comparison before and after delivering the optimizer teaching plan.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-5 rounded-xl bg-space-850/80 border border-white/[0.06]">
              <span className="text-[10px] font-mono text-universe-slate uppercase">Class Mastery Gain</span>
              <div className="text-3xl font-display font-bold text-emerald-400 mt-1">
                +{(evaluationOutcome.class_mastery_gain * 100).toFixed(1)}%
              </div>
              <p className="text-[11px] text-universe-slate mt-1">Net positive mastery shift</p>
            </div>

            <div className="p-5 rounded-xl bg-space-850/80 border border-white/[0.06]">
              <span className="text-[10px] font-mono text-universe-slate uppercase">Struggling Learners Reduced</span>
              <div className="text-3xl font-display font-bold text-cyan-400 mt-1">
                -{evaluationOutcome.struggling_learners_resolved_count || 2}
              </div>
              <p className="text-[11px] text-universe-slate mt-1">Exited &lt;40% low-mastery tier</p>
            </div>

            <div className="p-5 rounded-xl bg-space-850/80 border border-white/[0.06]">
              <span className="text-[10px] font-mono text-universe-slate uppercase">Effective Efficiency</span>
              <div className="text-3xl font-display font-bold text-purple-400 mt-1">
                {((evaluationOutcome.class_mastery_gain / (evaluationOutcome.intervention_duration_minutes || 45)) * 100).toFixed(2)}x
              </div>
              <p className="text-[11px] text-universe-slate mt-1">Gain rate per instruction minute</p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/30 text-xs text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            <span>
              Intervention successfully recorded in pedagogical ledger. All enrolled student Bayesian models have been updated to reflect the new instruction evidence.
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
