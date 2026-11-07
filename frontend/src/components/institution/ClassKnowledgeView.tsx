import { useState, useEffect, useCallback } from 'react';
import { ApiClient } from '../../api/client';
import { getConceptDisplayName } from '../../utils/conceptName';

/**
 * ClassKnowledgeView — B2B Admin feature.
 * Shows aggregate student KT per institutional class.
 * Extracted from the old TeacherDashboard's "OVERVIEW" tab.
 */
export function ClassKnowledgeView({ currentUserId: _currentUserId }: { currentUserId: string }) {
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
