import React, { useState } from 'react';
import type {
  ConceptNode,
  LearningSequenceResponse,
} from '../../api/client';
import {
  Compass,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
  BookOpen,
  HelpCircle,
  GitFork,
  Layers,
  Sparkles,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Network,
} from 'lucide-react';

export interface GuidedSequenceViewProps {
  sequenceData: LearningSequenceResponse | null;
  isLoading: boolean;
  selectedStartingConceptId: string | null;
  onSelectStartingConcept: (conceptId: string | null) => void;
  onStartLearning?: (conceptId: string) => void;
  onStartPractice?: (conceptId: string) => void;
  onSwitchToGraphView: (focusConceptId?: string) => void;
  allConcepts: ConceptNode[];
}

export const GuidedSequenceView: React.FC<GuidedSequenceViewProps> = ({
  sequenceData,
  isLoading,
  selectedStartingConceptId,
  onSelectStartingConcept,
  onStartLearning,
  onStartPractice,
  onSwitchToGraphView,
  allConcepts,
}) => {
  const [showUpstreamDetails, setShowUpstreamDetails] = useState(true);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-16 text-slate-400 space-y-4">
        <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm font-medium font-sans">Synthesizing chapter-coherent learning sequence...</p>
      </div>
    );
  }

  if (!sequenceData || sequenceData.sequence.length === 0) {
    return (
      <div className="p-8 text-center bg-space-900/40 border border-white/[0.08] rounded-2xl">
        <AlertCircle className="w-8 h-8 text-amber-400 mx-auto mb-2" />
        <h3 className="text-base font-semibold text-white">No Learning Sequence Available</h3>
        <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
          Please select a valid subject or upload curriculum notes to view the guided progression path.
        </p>
      </div>
    );
  }

  const { sequence, upstream_prerequisites, branching_points, cross_chapter_bridges, primary_recommendation } =
    sequenceData;

  // Map branching points by parent concept id
  const branchMap = new Map<string, Array<{ concept_id: string; name: string; chapter_name: string }>>();
  (branching_points || []).forEach((bp) => {
    branchMap.set(bp.parent_concept_id, bp.branches);
  });

  // Map cross chapter bridges by target concept id
  const bridgeMap = new Map<string, string>();
  (cross_chapter_bridges || []).forEach((br) => {
    bridgeMap.set(br.target_concept_id, br.explanation);
  });

  return (
    <div className="space-y-6">
      {/* ── Top Bar: Starting Concept Selector & View Mode Actions ── */}
      <div className="p-4 rounded-2xl bg-space-900/90 border border-white/[0.08] backdrop-blur-xl shadow-xl flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
        <div className="flex-1 max-w-xl">
          <label className="text-[10px] font-mono font-bold uppercase tracking-wider text-cyan-400 mb-1 block">
            Start Learning From Any Concept
          </label>
          <div className="relative">
            <select
              value={selectedStartingConceptId || ''}
              onChange={(e) => onSelectStartingConcept(e.target.value || null)}
              className="w-full bg-space-950 border border-white/[0.12] focus:border-cyan-400 text-white text-xs rounded-xl px-3 py-2 pr-8 appearance-none cursor-pointer outline-none transition-colors"
            >
              <option value="">Full Curriculum Sequence (Default from Chapter 1)</option>
              {allConcepts.map((c) => (
                <option key={c.concept_id} value={c.concept_id}>
                  {c.name}
                </option>
              ))}
            </select>
            <ChevronDown className="w-4 h-4 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
        </div>

        <div className="flex items-center gap-2 self-end md:self-auto">
          {selectedStartingConceptId && (
            <button
              type="button"
              onClick={() => onSelectStartingConcept(null)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-white/[0.05] hover:bg-white/[0.1] text-xs font-sans text-slate-300 hover:text-white border border-white/[0.08] transition-colors cursor-pointer"
              title="Reset to full curriculum starting from foundations"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Full Curriculum</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => onSwitchToGraphView(selectedStartingConceptId || undefined)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-cyan-500/10 hover:bg-cyan-500/20 text-xs font-sans font-semibold text-cyan-300 border border-cyan-500/30 hover:border-cyan-400 transition-colors cursor-pointer shadow-sm"
          >
            <Network className="w-3.5 h-3.5" />
            <span>Interactive Graph View</span>
          </button>
        </div>
      </div>

      {/* ── Upstream Prerequisites Warning Panel (If Selected Starting Concept has Dependencies) ── */}
      {upstream_prerequisites && upstream_prerequisites.length > 0 && (
        <div className="rounded-2xl bg-amber-950/30 border border-amber-500/40 p-4 shadow-lg backdrop-blur-md">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-amber-500/20 text-amber-300">
                <AlertCircle className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-display font-bold text-amber-200">
                  Upstream Prerequisites Recommended ({upstream_prerequisites.length})
                </h4>
                <p className="text-xs text-amber-300/80 mt-0.5">
                  Before diving into <strong className="text-white font-semibold">{sequenceData.starting_concept_name}</strong>, these foundational topics build the core theory:
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setShowUpstreamDetails(!showUpstreamDetails)}
              className="text-amber-400 hover:text-amber-200 p-1 rounded-lg transition-colors cursor-pointer"
            >
              {showUpstreamDetails ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          </div>

          {showUpstreamDetails && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 mt-3 pt-3 border-t border-amber-500/20">
              {upstream_prerequisites.map((u) => {
                return (
                  <div
                    key={u.concept_id}
                    className="flex items-center justify-between p-2 rounded-xl bg-space-950/60 border border-amber-500/20 text-xs"
                  >
                    <div className="min-w-0 pr-2">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-slate-200 truncate">{u.name}</span>
                        {u.is_direct && (
                          <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-amber-400/20 text-amber-300 font-bold uppercase">
                            Direct
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-slate-400 block">{u.chapter_name}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => onSelectStartingConcept(u.concept_id)}
                      className="text-[10px] font-mono text-cyan-400 hover:text-cyan-200 underline whitespace-nowrap cursor-pointer ml-1"
                    >
                      Start Here
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Single Primary Recommendation Banner (Deduplicated) ── */}
      {primary_recommendation && (
        <div className="p-4 rounded-2xl bg-gradient-to-r from-cyan-950/60 to-space-900/90 border border-cyan-500/30 shadow-xl backdrop-blur-xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-400/20 text-cyan-300 shadow-[0_0_15px_rgba(0,240,255,0.25)]">
              <Compass className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 font-bold">
                  Next Best Step
                </span>
                <span className="text-[10px] font-mono text-slate-400 px-2 py-0.5 rounded-full bg-white/[0.05]">
                  {primary_recommendation.chapter_name}
                </span>
              </div>
              <h3 className="text-base font-display font-bold text-white mt-0.5">
                {primary_recommendation.name}
              </h3>
              <p className="text-xs text-slate-300 mt-1 max-w-xl">
                {primary_recommendation.reason}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-end md:self-auto">
            {onStartLearning && (
              <button
                type="button"
                onClick={() => onStartLearning(primary_recommendation.concept_id)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-space-950 font-sans font-bold text-xs shadow-[0_0_15px_rgba(0,240,255,0.4)] transition-all cursor-pointer"
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span>Start Study</span>
              </button>
            )}
            {onStartPractice && (
              <button
                type="button"
                onClick={() => onStartPractice(primary_recommendation.concept_id)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-white/[0.08] hover:bg-white/[0.15] text-white font-sans font-semibold text-xs border border-white/[0.1] transition-colors cursor-pointer"
              >
                <HelpCircle className="w-3.5 h-3.5" />
                <span>Practice</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Step Progression Sequence ── */}
      <div className="space-y-4">
        <div className="flex items-center justify-between px-1">
          <h3 className="text-sm font-display font-bold text-slate-200 uppercase tracking-wider flex items-center gap-2">
            <Layers className="w-4 h-4 text-cyan-400" />
            <span>Guided Step Progression ({sequence.length} Steps)</span>
          </h3>
          <span className="text-xs font-mono text-slate-400">
            Ordered chapter-by-chapter without arbitrary skips
          </span>
        </div>

        <div className="space-y-3">
          {sequence.map((step) => {
            const isMastered = step.mastery >= 0.75;
            const branches = branchMap.get(step.concept_id) || [];
            const bridgeNote = bridgeMap.get(step.concept_id);

            return (
              <React.Fragment key={step.concept_id}>
                {/* Cross Chapter Transition Highlight */}
                {bridgeNote && (
                  <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-purple-950/30 border border-purple-500/30 text-purple-300 text-xs">
                    <ArrowRight className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                    <span><strong>Chapter Bridge:</strong> {bridgeNote}</span>
                  </div>
                )}

                <div
                  className={`p-4 rounded-2xl border transition-all ${
                    step.is_starting_concept
                      ? 'bg-space-900/90 border-cyan-400/80 shadow-[0_0_20px_rgba(0,240,255,0.15)] ring-1 ring-cyan-400/50'
                      : 'bg-space-900/60 border-white/[0.08] hover:border-white/[0.15]'
                  }`}
                >
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                    <div className="flex items-start gap-3">
                      {/* Step Number Badge */}
                      <div
                        className={`flex items-center justify-center w-10 h-10 rounded-xl font-mono text-xs font-bold shrink-0 ${
                          step.is_starting_concept
                            ? 'bg-cyan-400 text-space-950 shadow-[0_0_12px_#00F0FF]'
                            : isMastered
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : 'bg-space-950 text-slate-300 border border-white/[0.1]'
                        }`}
                      >
                        {step.step_number}
                      </div>

                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-sm font-display font-bold text-white">
                            {step.name}
                          </h4>
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/[0.06] text-slate-300">
                            {step.chapter_name}
                          </span>
                          {step.is_starting_concept && (
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-400/20 text-cyan-300 border border-cyan-400/40 font-bold uppercase">
                              ★ Starting Point
                            </span>
                          )}
                          {isMastered && (
                            <span className="flex items-center gap-1 text-[10px] font-mono text-emerald-400 font-semibold">
                              <CheckCircle2 className="w-3 h-3" /> Mastered
                            </span>
                          )}
                        </div>

                        {step.definition && (
                          <p className="text-xs text-slate-300/90 mt-1 line-clamp-2">
                            {step.definition}
                          </p>
                        )}

                        {/* Pedagogical Reason */}
                        <div className="mt-2 flex items-center gap-1.5 text-[11px] font-sans text-cyan-300/90">
                          <Sparkles className="w-3 h-3 text-cyan-400 shrink-0" />
                          <span>{step.reason}</span>
                        </div>

                        {/* Parallel Branch Indicator (e.g. Centripetal & Tangential Accel) */}
                        {branches.length > 1 && (
                          <div className="mt-2.5 p-2 rounded-xl bg-space-950/60 border border-white/[0.06] flex items-center gap-2 text-xs">
                            <GitFork className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                            <span className="text-slate-400 text-[11px]">
                              Parallel branches diverge here:{' '}
                              {branches.map((b, bIdx) => (
                                <span key={b.concept_id} className="text-slate-200 font-semibold">
                                  {b.name}{bIdx < branches.length - 1 ? ' and ' : ''}
                                </span>
                              ))}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Step Actions */}
                    <div className="flex items-center gap-2 shrink-0 self-end md:self-center">
                      {onStartLearning && (
                        <button
                          type="button"
                          onClick={() => onStartLearning(step.concept_id)}
                          className="px-3 py-1.5 rounded-xl bg-cyan-500/10 hover:bg-cyan-500/25 text-cyan-300 hover:text-cyan-200 text-xs font-sans font-semibold border border-cyan-500/30 transition-colors cursor-pointer"
                        >
                          Study
                        </button>
                      )}
                      {onStartPractice && (
                        <button
                          type="button"
                          onClick={() => onStartPractice(step.concept_id)}
                          className="px-3 py-1.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.1] text-slate-300 hover:text-white text-xs font-sans font-medium border border-white/[0.08] transition-colors cursor-pointer"
                        >
                          Practice
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => onSwitchToGraphView(step.concept_id)}
                        className="p-1.5 rounded-xl text-slate-400 hover:text-cyan-300 hover:bg-white/[0.05] transition-colors cursor-pointer"
                        title="Locate in Graph View"
                      >
                        <Network className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );
};
