import React from 'react';
import type { Subject, LearnerProgress, KnowledgeGap, LearningTarget } from '../../api/client';
import { Play, Sparkles, AlertTriangle, BookOpen, Compass, ArrowUpRight, ShieldCheck, Activity } from 'lucide-react';

export interface DashboardProps {
  currentSubject: Subject;
  progress: LearnerProgress | null;
  gaps: KnowledgeGap[];
  nextTarget: LearningTarget | null;
  onNavigateToAtlas: () => void;
  onNavigateToPath: () => void;
  onNavigateToSession: (conceptId: string) => void;
  onNavigateToSources: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({
  currentSubject,
  progress,
  gaps,
  nextTarget,
  onNavigateToAtlas,
  onNavigateToPath,
  onNavigateToSession,
  onNavigateToSources,
}) => {
  const masteryPercent = progress ? Math.round(progress.average_mastery * 100) : 0;
  const explorationPercent = progress ? Math.round(progress.exploration_rate * 100) : 0;
  const masteredCount = progress?.mastered_concepts || 0;
  const totalCount = progress?.total_concepts || 0;

  return (
    <div className="space-y-8 animate-fade-in">
      
      {/* 1. Command Center Editorial Hero */}
      <section className="relative universe-panel rounded-3xl p-8 lg:p-12 overflow-hidden">
        {/* Subtle Ambient Light Geometry */}
        <div className="absolute top-0 right-0 w-[500px] h-[300px] bg-gradient-to-bl from-cyan-500/10 via-violet-500/5 to-transparent blur-3xl pointer-events-none" />
        <div className="absolute -bottom-10 left-1/4 w-[350px] h-[200px] bg-cyan-500/5 blur-2xl pointer-events-none" />
        
        <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          <div className="lg:col-span-8 space-y-4">
            <div className="flex items-center gap-2.5">
              <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_8px_#00F0FF]" />
              <span className="text-[11px] font-mono tracking-widest text-cyan-300 uppercase">
                ACTIVE DOMAIN // {currentSubject.title}
              </span>
            </div>

            <h1 className="text-3xl sm:text-4xl lg:text-5xl font-display font-extrabold text-white tracking-tight leading-[1.1]">
              Your knowledge, <br />
              <span className="bg-gradient-to-r from-white via-cyan-100 to-universe-slate bg-clip-text text-transparent">
                mapped in real-time.
              </span>
            </h1>

            <p className="text-sm text-universe-slate max-w-2xl leading-relaxed font-sans pt-1">
              Taproot continuously analyzes your comprehension topology using Bayesian Knowledge Tracing. 
              Prerequisite dependencies are mapped, knowledge decay is guarded, and optimal learning steps are algorithmically computed.
            </p>
          </div>

          <div className="lg:col-span-4 flex flex-col sm:flex-row lg:flex-col gap-3 justify-end lg:items-end pt-2">
            <button
              onClick={onNavigateToAtlas}
              className="w-full sm:w-auto px-6 py-3.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center justify-center gap-2 shadow-[0_0_24px_rgba(0,240,255,0.25)] hover:shadow-[0_0_32px_rgba(0,240,255,0.4)] transition-all group"
            >
              <Compass className="w-4 h-4 text-space-950 group-hover:rotate-45 transition-transform duration-300" />
              <span>Launch Knowledge Atlas</span>
              <ArrowUpRight className="w-4 h-4 text-space-950" />
            </button>

            <button
              onClick={onNavigateToSources}
              className="w-full sm:w-auto px-5 py-3 rounded-xl bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.08] hover:border-cyan-400/30 text-xs font-mono font-medium flex items-center justify-center gap-2 transition-all"
            >
              <BookOpen className="w-3.5 h-3.5 text-cyan-400" />
              <span>Ingested Sources ({currentSubject.page_count || 1} pgs)</span>
            </button>
          </div>
        </div>

        {/* 2. Knowledge Telemetry Strip (Integrated visual metric system, not separate detached cards) */}
        <div className="mt-10 pt-8 border-t border-white/[0.06] grid grid-cols-2 sm:grid-cols-4 gap-6 lg:gap-8">
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-universe-slate uppercase tracking-wider">
              <Activity className="w-3.5 h-3.5 text-emerald-400" />
              <span>Demonstrated Mastery</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl lg:text-4xl font-display font-bold text-emerald-400">
                {masteryPercent}%
              </span>
              <span className="text-[10px] font-mono text-universe-slate/70">BKT score</span>
            </div>
            <div className="w-full bg-space-800 h-1 rounded-full overflow-hidden mt-2">
              <div className="bg-emerald-400 h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(4, masteryPercent)}%` }} />
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-universe-slate uppercase tracking-wider">
              <Compass className="w-3.5 h-3.5 text-cyan-400" />
              <span>Exploration Rate</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl lg:text-4xl font-display font-bold text-cyan-400">
                {explorationPercent}%
              </span>
              <span className="text-[10px] font-mono text-universe-slate/70">
                {progress?.explored_concepts || 0}/{totalCount} units
              </span>
            </div>
            <div className="w-full bg-space-800 h-1 rounded-full overflow-hidden mt-2">
              <div className="bg-cyan-400 h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(4, explorationPercent)}%` }} />
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-universe-slate uppercase tracking-wider">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Mastered Concepts</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl lg:text-4xl font-display font-bold text-white">
                {masteredCount}
              </span>
              <span className="text-[10px] font-mono text-universe-slate/70">verified solid</span>
            </div>
            <div className="w-full bg-space-800 h-1 rounded-full overflow-hidden mt-2">
              <div className="bg-emerald-400/50 h-full rounded-full transition-all duration-700" style={{ width: `${totalCount > 0 ? (masteredCount / totalCount) * 100 : 0}%` }} />
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-universe-slate uppercase tracking-wider">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>Identified Gaps</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl lg:text-4xl font-display font-bold text-amber-400">
                {gaps.length < 10 ? `0${gaps.length}` : gaps.length}
              </span>
              <span className="text-[10px] font-mono text-universe-slate/70">prioritized</span>
            </div>
            <div className="w-full bg-space-800 h-1 rounded-full overflow-hidden mt-2">
              <div className="bg-amber-400 h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(100, gaps.length * 20)}%` }} />
            </div>
          </div>
        </div>
      </section>

      {/* 3. Hero Feature: "YOUR NEXT MOVE" Algorithmic Recommendation */}
      {nextTarget && (
        <section className="relative universe-panel rounded-3xl p-6 lg:p-8 border-cyan-500/30 overflow-hidden shadow-[0_8px_32px_rgba(0,240,255,0.08)]">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
            <div className="space-y-2 max-w-2xl">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-0.5 rounded bg-cyan-950/80 border border-cyan-500/40 text-cyan-300 font-mono text-[10px] font-bold tracking-widest uppercase flex items-center gap-1.5">
                  <Sparkles className="w-3 h-3 text-cyan-400" />
                  CURRENT TARGET IN LEARNING VECTOR
                </span>
                <span className="text-[10px] font-mono text-universe-slate hidden sm:inline">
                  Reasoning Engine: Phase 4
                </span>
              </div>

              <h2 className="text-xl sm:text-2xl font-display font-bold text-white tracking-tight">
                {nextTarget.concept_name || nextTarget.name || nextTarget.concept_id}
              </h2>

              <div className="p-3.5 rounded-xl bg-space-950/60 border border-white/[0.05] text-xs text-universe-slate font-sans leading-relaxed">
                <span className="font-mono text-cyan-400 font-semibold mr-1.5">TARGET RATIONALE //</span>
                {nextTarget.reason}
              </div>
            </div>

            <div className="flex flex-col sm:flex-row items-center gap-3 shrink-0">
              <button
                onClick={() => onNavigateToSession(nextTarget.concept_id)}
                className="w-full sm:w-auto px-6 py-3.5 rounded-xl bg-gradient-to-r from-cyan-400 to-sky-400 hover:from-cyan-300 hover:to-sky-300 text-space-950 font-display font-extrabold text-xs flex items-center justify-center gap-2 shadow-[0_0_24px_rgba(0,240,255,0.3)] transition-all hover:scale-[1.02]"
              >
                <Play className="w-4 h-4 fill-current" />
                <span>Begin Learning Session</span>
              </button>

              <button
                onClick={onNavigateToPath}
                className="w-full sm:w-auto px-4 py-3.5 rounded-xl bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.08] text-xs font-mono flex items-center justify-center gap-1.5 transition-all"
              >
                <span>View Path</span>
                <ArrowUpRight className="w-3.5 h-3.5 text-universe-slate" />
              </button>
            </div>
          </div>
        </section>
      )}

      {/* 4. Prioritized Knowledge Gaps Radar & Actions */}
      {gaps.length > 0 && (
        <section className="universe-panel rounded-3xl p-6 lg:p-8 space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-white/[0.06]">
            <div className="space-y-1">
              <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>Knowledge Gap Matrix ({gaps.length} detected)</span>
              </h3>
              <p className="text-xs text-universe-slate font-sans">
                Foundational concepts with high uncertainty or broken prerequisite chains.
              </p>
            </div>

            <button
              onClick={onNavigateToPath}
              className="text-xs font-mono text-cyan-400 hover:text-cyan-300 flex items-center gap-1 transition-colors"
            >
              <span>Explore Complete Learning Path</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {gaps.slice(0, 3).map((gap) => (
              <div
                key={gap.concept_id}
                onClick={() => onNavigateToSession(gap.concept_id)}
                className="group p-4 rounded-2xl bg-space-850/50 hover:bg-space-800/80 border border-amber-500/20 hover:border-amber-400/50 transition-all duration-200 cursor-pointer flex flex-col justify-between space-y-3"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/60 border border-amber-500/30 text-amber-300 font-bold">
                      {gap.category}
                    </span>
                    <span className="text-[10px] font-mono text-universe-slate">
                      PRIORITY {Math.round(gap.priority_score * 100)}%
                    </span>
                  </div>

                  <h4 className="text-sm font-display font-bold text-white mt-2 group-hover:text-amber-200 transition-colors uppercase">
                    {gap.concept_id.replace(/_/g, ' ')}
                  </h4>

                  <p className="text-xs text-universe-slate mt-1 line-clamp-2 leading-relaxed">
                    {gap.reason}
                  </p>
                </div>

                <div className="pt-2 border-t border-white/[0.05] flex items-center justify-between text-[11px] font-mono text-amber-300 group-hover:text-amber-200">
                  <span>Remediate Gap</span>
                  <Play className="w-3.5 h-3.5 fill-current" />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

    </div>
  );
};
